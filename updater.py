from pacman import run_checkupdates, parse_checkupdates, get_package_origins, get_foreign_packages
from config import load_packages_map, load_github_token
from cache import load_seen_packages, save_seen_packages, load_github_repo_cache, save_github_repo_cache
from github import discover_github_repo, verify_repo
from models import PackageUpdate


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

def resolve_github_repos(updates: list[PackageUpdate]) -> None:
    """Solo intenta descubrir repo para paquetes conocidos o recién detectados, nunca para todo el sistema."""
    candidates = [u for u in updates if u.known or u.needs_classification]
    if not candidates:
        return

    cache = load_github_repo_cache()
    origins = get_package_origins()
    foreign = get_foreign_packages()
    token = load_github_token()

    for u in candidates:
        if u.name in cache:
            continue
        info = origins.get(u.name, {})
        repo = discover_github_repo(
            pkgname=u.name,
            pkgbase=info.get("base", u.name),
            is_foreign=u.name in foreign,
            installed_from=info.get("from", ""),
        )
        if repo:
            v = verify_repo(repo, u.name, u.old_version, token)
            cache[u.name] = {"repo": repo, "confidence": v["confidence"]}
        else:
            cache[u.name] = {"repo": None, "confidence": "low"}

    save_github_repo_cache(cache)