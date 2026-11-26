from pacman import run_checkupdates, parse_checkupdates, get_foreign_packages, get_foreign_package_versions, PackageInfo, _split_version
from aur import check_aur_updates
from config import load_release_notes_settings, load_packages_map, load_github_token
from cache import ReleaseNotesCache, load_seen_packages, save_seen_packages, load_github_repo_cache, save_github_repo_cache
from github import discover_github_repo, verify_repo, fetch_release_notes, is_trustworthy
from models import PackageUpdate, ChangeType, VersionBump
from release_notes import NotesLookupError, notes_diagnostic
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import Optional

import gitlab
import flatpak

MOZILLA_URLS = {
    "firefox": "https://www.firefox.com/en-US/firefox/{version}/releasenotes/",
    "thunderbird": "https://www.thunderbird.net/en-US/thunderbird/{version}/releasenotes/",
}
PLASMA_CHANGELOG = "https://kde.org/announcements/changelogs/plasma/{major}/{old}-{new}/"
MIN_GROUP_SIZE = 5  # umbral para considerar que es un release real, no casualidad
EXPLICIT_SOURCE_PREFIXES = ("github:", "gitlab:", "gitlab-self:", "link:", "template:", "flatpak:", "shared:")
REPOSITORY_SOURCE_PREFIXES = ("github:", "gitlab:", "gitlab-self:")

def get_updates() -> list[PackageUpdate]:

    return parse_checkupdates(run_checkupdates())

def resolve_github_repos(updates: list[PackageUpdate], pkg_info: dict[str, PackageInfo], sources: dict[str, str]) -> dict[str, str]:
    candidates = []
    for update in updates:
        source = sources.get(update.name, "")
        if (not update.flatpak_ref and update.change_type is ChangeType.VERSION
                and update.version_bump is not VersionBump.SNAPSHOT
                and source != "mozilla" and not source.startswith(EXPLICIT_SOURCE_PREFIXES)):
            candidates.append(update)
    if not candidates:
        return {}

    cache = load_github_repo_cache()
    foreign = get_foreign_packages()
    token = load_github_token()
    errors = {}
    changed = False

    for u in candidates:
        previous = cache.get(u.name, {})
        if previous.get("repo") or (previous.get("lookup_completed") and previous.get("version") == u.new_pkgver):
            continue
        info = pkg_info.get(u.name)
        try:
            repo = discover_github_repo(
                pkgname=u.name,
                pkgbase=info.base if info else u.name,
                is_foreign=u.name in foreign,
                installed_from=info.installed_from if info else "",
            )
            if repo:
                verification = verify_repo(repo, u.name, u.old_version, token)
                cache[u.name] = {"repo": repo, "confidence": verification["confidence"]}
            else:
                cache[u.name] = {"repo": None, "confidence": "low", "version": u.new_pkgver, "lookup_completed": True}
            changed = True
        except NotesLookupError as error:
            errors[u.name] = str(error)

    if changed:
        save_github_repo_cache(cache)
    return errors

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

def detect_group_releases(
    updates: list[PackageUpdate], groups: dict[str, str], bases: dict[str, str] | None = None,
    sources: dict[str, str] | None = None,
) -> tuple[list[dict], set[str]]:
    bases = bases or {}
    sources = sources or {}
    version_updates = [u for u in updates if not u.flatpak_ref and u.change_type is ChangeType.VERSION]
    by_base = defaultdict(list)
    inherited_groups = defaultdict(set)
    for u in version_updates:
        base = bases.get(u.name)
        if base:
            key = (base, u.old_pkgver, u.new_pkgver)
            by_base[key].append(u)
            if group := groups.get(u.name):
                inherited_groups[key].add(group)

    by_group = defaultdict(list)
    for u in version_updates:
        if u.known:
            continue
        group = groups.get(u.name)
        if not group:
            inherited = inherited_groups.get((bases.get(u.name), u.old_pkgver, u.new_pkgver), set())
            group = next(iter(inherited)) if len(inherited) == 1 else None
        if group:
            by_group[group, u.old_pkgver, u.new_pkgver].append(u)

    releases, absorbed = [], set()
    for (group, old, new), members in by_group.items():
        if len(members) >= MIN_GROUP_SIZE:
            releases.append({"group": group, "old": old, "new": new, "count": len(members),
                             "bump": members[0].version_bump})
            absorbed.update(member.name for member in members)

    for (base, old, new), members in by_base.items():
        members = [member for member in members if member.name not in absorbed
                   and sources.get(member.name) in {None, sources.get(base)}]
        if len(members) >= 2:
            representative = next((member for member in members if member.name == base), members[0])
            releases.append({"group": base, "old": old, "new": new, "count": len(members),
                             "bump": representative.version_bump, "representative": representative,
                             "members": [member.name for member in members]})
            absorbed.update(member.name for member in members)

    return releases, absorbed


