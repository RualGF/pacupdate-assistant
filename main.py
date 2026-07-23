from dotenv import load_dotenv
load_dotenv()

from updater import get_updates, resolve_github_repos, get_changelogs
from ui import render
from pacman import get_package_info
from config import load_packages_sources

def main() -> None:
    updates = get_updates()
    if not updates:
        print("✅ Sistema actualizado, no hay paquetes pendientes.")
        return
    pkg_info = get_package_info()
    resolve_github_repos(updates, pkg_info)
    sources = load_packages_sources()
    changelogs = get_changelogs(updates, sources)
    render(updates, changelogs)


if __name__ == "__main__":
    main()