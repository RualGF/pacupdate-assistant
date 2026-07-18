from updater import get_updates
from ui import render


def main() -> None:
    updates = get_updates()
    if not updates:
        print("✅ Sistema actualizado, no hay paquetes pendientes.")
        return
    render(updates)


if __name__ == "__main__":
    main()