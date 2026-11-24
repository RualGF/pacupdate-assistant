from pacman import run_checkupdates, parse_checkupdates, get_foreign_packages, get_installed_version, PackageInfo, _split_version
from aur import check_aur_updates
from config import load_release_notes_settings, load_packages_map, load_github_token
from cache import load_seen_packages, save_seen_packages, load_github_repo_cache, save_github_repo_cache
from github import discover_github_repo, verify_repo, fetch_release_notes, is_trustworthy
from models import PackageUpdate, ChangeType, VersionBump
from collections import defaultdict
from typing import Optional

import gitlab
import flatpak

MOZILLA_URLS = {
    "firefox": "https://www.firefox.com/en-US/firefox/{version}/releasenotes/",
    "thunderbird": "https://www.thunderbird.net/en-US/thunderbird/{version}/releasenotes/",
}
PLASMA_CHANGELOG = "https://kde.org/announcements/changelogs/plasma/{major}/{old}-{new}/"
MIN_GROUP_SIZE = 5  # umbral para considerar que es un release real, no casualidad
EXPLICIT_SOURCE_PREFIXES = ("github:", "gitlab:", "gitlab-self:", "link:", "template:", "flatpak:")

def get_updates() -> list[PackageUpdate]:

    return parse_checkupdates(run_checkupdates())

def resolve_github_repos(updates: list[PackageUpdate], pkg_info: dict[str, PackageInfo], sources: dict[str, str]) -> None:
    candidates = []
    for update in updates:
        source = sources.get(update.name, "")
        if (not update.flatpak_ref and update.change_type is ChangeType.VERSION
                and source != "mozilla" and not source.startswith(EXPLICIT_SOURCE_PREFIXES)):
            candidates.append(update)
    if not candidates:
        return

    cache = load_github_repo_cache()
    foreign = get_foreign_packages()
    token = load_github_token()

    for u in candidates:
        previous = cache.get(u.name, {})
        if previous.get("repo") or previous.get("version") == u.new_pkgver:
            continue
        info = pkg_info.get(u.name)
        repo = discover_github_repo(
            pkgname=u.name,
            pkgbase=info.base if info else u.name,
            is_foreign=u.name in foreign,
            installed_from=info.installed_from if info else "",
        )
        if repo:
            v = verify_repo(repo, u.name, u.old_version, token)
            cache[u.name] = {"repo": repo, "confidence": v["confidence"]}
        else:
            cache[u.name] = {"repo": None, "confidence": "low", "version": u.new_pkgver}

    save_github_repo_cache(cache)

def get_changelogs(updates: list[PackageUpdate], sources: dict[str, str]) -> dict[str, dict]:
    cache = load_github_repo_cache()
    token = load_github_token()
    changelogs = {}

    for u in updates:
        if u.change_type is not ChangeType.VERSION:
            continue
        result = resolve_one_changelog(u, sources, cache, token)
        if result:
            changelogs[u.name] = result

    return changelogs

def detect_group_releases(updates: list[PackageUpdate], groups: dict[str, str]) -> tuple[list[dict], set[str]]:
    """
    Agrupa paquetes NO clasificados que comparten grupo pacman y suben de versión juntos.
    Solo cuenta si hay al menos un salto MAJOR entre ellos.
    """
    by_group: dict[str, list[PackageUpdate]] = defaultdict(list)
    for u in updates:
        if u.flatpak_ref or u.known or u.change_type is not ChangeType.VERSION:
            continue
        group = groups.get(u.name)
        if group:
            by_group[group].append(u)

    releases, absorbed = [], set()
    for group, members in by_group.items():
        if len(members) < MIN_GROUP_SIZE:
            continue
        versions = [(m.old_pkgver, m.new_pkgver) for m in members]
        old_v, new_v = max(set(versions), key=versions.count)
        bump = max((m.version_bump for m in members), key=lambda b: list(VersionBump).index(b))

        releases.append({"group": group, "old": old_v, "new": new_v, "count": len(members), "bump": bump})
        absorbed.update(m.name for m in members)

    return releases, absorbed

def get_aur_updates() -> list[PackageUpdate]:
    foreign = get_foreign_packages()
    installed = {pkg: get_installed_version(pkg) for pkg in foreign}
    raw_updates = check_aur_updates(foreign, installed)

    result = []
    for u in raw_updates:
        old_pkgver, old_pkgrel = _split_version(u["old"])
        new_pkgver, new_pkgrel = _split_version(u["new"])
        result.append(PackageUpdate(
            name=u["name"],
            old_pkgver=old_pkgver, old_pkgrel=old_pkgrel,
            new_pkgver=new_pkgver, new_pkgrel=new_pkgrel,
        ))
    return result

def resolve_one_changelog(u: PackageUpdate, sources: dict, cache: dict, token: Optional[str]) -> Optional[dict]:
    raw_source = sources.get(u.name, "")
    if u.flatpak_ref:
        if u.change_type is not ChangeType.VERSION:
            return None
        app_id = u.flatpak_ref.split("/", 1)[0]
        settings = load_release_notes_settings(u.name) if raw_source == f"flatpak:{app_id}" else {}
        return flatpak.fetch_release_notes(u, settings)

    if raw_source.startswith("flatpak:"):
        return None
    if u.change_type is not ChangeType.VERSION and not raw_source.startswith("link:"):
        return None
    
    if raw_source.startswith("github:"):
        notes_file = load_release_notes_settings(u.name).get("file")
        return fetch_release_notes(raw_source.split(":", 1)[1], u.new_pkgver, token, notes_file)
    elif raw_source.startswith("gitlab-self:"):
        _, host, project = raw_source.split(":", 2)
        notes_file = load_release_notes_settings(u.name).get("file")
        return gitlab.fetch_release_notes(project, u.new_pkgver, host=host, notes_file=notes_file)
    elif raw_source.startswith("gitlab:"):
        notes_file = load_release_notes_settings(u.name).get("file")
        return gitlab.fetch_release_notes(raw_source.split(":", 1)[1], u.new_pkgver, notes_file=notes_file)
    elif raw_source.startswith("link:"):
        return {"type": "link", "url": raw_source.split(":", 1)[1]}
    elif raw_source == "mozilla" and u.name in MOZILLA_URLS:
        return {"type": "link", "url": MOZILLA_URLS[u.name].format(version=u.new_pkgver)}
    elif raw_source.startswith("template:"):
        ver = u.new_pkgver.split(":")[-1]
        url = raw_source.split(":", 1)[1].format(version=ver, version_dash=ver.replace(".", "-"))
        return {"type": "link", "url": url}
    else:
        entry = cache.get(u.name)
        if entry and entry["repo"] and is_trustworthy(entry["confidence"]):
            notes_file = load_release_notes_settings(u.name).get("file") if u.known else None
            return fetch_release_notes(entry["repo"], u.new_pkgver, token, notes_file)
    return None

def classify_updates(updates: list[PackageUpdate], seen: set[str]) -> None:
    packages_map = load_packages_map()
    for u in updates:
        u.category = packages_map.get(u.name, "applications" if u.flatpak_ref else "system")
        u.known = u.name in packages_map
        u.is_new = u.name not in seen
