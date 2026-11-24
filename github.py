import json
import requests
import re
import sys
from typing import Optional
from urllib.parse import quote, urlencode

from release_notes import find_file_notes, matching_tag, published_notes

GITHUB_REPO_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+?)(?:\.git|/archive|/releases|[\"'])")
URL_FIELD_RE = re.compile(r'^\s*url\s*=\s*["\']?(https?://github\.com/([\w.-]+/[\w.-]+?))/?["\']?\s*$', re.MULTILINE)


def _extract_repo(pkgbuild_text: str) -> Optional[str]:
    url_match = URL_FIELD_RE.search(pkgbuild_text)
    if url_match:
        return url_match.group(2)
    source_match = GITHUB_REPO_RE.search(pkgbuild_text)
    return source_match.group(1) if source_match else None


def _fetch(url: str, headers: dict) -> Optional[str]:
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code in (401, 403):
            print(f"⚠ GitHub respondió {resp.status_code}: revisa GITHUB_TOKEN o el límite de peticiones", file=sys.stderr)
        return resp.text if resp.status_code == 200 else None
    except requests.exceptions.RequestException:
        return None  # timeout, error de red, DNS, lo que sea: lo tratamos como "no encontrado"


def discover_github_repo(pkgname: str, pkgbase: str, is_foreign: bool, installed_from: str) -> Optional[str]:
    candidates = []
    if is_foreign:
        candidates.append(f"https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h={pkgbase}")
    else:
        if installed_from.startswith("cachyos"):
            candidates.append(f"https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/master/{pkgbase}/PKGBUILD")
        candidates.append(f"https://gitlab.archlinux.org/archlinux/packaging/packages/{pkgbase}/-/raw/main/PKGBUILD")

    for url in candidates:
        text = _fetch(url, headers={})
        if text:
            repo = _extract_repo(text)
            if repo:
                return repo
    return None

def verify_repo(repo: str, pkgname: str, known_version: Optional[str], token: Optional[str]) -> dict:
    checks = {"name_similarity": False, "version_found": False}

    repo_project = repo.split("/")[-1].lower()
    checks["name_similarity"] = pkgname.lower() in repo_project or repo_project in pkgname.lower()

    if known_version:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        tags = _fetch_json(f"https://api.github.com/repos/{repo}/tags", headers) or []
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
    try:
        return json.loads(_fetch(url, headers) or "null")
    except ValueError:
        return None


def fetch_release_notes(repo: str, version: str, token: Optional[str], notes_file: str | None = None) -> Optional[dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    version = version.split(":")[-1]
    if not version:
        return None
    project = repo.rsplit("/", 1)[-1]
    api = f"https://api.github.com/repos/{repo}"
    web = f"https://github.com/{repo}"

    releases = _fetch_json(f"{api}/releases?per_page=100", headers)
    if not isinstance(releases, list):
        return None
    release = next((item for item in releases if matching_tag(item.get("tag_name") or "", version, project)), None)
    if release is None:
        tags = _fetch_json(f"{api}/tags?per_page=100", headers) or []
        tag = next((item["name"] for item in tags if matching_tag(item["name"], version, project)), None)
        if tag:
            release = _fetch_json(f"{api}/releases/tags/{quote(tag, safe='')}", headers)
        else:
            for candidate in (f"v{version}", version):
                if _fetch_json(f"{api}/git/ref/tags/{quote(candidate, safe='')}", headers):
                    tag = candidate
                    release = _fetch_json(f"{api}/releases/tags/{quote(tag, safe='')}", headers)
                    break
    else:
        tag = release["tag_name"]
    if not tag:
        return None

    ref = quote(tag, safe="")
    url = f"{web}/tree/{ref}"
    if release:
        url = release.get("html_url") or url
        body = published_notes(release.get("body"))
        if body:
            return {"type": "text", "body": body, "url": url}

    def list_files():
        tree = _fetch_json(f"{api}/git/trees/{ref}?recursive=1", headers) or {}
        return (item["path"] for item in tree.get("tree", []) if item["type"] == "blob" and item.get("size", 0) <= 1_000_000)

    def read_file(path):
        query = urlencode({"ref": tag})
        return _fetch(f"{api}/contents/{quote(path)}?{query}", {**headers, "Accept": "application/vnd.github.raw+json"})

    result = find_file_notes(version, notes_file, list_files, read_file, lambda path: f"{web}/blob/{ref}/{quote(path)}")
    return result or {"type": "reference", "url": url}
