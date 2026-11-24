import re
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath
from xml.etree import ElementTree


def matching_tag(tag: str, version: str, project: str) -> bool:
    tag, version, project = tag.casefold(), version.casefold(), project.casefold()
    return tag in {version, f"v{version}", f"{project}-{version}", f"{project}-v{version}",
                   f"release-{version}", f"release/{version}", f"version-{version}"}


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
    r"^(#{1,6}\s+)?(?:version\s+|release\s+)?\[?v?(\d[\w.+-]*)\]?(?:\s+[-–—:]\s+.*|\s+\(.+\)|\s+\d{4}-\d\d-\d\d|:)?$",
    re.I,
)


def _notes_section(text: str, version: str) -> str | None:
    lines = text.splitlines()
    start = level = None
    for index, line in enumerate(lines):
        heading = _VERSION_HEADING.fullmatch(line.strip()) if line == line.lstrip() else None
        markdown = re.match(r"^(#{1,6})\s", line)
        if start is not None and (heading or (markdown and level and len(markdown[1]) <= level)):
            return published_notes("\n".join(lines[start:index]))
        if heading and heading[2] == version:
            start = index + 1
            level = len(heading[1].strip()) if heading[1] else None
            if start < len(lines) and re.fullmatch(r"[=~-]{3,}", lines[start].strip()):
                start += 1
    return published_notes("\n".join(lines[start:])) if start is not None else None


def find_file_notes(
    version: str, configured_file: str | None, list_files: Callable[[], Iterable[str]],
    read_file: Callable[[str], str | None], file_url: Callable[[str], str],
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
            release = next((item for item in root.findall("./releases/release") if item.get("version") == version), None)
            result = appstream_notes(release) if release is not None else None
            if result and (result["type"] == "link" or published_notes(result["body"])):
                result["url"] = result["url"] or url
                return result
        else:
            body = _notes_section(text, version)
            if body:
                return {"type": "text", "body": body, "url": url}
    return None