def detect_group_rebuilds(
    updates: list[PackageUpdate], groups: dict[str, str], bases: dict[str, str],
) -> list[tuple[str, list[PackageUpdate]]]:
    by_group: dict[tuple[str, str, str, str], list[PackageUpdate]] = defaultdict(list)
    for update in updates:
        if update.flatpak_ref or update.known or update.change_type is not ChangeType.REBUILD:
            continue
        group = groups.get(update.name) or groups.get(bases.get(update.name, ""))
        if group:
            key = (group, update.new_pkgver, update.old_pkgrel, update.new_pkgrel)
            by_group[key].append(update)
    return [(key[0], members) for key, members in by_group.items() if len(members) >= MIN_GROUP_SIZE]


def get_aur_updates() -> list[PackageUpdate]:
    installed = get_foreign_package_versions()
    raw_updates = check_aur_updates(set(installed), installed)

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

def resolve_one_changelog(u: PackageUpdate, sources: dict, cache: dict, token: Optional[str], *,
                          discovery_errors: dict[str, str] | None = None,
                          notes_cache: ReleaseNotesCache | None = None) -> Optional[dict]:
    try:
        return _resolve_one_changelog(u, sources, cache, token, discovery_errors or {}, notes_cache)
    except NotesLookupError as error:
        return error.as_result()


def _resolve_one_changelog(u: PackageUpdate, sources: dict, cache: dict, token: Optional[str],
                           discovery_errors: dict[str, str], notes_cache: ReleaseNotesCache | None) -> Optional[dict]:
    raw_source = sources.get(u.name, "")
    if u.flatpak_ref:
        if u.change_type is not ChangeType.VERSION:
            return None
        app_id = u.flatpak_ref.split("/", 1)[0]
        settings = load_release_notes_settings(u.name) if raw_source == f"flatpak:{app_id}" else {}
        ref = f"{u.flatpak_kind}/{u.flatpak_ref}"
        key = ("flatpak", ref, u.flatpak_origin, u.flatpak_installation, settings, u.new_pkgver)
        notes = _cached_notes(notes_cache, key, partial(flatpak.fetch_release_notes, u, settings))
        return notes or notes_diagnostic(
            "version_missing", "Sin notas para esta versión en AppStream o en la fuente configurada.",
        )

    if raw_source.startswith("flatpak:"):
        return None
    if u.change_type is not ChangeType.VERSION and not raw_source.startswith("link:"):
        return None

    if parent := shared_notes_parent(raw_source):
        if shared_notes_parent(sources.get(parent, "")):
            return None
        return _resolve_one_changelog(replace(u, name=parent), sources, cache, token, discovery_errors, notes_cache)

    if raw_source.startswith("link:"):
        return {"type": "source", "url": raw_source.split(":", 1)[1]}
    elif raw_source == "mozilla" and u.name in MOZILLA_URLS:
        return {"type": "link", "url": MOZILLA_URLS[u.name].format(version=u.new_pkgver)}
    elif raw_source.startswith("template:"):
        ver = u.new_pkgver.split(":")[-1]
        parts = ver.split(".")
        url = raw_source.split(":", 1)[1].format(
            version=ver, version_dash="-".join(parts), version_series=".".join(parts[:2]),
            version_major=parts[0], version_compact="".join(parts),
        )
        return {"type": "link", "url": url}
    if not raw_source.startswith(REPOSITORY_SOURCE_PREFIXES):
        entry = cache.get(u.name)
        if u.name in discovery_errors:
            return notes_diagnostic("unavailable", discovery_errors[u.name])
        if not entry or not entry.get("repo"):
            return notes_diagnostic("unknown_source", "Fuente oficial sin identificar.")
        if not is_trustworthy(entry["confidence"]):
            return notes_diagnostic("unverified_source", f"Repositorio localizado sin confirmar como fuente oficial ({entry['repo']}).")
        raw_source = f"github:{entry['repo']}"

    notes_file = load_release_notes_settings(u.name).get("file") if u.name in sources or u.known else None
    if raw_source.startswith("github:"):
        repo = raw_source.split(":", 1)[1]
        fetch = partial(fetch_release_notes, repo, u.new_pkgver, token, notes_file, old_version=u.old_pkgver)
        identity = ("github", repo.casefold())
    else:
        kind, project = raw_source.split(":", 1)
        host = "gitlab.com"
        if kind == "gitlab-self":
            host, project = project.split(":", 1)
        fetch = partial(gitlab.fetch_release_notes, project, u.new_pkgver, host=host,
                        notes_file=notes_file, old_version=u.old_pkgver)
        identity = ("gitlab", host.casefold(), project)
    return _cached_notes(notes_cache, (*identity, notes_file, u.old_pkgver, u.new_pkgver), fetch)


def _cached_notes(notes_cache: ReleaseNotesCache | None, key: tuple,
                  fetch: Callable[[], dict | None]) -> dict | None:
    return notes_cache.get_or_fetch(key, fetch) if notes_cache is not None else fetch()


def shared_notes_parent(source: str) -> str:
    return source.removeprefix("shared:") if source.startswith("shared:") else ""


def classify_updates(updates: list[PackageUpdate], seen: set[str]) -> None:
    packages_map = load_packages_map()
    for u in updates:
        if u.flatpak_ref:
            default_category = "flatpak-runtimes" if u.flatpak_kind == "runtime" else "applications"
        else:
            default_category = "system"
        u.category = packages_map.get(u.name, default_category)
        u.known = u.name in packages_map
        u.is_new = u.name not in seen
