import requests
import re
from typing import Optional
from urllib.parse import quote, urlencode

from release_notes import find_file_notes, matching_tag, published_notes

GITLAB_REPO_RE = re.compile(r"gitlab\.com/([\w.-]+/[\w.-]+?)(?:\.git|/-/archive|/-/releases|[\"'])")


def extract_gitlab_repo(pkgbuild_text: str) -> Optional[str]:
    match = GITLAB_REPO_RE.search(pkgbuild_text)
    return match.group(1) if match else None


def _fetch(url: str, *, raw: bool = False):
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.text if raw else response.json()
    except (requests.RequestException, ValueError):
        pass
    return None


def fetch_release_notes(project_path: str, version: str, host: str = "gitlab.com", notes_file: str | None = None) -> Optional[dict]:
    version = version.split(":")[-1]
    project = project_path.rsplit("/", 1)[-1]
    api = f"https://{host}/api/v4/projects/{quote(project_path, safe='')}"
    web = f"https://{host}/{project_path}/-"

    releases = _fetch(f"{api}/releases?per_page=100")
    if not version or not isinstance(releases, list):
        return None
    release = next((item for item in releases if matching_tag(item.get("tag_name") or "", version, project)), None)
    if release:
        tag = release["tag_name"]
    else:
        tags = _fetch(f"{api}/repository/tags?{urlencode({'search': version, 'per_page': 100})}") or []
        tag = next((item["name"] for item in tags if matching_tag(item["name"], version, project)), None)
        if not tag:
            return None
        release = _fetch(f"{api}/releases/{quote(tag, safe='')}")

    ref = quote(tag, safe="")
    url = f"{web}/tags/{ref}"
    if release:
        url = f"{web}/releases/{ref}"
        body = published_notes(release.get("description"))
        if body:
            return {"type": "text", "body": body, "url": url}

    def list_files():
        for page in range(1, 4):
            query = urlencode({"ref": tag, "recursive": "true", "per_page": 100, "page": page})
            items = _fetch(f"{api}/repository/tree?{query}") or []
            yield from (item["path"] for item in items if item["type"] == "blob")
            if len(items) < 100:
                break

    def read_file(path):
        return _fetch(f"{api}/repository/files/{quote(path, safe='')}/raw?{urlencode({'ref': tag})}", raw=True)

    result = find_file_notes(version, notes_file, list_files, read_file, lambda path: f"{web}/blob/{ref}/{quote(path)}")
    return result or {"type": "reference", "url": url}
