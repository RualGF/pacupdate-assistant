from dotenv import load_dotenv
load_dotenv()

from updater import get_updates, get_aur_updates, classify_updates, resolve_github_repos, detect_group_releases
from ui import render
from pacman import get_package_info, get_package_groups
from config import load_packages_sources
from cache import load_seen_packages, save_seen_packages

def main() -> None:
    updates = get_updates() + get_aur_updates()
    if not updates:
        print("✅ Sistema actualizado, no hay paquetes pendientes.")
        return

    seen = load_seen_packages()
    classify_updates(updates, seen)
    save_seen_packages(seen | {u.name for u in updates})

    pkg_info = get_package_info()
    resolve_github_repos(updates, pkg_info)
    sources = load_packages_sources()
    groups = get_package_groups()
    group_releases, absorbed = detect_group_releases(updates, groups)

    render(updates, sources, group_releases, absorbed)


if __name__ == "__main__":
    main()