import json
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent / "cache"
SEEN_FILE = CACHE_DIR / "seen_packages.json"


def load_seen_packages() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    return set(json.loads(SEEN_FILE.read_text()))


def save_seen_packages(names: set[str]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(names), ensure_ascii=False, indent=2))

def load_github_repo_cache() -> dict[str, dict]:
    path = CACHE_DIR / "github_repos.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_github_repo_cache(cache: dict[str, dict]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / "github_repos.json").write_text(json.dumps(cache, indent=2, ensure_ascii=False))