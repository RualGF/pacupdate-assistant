import requests
import re
from typing import Optional

GITHUB_REPO_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+?)(?:\.git|/archive|/releases|[\"'])")
URL_FIELD_RE = re.compile(r'^\s*url\s*=\s*["\']?(https?://github\.com/([\w.-]+/[\w.-]+?))/?["\']?\s*$', re.MULTILINE)


def _extract_repo(pkgbuild_text: str) -> Optional[str]:
    url_match = URL_FIELD_RE.search(pkgbuild_text)
    if url_match:
        return url_match.group(2)
    source_match = GITHUB_REPO_RE.search(pkgbuild_text)
    return source_match.group(1) if source_match else None


def _fetch(url: str, headers: dict) -> Optional[str]:
    resp = requests.get(url, headers=headers, timeout=5)
    return resp.text if resp.status_code == 200 else None


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
        text = _fetch(f"https://api.github.com/repos/{repo}/tags", headers)
        if text:
            import json
            tags = [t["name"] for t in json.loads(text)]
            # limpiamos el pkgrel/epoch de la versión instalada para comparar solo el pkgver
            version_core = known_version.split("-")[0].split(":")[-1]
            checks["version_found"] = any(version_core in tag for tag in tags)

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

def fetch_release_notes(repo: str, version: str, token: Optional[str]) -> Optional[dict]:
    """
    Busca el release de GitHub que corresponde a la nueva versión.
    Devuelve {'type': 'text', 'body': ..., 'url': ...} si hay notas,
    o {'type': 'link', 'url': ...} si el release existe pero sin cuerpo de texto,
    o None si no se encuentra ningún release que matchee la versión.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    text = _fetch(f"https://api.github.com/repos/{repo}/releases", headers)
    if not text:
        return None

    import json
    releases = json.loads(text)
    version_core = version.split("-")[0].split(":")[-1]  # quita pkgrel/epoch

    for release in releases:
        tag = release.get("tag_name", "")
        if version_core in tag:
            body = (release.get("body") or "").strip().replace("\r\n", "\n")
            url = release.get("html_url", "")
            if body:
                return {"type": "text", "body": body, "url": url}
            return {"type": "link", "url": url}
    if releases:
        return {"type": "link", "url": f"https://github.com/{repo}/releases"}

    return None  # no hay release para esa versión (quizás solo usan tags, sin Releases)