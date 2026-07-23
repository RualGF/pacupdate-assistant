import requests
import re
from typing import Optional
from urllib.parse import quote

GITLAB_REPO_RE = re.compile(r"gitlab\.com/([\w.-]+/[\w.-]+?)(?:\.git|/-/archive|/-/releases|[\"'])")


def extract_gitlab_repo(pkgbuild_text: str) -> Optional[str]:
    match = GITLAB_REPO_RE.search(pkgbuild_text)
    return match.group(1) if match else None


def fetch_release_notes(project_path: str, version: str) -> Optional[dict]:
    encoded = quote(project_path, safe="")
    resp = requests.get(f"https://gitlab.com/api/v4/projects/{encoded}/releases", timeout=5)
    if resp.status_code != 200:
        return None

    version_core = version.split("-")[0].split(":")[-1]
    for release in resp.json():
        tag = release.get("tag_name", "")
        if version_core in tag:
            body = (release.get("description") or "").strip().replace("\r\n", "\n")
            url = f"https://gitlab.com/{project_path}/-/releases/{tag}"
            if body:
                return {"type": "text", "body": body, "url": url}
            return {"type": "link", "url": url}
    return None