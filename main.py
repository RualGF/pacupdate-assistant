from dotenv import load_dotenv

load_dotenv()

from updater import get_updates, resolve_github_repos
from ui import render

def main() -> None:
    updates = get_updates()
    if not updates:
        print("✅ Sistema actualizado, no hay paquetes pendientes.")
        return
    resolve_github_repos(updates)
    render(updates)


if __name__ == "__main__":
    main()