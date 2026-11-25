import gzip
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag
from xml.etree import ElementTree

from models import PackageUpdate
from release_notes import appstream_notes, fetch_notes_response, notes_diagnostic


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
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    rows = [line.split("\t") for line in result.stdout.splitlines() if line.strip()]
    return [row + [""] * (columns - len(row)) for row in rows if len(row) <= columns]


def _is_extension(ref: str, scope: str) -> bool:
    try:
        result = subprocess.run(
            ["flatpak", "info", "--show-metadata", scope, "--", ref],
            capture_output=True, text=True, check=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "[ExtensionOf]" in result.stdout.splitlines()


def get_flatpak_updates(sources: dict[str, str]) -> tuple[list[PackageUpdate], bool]:
    names = {
        source.removeprefix("flatpak:"): name
        for name, source in sources.items()
        if source.startswith("flatpak:")
    }
    local_rows = _list_rows(
        ["list", "--columns=ref:f,version:f,origin:f,installation:f,options:f"], 5,
    )
    if local_rows is None:
        return [], True

    installed = {}
    for ref, version, origin, installation, options in local_rows:
        if not (ref and origin and installation):
            continue
        if ref.count("/") == 2:
            kind = "runtime" if "runtime" in options.split(",") else "app"
            ref = f"{kind}/{ref}"
        installed.setdefault((origin, installation), {})[ref] = version

    updates = []
    failed = False
    for (origin, installation), apps in installed.items():
        scope = _installation_option(installation)
        remote_rows = _list_rows(
            ["remote-ls", "--updates", scope, "--columns=ref:f,name:f,version:f", "--", origin], 3,
        )
        if remote_rows is None:
            failed = True
            continue
        for ref, display_name, version in remote_rows:
            if ref not in apps or ref.count("/") != 3:
                continue
            kind, app_ref = ref.split("/", 1)
            app = app_ref.split("/", 1)[0]
            updates.append(PackageUpdate(
                name=names.get(app, app), old_pkgver=apps[ref], old_pkgrel="",
                new_pkgver=version, new_pkgrel="",
                flatpak_ref=app_ref,
                flatpak_installation=installation,
                flatpak_origin=origin,
                flatpak_kind=kind,
                flatpak_name=display_name,
                flatpak_extension=kind == "runtime" and _is_extension(ref, scope),
            ))
    return updates, failed


def _appstream_directory(update: PackageUpdate) -> Path | None:
    try:
        result = subprocess.run(
            ["flatpak", "info", "--show-location", _installation_option(update.flatpak_installation),
             "--", f"{update.flatpak_kind}/{update.flatpak_ref}"],
            capture_output=True, text=True, check=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    location = Path(result.stdout.strip())
    app, arch, branch = update.flatpak_ref.split("/")
    if location.parts[-5:-1] != (update.flatpak_kind, app, arch, branch):
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
                if any(bundle.text == ref for bundle in component.findall("bundle[@type='flatpak']")):
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
        result = _appstream_release(catalog, f"{update.flatpak_kind}/{update.flatpak_ref}", update.new_pkgver)
        if result:
            return result

    url = settings.get("url")
    platform = settings.get("platform")
    if settings.get("format") != "release-tables" or not url or not platform:
        return None
    response = fetch_notes_response(url, "La página oficial", timeout=8)
    if response is None:
        return notes_diagnostic("source_missing", "La página oficial configurada no está accesible.")
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
