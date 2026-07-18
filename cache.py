import json
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
SEEN_FILE = CACHE_DIR / "seen_packages.json"


def load_seen_packages() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    return set(json.loads(SEEN_FILE.read_text()))


def save_seen_packages(names: set[str]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(names), ensure_ascii=False, indent=2))