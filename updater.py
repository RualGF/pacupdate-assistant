from pacman import run_checkupdates, parse_checkupdates, get_foreign_packages, PackageInfo
from config import load_packages_map, load_github_token
from cache import load_seen_packages, save_seen_packages, load_github_repo_cache, save_github_repo_cache
from github import discover_github_repo, verify_repo, fetch_release_notes, is_trustworthy
from models import PackageUpdate, ChangeType, VersionBump
from collections import defaultdict

import gitlab

MOZILLA_URLS = {
    "firefox": "https://www.firefox.com/en-US/firefox/{version}/releasenotes/",
    "thunderbird": "https://www.thunderbird.net/en-US/thunderbird/{version}/releasenotes/",
}

MIN_GROUP_SIZE = 5  # umbral para considerar que es un release real, no casualidad

def get_updates() -> list[PackageUpdate]:
    updates = parse_checkupdates(run_checkupdates())
    packages_map = load_packages_map()
    seen = load_seen_packages()

    for u in updates:
        u.category = packages_map.get(u.name, "system")
        u.known = u.name in packages_map
        u.is_new = u.name not in seen

    save_seen_packages(seen | {u.name for u in updates})
    return updates

def resolve_github_repos(updates: list[PackageUpdate], pkg_info: dict[str, PackageInfo]) -> None:
    """Solo intenta descubrir repo para paquetes conocidos o recién detectados, nunca para todo el sistema."""
    candidates = [u for u in updates if u.known or u.needs_classification]
    if not candidates:
        return

    cache = load_github_repo_cache()
    foreign = get_foreign_packages()
    token = load_github_token()

    for u in candidates:
        if u.name in cache:
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
            cache[u.name] = {"repo": None, "confidence": "low"}

    save_github_repo_cache(cache)

def get_changelogs(updates: list[PackageUpdate], sources: dict[str, str]) -> dict[str, dict]:
    cache = load_github_repo_cache()
    token = load_github_token()
    changelogs = {}

    for u in updates:
        if not u.known or u.change_type is not ChangeType.VERSION:
            continue

        raw_source = sources.get(u.name, "")
        result = None

        if raw_source.startswith("github:"):
            repo = raw_source.split(":", 1)[1]
            result = fetch_release_notes(repo, u.new_pkgver, token)
        elif raw_source.startswith("gitlab:"):
            project = raw_source.split(":", 1)[1]
            result = gitlab.fetch_release_notes(project, u.new_pkgver)
        elif raw_source.startswith("link:"):
            result = {"type": "link", "url": raw_source.split(":", 1)[1]}
        elif raw_source == "mozilla" and u.name in MOZILLA_URLS:
            url = MOZILLA_URLS[u.name].format(version=u.new_pkgver)
            result = {"type": "link", "url": url}
        else:
            # sin estrategia curada: probamos el repo autodescubierto, si es fiable
            entry = cache.get(u.name)
            if entry and entry["repo"] and is_trustworthy(entry["confidence"]):
                result = fetch_release_notes(entry["repo"], u.new_pkgver, token)

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
        if u.known or u.change_type is not ChangeType.VERSION:
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