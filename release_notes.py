import re
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath
from xml.etree import ElementTree

import requests


def notes_diagnostic(reason: str, message: str) -> dict:
    return {"type": "diagnostic", "reason": reason, "message": message, "url": ""}


class NotesLookupError(RuntimeError):
    def as_result(self) -> dict:
        return notes_diagnostic("unavailable", str(self))


def fetch_notes_response(url: str, service: str, *, headers: dict | None = None,
                         timeout: int = 5) -> requests.Response | None:
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except requests.Timeout as error:
        raise NotesLookupError(f"{service} no respondió a tiempo.") from error
    except requests.RequestException as error:
        raise NotesLookupError(f"No se pudo conectar con {service}.") from error

    if response.status_code == 200:
        return response
    if response.status_code == 404:
        return None
    if response.status_code == 429 or (
        response.status_code == 403 and (
            response.headers.get("X-RateLimit-Remaining") == "0" or response.headers.get("Retry-After")
        )
    ):
        raise NotesLookupError(f"{service} alcanzó su límite de peticiones.")
    if response.status_code in (401, 403):
        raise NotesLookupError(f"{service} denegó el acceso (HTTP {response.status_code}).")
    raise NotesLookupError(f"{service} devolvió HTTP {response.status_code}.")


def notes_objects(data, key: str, service: str) -> list[dict]:
    if not isinstance(data, list) or any(not isinstance(item, dict) or not isinstance(item.get(key), str) for item in data):
        raise NotesLookupError(f"{service} devolvió un listado inesperado.")
    return data


def matching_tag(tag: str, version: str, project: str) -> bool:
    tag, version, project = tag.casefold(), version.casefold(), project.casefold()
    return tag in {version, f"v{version}", f"{project}-{version}", f"{project}-v{version}",
                   f"release-{version}", f"release/{version}", f"version-{version}"}


