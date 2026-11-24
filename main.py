from dotenv import load_dotenv
load_dotenv()

from updater import get_updates, get_aur_updates, classify_updates, resolve_github_repos, detect_group_releases
from ui import render
from pacman import get_package_info, get_package_groups
from config import load_packages_sources
from cache import load_seen_packages, save_seen_packages
from flatpak import get_flatpak_updates

def main() -> None:
    sources = load_packages_sources()
    flatpaks, flatpak_failed = get_flatpak_updates(sources)
    updates = get_updates() + get_aur_updates() + flatpaks
    if not updates:
        if flatpak_failed:
            print("No se detectaron actualizaciones de pacman ni AUR. La comprobación de Flatpak quedó incompleta.")
        else:
            print("✅ Sistema actualizado, no hay paquetes pendientes.")
        return

    seen = load_seen_packages()
    classify_updates(updates, seen)
    save_seen_packages(seen | {u.name for u in updates})

    pkg_info = get_package_info()
    groups = get_package_groups()
    group_releases, absorbed = detect_group_releases(updates, groups)
    resolve_github_repos([update for update in updates if update.name not in absorbed], pkg_info, sources)

    render(updates, sources, group_releases, absorbed)


if __name__ == "__main__":
    main()
