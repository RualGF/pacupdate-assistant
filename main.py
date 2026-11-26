from dotenv import load_dotenv
load_dotenv()

from updater import (get_updates, get_aur_updates, classify_updates, resolve_github_repos, detect_group_releases,
                     detect_group_rebuilds)
from ui import render
from pacman import get_package_info, get_package_groups, get_package_bases
from config import load_packages_sources
from cache import ReleaseNotesCache, load_seen_packages, save_seen_packages
from flatpak import get_flatpak_updates
from models import UpdateCheckError

def main() -> int:
    sources = load_packages_sources()
    issues = []
    updates = []
    for source, check in (("pacman", get_updates), ("AUR", get_aur_updates)):
        try:
            updates.extend(check())
        except UpdateCheckError as error:
            issues.append(f"⚠ No se pudo completar la consulta de {source}. {error}")

    flatpaks, flatpak_failed = get_flatpak_updates(sources)
    updates.extend(flatpaks)
    if flatpak_failed:
        issues.append("⚠ No se pudo completar la consulta de Flatpak.")
    for issue in issues:
        print(issue)

    if not updates:
        if issues:
            print("No se pudo confirmar si hay actualizaciones pendientes.")
            return 1
        print("✅ Sistema actualizado, no hay paquetes pendientes.")
        return 0

    if issues:
        print("Mostrando las actualizaciones que se pudieron comprobar.")

    seen = load_seen_packages()
    classify_updates(updates, seen)
    save_seen_packages(seen | {u.name for u in updates})

    pkg_info = {}
    discovery_errors = {}
    group_releases, absorbed = [], set()
    group_rebuilds = []
    if any(not update.flatpak_ref for update in updates):
        pkg_info = get_package_info()
        bases = get_package_bases(updates)
        for name, base in bases.items():
            if name in pkg_info:
                pkg_info[name].base = base
        groups = get_package_groups()
        group_releases, absorbed = detect_group_releases(updates, groups, bases, sources)
        group_rebuilds = detect_group_rebuilds(updates, groups, bases)
        representatives = {release["representative"].name for release in group_releases if "representative" in release}
        candidates = [update for update in updates if update.category != "system"
                      and (update.name not in absorbed or update.name in representatives)]
        discovery_errors = resolve_github_repos(candidates, pkg_info, sources)

    render(updates, sources, group_releases, absorbed, pkg_info=pkg_info, discovery_errors=discovery_errors,
           notes_cache=ReleaseNotesCache(), group_rebuilds=group_rebuilds)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
