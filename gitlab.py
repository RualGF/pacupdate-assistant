import re
from typing import Optional
from urllib.parse import quote, urlencode

from release_notes import (NotesLookupError, combine_version_notes, earlier_release_notes, fetch_notes_response,
                           find_file_notes, matching_tag, notes_diagnostic, notes_objects, published_notes, range_start)

GITLAB_REPO_RE = re.compile(r"gitlab\.com/([\w.-]+/[\w.-]+?)(?:\.git|/-/archive|/-/releases|[\"'])")


def extract_gitlab_repo(pkgbuild_text: str) -> Optional[str]:
    match = GITLAB_REPO_RE.search(pkgbuild_text)
    return match.group(1) if match else None


def _fetch(url: str, *, raw: bool = False):
    response = fetch_notes_response(url, "GitLab")
    if response is None:
        return None
    if raw:
        return response.text
    try:
        data = response.json()
    except ValueError as error:
        raise NotesLookupError("GitLab devolvió una respuesta JSON inválida.") from error
    if data is None:
        raise NotesLookupError("GitLab devolvió una respuesta vacía.")
    return data


def fetch_release_notes(project_path: str, version: str, host: str = "gitlab.com", notes_file: str | None = None, *,
                        old_version: str | None = None) -> Optional[dict]:
    old = range_start(old_version, version)
    version = version.split(":")[-1]
    project = project_path.rsplit("/", 1)[-1]
    api = f"https://{host}/api/v4/projects/{quote(project_path, safe='')}"
    web = f"https://{host}/{project_path}/-"

    if not version:
        return None
    try:
        releases = _fetch(f"{api}/releases?per_page=100")
        if releases is None:
            return notes_diagnostic("repository_missing", "El repositorio de GitLab no está accesible.")
        releases = notes_objects(releases, "tag_name", "GitLab")
    except NotesLookupError as error:
        return error.as_result()
    earlier = earlier_release_notes(releases, project, old, version, "description",
                                    lambda item: f"{web}/releases/{quote(item['tag_name'], safe='')}")
    release = next((item for item in releases if matching_tag(item.get("tag_name") or "", version, project)), None)
    tag = release["tag_name"] if release else None
    try:
        if tag is None:
            tags = _fetch(f"{api}/repository/tags?{urlencode({'search': version, 'per_page': 100})}")
            tags = notes_objects(tags, "name", "GitLab") if tags is not None else []
            tag = next((item["name"] for item in tags if matching_tag(item["name"], version, project)), None)
            if tag:
                release = _fetch(f"{api}/releases/{quote(tag, safe='')}")
                if release is not None and not isinstance(release, dict):
                    raise NotesLookupError("GitLab devolvió una publicación inesperada.")
    except NotesLookupError as error:
        diagnostic = error.as_result()
        if tag is not None:
            diagnostic["url"] = f"{web}/tags/{quote(tag, safe='')}"
        return combine_version_notes(version, diagnostic, earlier)
    if not tag:
        missing = notes_diagnostic("version_missing", "GitLab no muestra una publicación ni una etiqueta para esta versión.")
        return combine_version_notes(version, missing, earlier)

    ref = quote(tag, safe="")
    url = f"{web}/tags/{ref}"
    if release:
        url = f"{web}/releases/{ref}"
        body = published_notes(release.get("description"))
        if body:
            return combine_version_notes(version, {"type": "text", "body": body, "url": url}, earlier)

    def list_files():
        for page in range(1, 4):
            query = urlencode({"ref": tag, "recursive": "true", "per_page": 100, "page": page})
            items = _fetch(f"{api}/repository/tree?{query}")
            items = notes_objects(items, "path", "GitLab") if items is not None else []
            yield from (item["path"] for item in items if item.get("type") == "blob")
            if len(items) < 100:
                break

    def read_file(path):
        return _fetch(f"{api}/repository/files/{quote(path, safe='')}/raw?{urlencode({'ref': tag})}", raw=True)

    try:
        result = find_file_notes(version, notes_file, list_files, read_file,
                                 lambda path: f"{web}/blob/{ref}/{quote(path)}", old_version=old)
    except NotesLookupError as error:
        result = {**error.as_result(), "url": url}
    return combine_version_notes(version, result or {"type": "reference", "url": url}, earlier)
