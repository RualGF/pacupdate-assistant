from pacman import run_checkupdates, parse_checkupdates
from config import load_packages_map
from cache import load_seen_packages, save_seen_packages
from models import PackageUpdate


def get_updates() -> list[PackageUpdate]:
    updates = parse_checkupdates(run_checkupdates())
    packages_map = load_packages_map()
    seen = load_seen_packages()

    for u in updates:
        meta = packages_map.get(u.name)
        u.category = meta["category"] if meta else "system"
        u.known = meta is not None
        u.show_rebuilds = meta["show_rebuilds"] if meta else False
        u.is_new = u.name not in seen

    save_seen_packages(seen | {u.name for u in updates})
    return updates