import gzip
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag
from xml.etree import ElementTree

import requests

from models import PackageUpdate
from release_notes import appstream_notes


def _installation_option(installation: str) -> str:
    if installation in {"user", "system"}:
        return f"--{installation}"
    return f"--installation={installation}"


def _list_rows(args: list[str], columns: int) -> list[list[str]] | None:
    try:
        result = subprocess.run(
            ["flatpak", *args], capture_output=True, text=True, check=True,
            env={**os.environ, "LC_ALL": "C"}, timeout=15,
        )
    except FileNotFoundError:
        return []
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("⚠ No se pudo completar la consulta de Flatpak.", file=sys.stderr)
        return None

    rows = [line.split("\t") for line in result.stdout.splitlines()]
    return [row for row in rows if len(row) == columns]


def get_flatpak_updates(sources: dict[str, str]) -> tuple[list[PackageUpdate], bool]:
    names = {
        source.removeprefix("flatpak:"): name
        for name, source in sources.items()
        if source.startswith("flatpak:")
    }
    local_rows = _list_rows(
        ["list", "--app", "--columns=application:f,version:f,arch:f,branch:f,origin:f,installation:f"], 6,
    )
    if local_rows is None:
        return [], True

    installed = {}
    for app, version, arch, branch, origin, installation in local_rows:
        if app and origin and installation:
            installed.setdefault((origin, installation), {})[app, arch, branch] = version

    updates = []
    failed = False
    for (origin, installation), apps in installed.items():
        scope = _installation_option(installation)
        remote_rows = _list_rows(
            ["remote-ls", "--app", "--updates", scope,
             "--columns=application:f,version:f,arch:f,branch:f", "--", origin], 4,
        )
        if remote_rows is None:
            failed = True
            continue
        for app, version, arch, branch in remote_rows:
            if (app, arch, branch) in apps:
                updates.append(PackageUpdate(
                    name=names.get(app, app), old_pkgver=apps[app, arch, branch], old_pkgrel="",
                    new_pkgver=version, new_pkgrel="",
                    flatpak_ref=f"{app}/{arch}/{branch}",
                    flatpak_installation=installation,
                    flatpak_origin=origin,
                ))
    return updates, failed


def _appstream_directory(update: PackageUpdate) -> Path | None:
    try:
        result = subprocess.run(
            ["flatpak", "info", "--show-location", _installation_option(update.flatpak_installation),
             "--", update.flatpak_ref],
            capture_output=True, text=True, check=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    location = Path(result.stdout.strip())
    app, arch, branch = update.flatpak_ref.split("/")
    if location.parts[-5:-1] != ("app", app, arch, branch):
        return None
    return location.parents[4] / "appstream" / update.flatpak_origin / arch / "active"


def _appstream_release(catalog: Path, ref: str, version: str) -> dict | None:
    open_catalog = gzip.open if catalog.suffix == ".gz" else open
    try:
        with open_catalog(catalog, "rb") as source:
            events = ElementTree.iterparse(source, events=("start", "end"))
            _, root = next(events)
            for event, component in events:
                if event != "end" or component.tag != "component":
                    continue
                if any(bundle.text == f"app/{ref}" for bundle in component.findall("bundle[@type='flatpak']")):
                    for release in component.findall("./releases/release"):
                        if release.get("version") == version:
                            return appstream_notes(release)
                root.remove(component)
    except (OSError, EOFError, ElementTree.ParseError, StopIteration):
        return None
    return None


def fetch_release_notes(update: PackageUpdate, settings: dict[str, str]) -> dict | None:
    if not update.new_pkgver:
        return None

    directory = _appstream_directory(update)
    if directory is not None:
        catalog = directory / "appstream.xml"
        if not catalog.is_file():
            catalog = directory / "appstream.xml.gz"
        result = _appstream_release(catalog, update.flatpak_ref, update.new_pkgver)
        if result:
            return result

    url = settings.get("url")
    platform = settings.get("platform")
    if settings.get("format") != "release-tables" or not url or not platform:
        return None
    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
    except requests.RequestException:
        return None
    return parse_release_tables(response.text, update.new_pkgver, url, platform)


JSON_LD = re.compile(r'<script\b[^>]*\btype=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def _normalize_release_version(value: str) -> str:
    return re.sub(r"\s*\((\d+)\)$", r".\1", " ".join(value.split()))


@dataclass
class Table:
    anchor: str
    rows: list[list[str]] = field(default_factory=list)


class ReleaseTables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[Table] = []
        self.anchor = ""
        self.released = False
        self.table: Table | None = None
        self.row: list[str] | None = None
        self.capture: str | None = None
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.anchor = ""
            self.capture = tag
            self.parts = []
        elif tag == "h3":
            self.anchor = dict(attrs).get("id") or ""
        elif tag == "table" and self.released:
            self.table = Table(self.anchor)
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"th", "td"} and self.row is not None:
            self.capture = tag
            self.parts = []
        elif tag in {"br", "p", "li"} and self.capture:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == self.capture:
            value = "".join(self.parts)
            if tag == "h2":
                self.released = value.strip().casefold() == "released"
            elif self.row is not None:
                self.row.append(value.strip())
            self.capture = None
        elif tag == "tr" and self.table is not None and self.row:
            self.table.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.table.rows:
                self.tables.append(self.table)
            self.table = None


def parse_release_tables(html: str, version: str, url: str, platform: str) -> dict | None:
    platform = platform.casefold()
    platform_pattern = re.compile(rf"\b{re.escape(platform)}\b", re.I)

    for script in JSON_LD.finditer(html):
        try:
            article = json.loads(script[1])
        except ValueError:
            continue
        if isinstance(article, dict) and isinstance(article.get("articleBody"), str):
            html = article["articleBody"]
            break

    parser = ReleaseTables()
    parser.feed(html)
    found: Table | None = None
    notes = []
    for table in parser.tables:
        headings = [" ".join(cell.split()).casefold() for cell in table.rows[0]]
        if found is not None and (table.anchor != found.anchor or platform in headings):
            break
        if platform in headings:
            column = headings.index(platform)
            if any(len(row) > column and _normalize_release_version(row[column]) == version for row in table.rows[1:]):
                found = table
        elif found is not None and {"description", "platforms"} <= set(headings):
            description = headings.index("description")
            platforms = headings.index("platforms")
            title = headings.index("feature title") if "feature title" in headings else None
            for row in table.rows[1:]:
                if len(row) != len(headings):
                    continue
                if not platform_pattern.search(row[platforms]):
                    continue
                body = " ".join(row[description].split())
                if body:
                    if title is not None and row[title]:
                        body = f"**{' '.join(row[title].split())}** — {body}"
                    notes.append(f"- {body}")

    if found is None or not notes:
        return None
    url = f"{urldefrag(url).url}#{found.anchor}" if found.anchor else url
    return {"type": "text", "url": url, "body": "\n".join(notes)}