def _version_key(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        return ()
    parts = tuple(int(part) for part in version.split("."))
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def range_start(old_version: str | None, new_version: str) -> str | None:
    if not old_version:
        return None
    old_epoch, _, old = old_version.rpartition(":")
    new_epoch, _, new = new_version.rpartition(":")
    if (old_epoch or "0") == (new_epoch or "0") and () < _version_key(old) < _version_key(new):
        return old
    return None


def _between(version: str, old: str | None, new: str) -> bool:
    return bool(old and _version_key(old) < _version_key(version) < _version_key(new))


def earlier_release_notes(
    releases: Iterable[dict], project: str, old: str | None, new: str,
    body_key: str, release_url: Callable[[dict], str],
) -> dict[str, dict]:
    notes = {}
    if not old:
        return notes
    for release in releases:
        if any(release.get(flag) for flag in ("draft", "prerelease", "upcoming_release")):
            continue
        tag = release.get("tag_name") or ""
        match = re.search(r"[0-9]+(?:\.[0-9]+)+$", tag)
        if not match:
            continue
        version = match[0]
        if matching_tag(tag, version, project) and _between(version, old, new):
            body = published_notes(release.get(body_key))
            if body:
                notes.setdefault(version, {"type": "text", "body": body, "url": release_url(release)})
    return notes


def combine_version_notes(version: str, target: dict | None, earlier: dict[str, dict]) -> dict | None:
    if not earlier:
        return target

    entries = {}
    fallback = None
    if target and target["type"] == "range":
        entries.update((entry["version"], entry) for entry in target["entries"])
        fallback = target["fallback"]
    elif target and target["type"] in {"text", "link"}:
        entries[version] = target
    else:
        fallback = target
    entries.update(earlier)
    ordered = sorted(entries, key=_version_key, reverse=True)
    return {"type": "range", "entries": [{**entries[item], "version": item} for item in ordered],
            "fallback": fallback, "target_found": version in entries}


def published_notes(body: str | None) -> str | None:
    body = (body or "").replace("\r\n", "\n").strip()
    lines = [line.strip(" #*`_-.:") for line in body.splitlines() if line.strip()]
    boilerplate = r"(?:new (?:version bump|release)|version bump|bump (?:the )?version|release)(?:\s+(?:to\s+)?v?\d[\w.+-]*)?"
    for line in lines:
        if line and not re.fullmatch(boilerplate, line, re.I) and not re.match(r"full changelog[*_`]*\s*:", line, re.I):
            return body
    return None


def appstream_notes(release: ElementTree.Element) -> dict | None:
    descriptions = release.findall("description")
    language = "{http://www.w3.org/XML/1998/namespace}lang"
    description = next((node for node in descriptions if not node.get(language)), None)
    if description is None and descriptions:
        description = descriptions[0]

    lines = []
    if description is not None:
        for node in description:
            if node.tag == "p" and not node.get(language):
                lines.append(" ".join("".join(node.itertext()).split()))
            elif node.tag in {"ul", "ol"} and not node.get(language):
                for item in node.findall("li"):
                    if not item.get(language):
                        lines.append(f"- {' '.join(''.join(item.itertext()).split())}")
    body = "\n".join(line for line in lines if line).strip()
    url = release.findtext("url[@type='details']") or ""
    if body:
        return {"type": "text", "body": body, "url": url}
    if url:
        return {"type": "link", "url": url}
    return None


_METAINFO_SUFFIXES = (".metainfo.xml", ".appdata.xml", ".metainfo.xml.in", ".appdata.xml.in")
_NEWS_FILE = re.compile(r"(?:changelog|changes|news|release[-_ ]?notes)(?:\.(?:md|rst|txt|markdown))?", re.I)
_VERSION_HEADING = re.compile(
    r"^(#{1,6}\s+)?(?:(?:version|release|(?:overview of )?changes in)\s+)?\[?v?(\d[\w.+-]*)\]?"
    r"(?:\s+[-–—:]\s+.*|\s+\(.+\)|\s+\d{4}-\d\d-\d\d|,\s+\d{1,2}-\d{1,2}-\d{4}|:)?$",
    re.I,
)


def _notes_sections(text: str) -> Iterable[tuple[str, str]]:
    lines = text.splitlines()
    start = level = version = underline = fence = None
    for index, line in enumerate(lines):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker and (marker[1][0] == "`" or marker[2].strip()):
            fence = marker[1]
            continue
        separator = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if not re.fullmatch(r"[=~-]{3,}", separator):
            separator = ""
        markdown = re.match(r"^(#{1,6})\s", line)
        heading = _VERSION_HEADING.fullmatch(line.strip()) if markdown or (separator and line == line.lstrip()) else None
        section_ends = (heading or (markdown and level and len(markdown[1]) <= level)
                        or (underline and separator and separator[0] == underline))
        if start is not None and section_ends:
            if body := published_notes("\n".join(lines[start:index])):
                yield version, body
            start = None
        if heading:
            version = heading[2]
            start = index + (2 if separator else 1)
            level = len(heading[1].strip()) if heading[1] else None
            underline = separator[0] if separator else None
    if start is not None and (body := published_notes("\n".join(lines[start:]))):
        yield version, body


def find_file_notes(
    version: str, configured_file: str | None, list_files: Callable[[], Iterable[str]],
    read_file: Callable[[str], str | None], file_url: Callable[[str], str], *, old_version: str | None = None,
) -> dict | None:
    if configured_file:
        paths = [configured_file]
    else:
        paths = []
        for path in list_files():
            parts = PurePosixPath(path).parts
            if not parts or (len(parts) > 1 and parts[0].casefold() not in {"appstream", "data", "doc", "docs", "resources"}):
                continue
            if path.casefold().endswith(_METAINFO_SUFFIXES) or _NEWS_FILE.fullmatch(parts[-1]):
                paths.append(path)
        metafiles = [path for path in paths if path.casefold().endswith(_METAINFO_SUFFIXES)]
        # Si el árbol publica varios componentes, la configuración identifica el correcto.
        paths = sorted((path for path in paths if path not in metafiles), key=lambda path: (path.count("/"), path))
        if len(metafiles) == 1:
            paths.insert(0, metafiles[0])

    earlier = {}
    general = None
    for path in paths[:4]:
        text = read_file(path)
        if not text:
            continue
        url = file_url(path)
        if path.casefold().endswith((".xml", ".xml.in")):
            try:
                root = ElementTree.fromstring(text)
            except ElementTree.ParseError:
                continue
            candidates = {}
            for release in root.findall("./releases/release"):
                label = release.get("version", "")
                if label != version and (release.get("type") == "development" or not _between(label, old_version, version)):
                    continue
                result = appstream_notes(release)
                if result and (result["type"] == "link" or published_notes(result["body"])):
                    result["url"] = result["url"] or url
                    candidates.setdefault(label, result)
        else:
            candidates = {}
            for label, body in _notes_sections(text):
                if label == version or _between(label, old_version, version):
                    candidates.setdefault(label, {"type": "text", "body": body, "url": url})
            general = general or {"type": "general", "url": url}
        target = candidates.pop(version, None)
        earlier = {**candidates, **earlier}
        if target:
            return combine_version_notes(version, target, earlier)
    return combine_version_notes(version, general, earlier)
