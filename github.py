import json
import re
from typing import Optional
from urllib.parse import quote, urlencode, urlsplit

from release_notes import (NotesLookupError, combine_version_notes, earlier_release_notes, fetch_notes_response,
                           find_file_notes, matching_tag, notes_diagnostic, notes_objects, published_notes, range_start)

GITHUB_REPO_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+?)(?:\.git|/archive|/releases|[\"'])")
URL_FIELD_RE = re.compile(r'^\s*url\s*=\s*["\']?(https?://github\.com/([\w.-]+/[\w.-]+?))/?["\']?\s*$', re.MULTILINE)


def _extract_repo(pkgbuild_text: str) -> Optional[str]:
    url_match = URL_FIELD_RE.search(pkgbuild_text)
    if url_match:
        return url_match.group(2)
    source_match = GITHUB_REPO_RE.search(pkgbuild_text)
    return source_match.group(1) if source_match else None


def _fetch(url: str, headers: dict) -> Optional[str]:
    host = urlsplit(url).hostname
    services = {"aur.archlinux.org": "AUR", "gitlab.archlinux.org": "GitLab de Arch"}
    response = fetch_notes_response(url, services.get(host, "GitHub"), headers=headers)
    return response.text if response is not None else None


def discover_github_repo(pkgname: str, pkgbase: str, is_foreign: bool, installed_from: str) -> Optional[str]:
    candidates = []
    if is_foreign:
        candidates.append(f"https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h={pkgbase}")
    else:
        if installed_from.startswith("cachyos"):
            candidates.append(f"https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/master/{pkgbase}/PKGBUILD")
        candidates.append(f"https://gitlab.archlinux.org/archlinux/packaging/packages/{pkgbase}/-/raw/main/PKGBUILD")

    failure = None
    for url in candidates:
        try:
            text = _fetch(url, headers={})
            if text and text.lstrip().lower().startswith(("<!doctype html", "<html")):
                raise NotesLookupError(f"{urlsplit(url).hostname} devolvió HTML en lugar del PKGBUILD.")
        except NotesLookupError as error:
            failure = error
            continue
        if text and (repo := _extract_repo(text)):
            return repo
    if failure is not None:
        raise failure
    return None

def verify_repo(repo: str, pkgname: str, known_version: Optional[str], token: Optional[str]) -> dict:
    checks = {"name_similarity": False, "version_found": False}

    repo_project = repo.split("/")[-1].lower()
    checks["name_similarity"] = pkgname.lower() in repo_project or repo_project in pkgname.lower()

    if known_version:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        tags = _fetch_json(f"https://api.github.com/repos/{repo}/tags", headers)
        tags = notes_objects(tags, "name", "GitHub") if tags is not None else []
        version_core = known_version.rsplit("-", 1)[0].split(":")[-1]
        checks["version_found"] = any(matching_tag(tag["name"], version_core, repo_project) for tag in tags)

    # version_found es la señal fuerte: por sí sola ya basta para "high".
    # name_similarity solo desempata cuando no pudimos verificar versión.
    if checks["version_found"]:
        checks["confidence"] = "high"
    elif checks["name_similarity"]:
        checks["confidence"] = "medium"
    else:
        checks["confidence"] = "low"

    return checks

def is_trustworthy(confidence: str) -> bool:
    return confidence in ("high", "medium")

def _fetch_json(url: str, headers: dict):
    text = _fetch(url, headers)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError as error:
        raise NotesLookupError("GitHub devolvió una respuesta JSON inválida.") from error
    if data is None:
        raise NotesLookupError("GitHub devolvió una respuesta vacía.")
    return data


def fetch_cachyos_kernel_notes(base: str, old_version: str, new_version: str, token: Optional[str]) -> dict:
    metadata_url = f"https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/{base}/.SRCINFO"
    missing = notes_diagnostic("version_missing", "Sin notas de CachyOS verificadas para este cambio.")
    metadata = _fetch(metadata_url, {})
    if metadata is None:
        return missing

    fields = dict(re.findall(r"^\s*(pkgbase|pkgver|pkgrel) = (\S+)$", metadata, re.MULTILINE))
    if fields.get("pkgbase") != base or f"{fields.get('pkgver')}-{fields.get('pkgrel')}" != new_version:
        return missing

    repo = "CachyOS/linux"
    tag_pattern = r"cachyos-(\d+\.\d+\.\d+)-(\d+)"
    source = re.search(
        rf"^\s*source = https://github\.com/{repo}/releases/download/({tag_pattern})/\1\.tar\.gz$",
        metadata, re.MULTILINE,
    )
    if not source or source[2] != fields["pkgver"]:
        return missing

    tag, version, revision = source.groups()
    old_pkgver, _, old_pkgrel = old_version.rpartition("-")
    same_version = old_pkgver == version
    if same_version and (not old_pkgrel.isdecimal() or int(revision) <= int(old_pkgrel)):
        return missing

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    entries = []
    while True:
        release = _fetch_json(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers)
        if release is None:
            break
        if not isinstance(release, dict) or release.get("tag_name") != tag:
            raise NotesLookupError("GitHub devolvió una publicación inesperada para el kernel de CachyOS.")
        raw_body = release.get("body")
        if raw_body is not None and not isinstance(raw_body, str):
            raise NotesLookupError("GitHub devolvió notas inesperadas para el kernel de CachyOS.")
        body = published_notes(raw_body)
        if release.get("draft") or release.get("prerelease") or not body:
            break
        entries.append({"type": "text", "body": body, "version": tag.removeprefix("cachyos-"),
                        "url": f"https://github.com/{repo}/releases/tag/{tag}"})
        previous = re.search(rf"^Previous release: `{tag_pattern}`\s*$", body, re.MULTILINE)
        if not same_version or not previous or previous[1] != version:
            break
        previous_revision = int(previous[2])
        if not int(old_pkgrel) < previous_revision < int(revision):
            break
        revision = previous[2]
        tag = f"cachyos-{version}-{revision}"

    if len(entries) > 1:
        return {"type": "range", "entries": entries, "fallback": None, "target_found": True}
    return entries[0] if entries else missing


def fetch_release_notes(repo: str, version: str, token: Optional[str], notes_file: str | None = None, *,
                        old_version: str | None = None) -> Optional[dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    old = range_start(old_version, version)
    version = version.split(":")[-1]
    if not version:
        return None
    project = repo.rsplit("/", 1)[-1]
    api = f"https://api.github.com/repos/{repo}"
    web = f"https://github.com/{repo}"

    try:
        releases = _fetch_json(f"{api}/releases?per_page=100", headers)
        if releases is None:
            return notes_diagnostic("repository_missing", "El repositorio de GitHub no está accesible.")
        releases = notes_objects(releases, "tag_name", "GitHub")
    except NotesLookupError as error:
        return error.as_result()
    earlier = earlier_release_notes(releases, project, old, version, "body", lambda item: item.get("html_url") or "")
    release = next((item for item in releases if matching_tag(item.get("tag_name") or "", version, project)), None)
    tag = release["tag_name"] if release else None
    try:
        if tag is None:
            tag = _find_tag(api, project, version, headers)
            if tag:
                release = _fetch_json(f"{api}/releases/tags/{quote(tag, safe='')}", headers)
                if release is not None and not isinstance(release, dict):
                    raise NotesLookupError("GitHub devolvió una publicación inesperada.")
    except NotesLookupError as error:
        diagnostic = error.as_result()
        if tag is not None:
            diagnostic["url"] = f"{web}/tree/{quote(tag, safe='')}"
        return combine_version_notes(version, diagnostic, earlier)
    if not tag:
        missing = notes_diagnostic("version_missing", "GitHub no muestra una publicación ni una etiqueta para esta versión.")
        return combine_version_notes(version, missing, earlier)

    ref = quote(tag, safe="")
    url = f"{web}/tree/{ref}"
    if release:
        url = release.get("html_url") or url
        body = published_notes(release.get("body"))
        if body:
            return combine_version_notes(version, {"type": "text", "body": body, "url": url}, earlier)

    def list_files():
        tree = _fetch_json(f"{api}/git/trees/{ref}?recursive=1", headers)
        if tree is None:
            return []
        if not isinstance(tree, dict):
            raise NotesLookupError("GitHub devolvió un árbol de archivos inesperado.")
        files = notes_objects(tree.get("tree"), "path", "GitHub")
        return (item["path"] for item in files if item.get("type") == "blob" and item.get("size", 0) <= 1_000_000)

    def read_file(path):
        query = urlencode({"ref": tag})
        return _fetch(f"{api}/contents/{quote(path)}?{query}", {**headers, "Accept": "application/vnd.github.raw+json"})

    try:
        result = find_file_notes(version, notes_file, list_files, read_file,
                                 lambda path: f"{web}/blob/{ref}/{quote(path)}", old_version=old)
    except NotesLookupError as error:
        result = {**error.as_result(), "url": url}
    return combine_version_notes(version, result or {"type": "reference", "url": url}, earlier)


def _find_tag(api: str, project: str, version: str, headers: dict) -> str | None:
    tags = _fetch_json(f"{api}/tags?per_page=100", headers)
    if tags is not None:
        for item in notes_objects(tags, "name", "GitHub"):
            if matching_tag(item["name"], version, project):
                return item["name"]

    for candidate in (f"v{version}", version):
        ref = _fetch_json(f"{api}/git/ref/tags/{quote(candidate, safe='')}", headers)
        if ref is not None:
            if not isinstance(ref, dict) or ref.get("ref") != f"refs/tags/{candidate}":
                raise NotesLookupError("GitHub devolvió una referencia inesperada.")
            return candidate
    return None
