import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from hashlib import sha256
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
SEEN_FILE = CACHE_DIR / "seen_packages.json"
PENDING_UPDATES_FILE = CACHE_DIR / "pending_updates.sqlite3"
NOTES_CACHE_FILE = CACHE_DIR / "release_notes.sqlite3"
NOTES_CACHE_TTL = 24 * 60 * 60


def load_seen_packages() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    return set(json.loads(SEEN_FILE.read_text()))


def save_seen_packages(names: set[str]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(names), ensure_ascii=False, indent=2))


def remember_pending_updates(current: dict[str, str]) -> tuple[dict[str, str] | None, bool]:
    try:
        PENDING_UPDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(PENDING_UPDATES_FILE, timeout=0.2)) as database, database:
            database.execute("BEGIN IMMEDIATE")
            database.execute("""
                CREATE TABLE IF NOT EXISTS pending_updates (
                    id INTEGER PRIMARY KEY CHECK (id = 1), versions TEXT NOT NULL
                )
            """)
            row = database.execute("SELECT versions FROM pending_updates WHERE id = 1").fetchone()
            database.execute("""
                INSERT INTO pending_updates VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET versions = excluded.versions
            """, (json.dumps(current, ensure_ascii=False),))
    except (OSError, sqlite3.Error):
        return None, False

    try:
        previous = json.loads(row[0]) if row else None
    except ValueError:
        return None, True
    if isinstance(previous, dict) and all(isinstance(version, str) for version in previous.values()):
        return previous, True
    return None, True


def load_github_repo_cache() -> dict[str, dict]:
    path = CACHE_DIR / "github_repos.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_github_repo_cache(cache: dict[str, dict]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / "github_repos.json").write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def _has_verified_notes(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    kind = result.get("type")
    if kind == "text":
        return isinstance(result.get("body"), str) and bool(result["body"].strip()) and isinstance(result.get("url"), str)
    if kind == "link":
        return isinstance(result.get("url"), str) and bool(result["url"])
    if kind == "range":
        entries = result.get("entries")
        return (result.get("target_found") is True and result.get("fallback") is None
                and isinstance(entries, list) and bool(entries) and all(
                    isinstance(entry, dict) and entry.get("type") in {"text", "link"}
                    and isinstance(entry.get("version"), str) and _has_verified_notes(entry)
                    for entry in entries
                ))
    return False


class ReleaseNotesCache:
    def __init__(self, path: Path = NOTES_CACHE_FILE):
        self.path = path

    def get_or_fetch(self, source: tuple, fetch: Callable[[], dict | None]) -> dict | None:
        try:
            encoded = json.dumps(source, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return fetch()
        key = sha256(encoded.encode("utf-8")).hexdigest()
        cached = self._read(key)
        if cached is not None:
            return cached

        result = fetch()
        if _has_verified_notes(result):
            self._write(key, result)
        return result

    def _read(self, key: str) -> dict | None:
        try:
            if not self.path.is_file():
                return None
            with closing(sqlite3.connect(self.path, timeout=0.2)) as database:
                row = database.execute(
                    "SELECT payload FROM release_notes WHERE cache_key = ? AND saved_at > ?",
                    (key, time.time() - NOTES_CACHE_TTL),
                ).fetchone()
            result = json.loads(row[0]) if row else None
        except (OSError, sqlite3.Error, ValueError):
            return None
        return result if _has_verified_notes(result) else None

    def _write(self, key: str, result: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=0.2)) as database, database:
                database.execute("""
                    CREATE TABLE IF NOT EXISTS release_notes (
                        cache_key TEXT PRIMARY KEY, saved_at REAL NOT NULL, payload TEXT NOT NULL
                    )
                """)
                now = time.time()
                database.execute("DELETE FROM release_notes WHERE saved_at <= ?", (now - NOTES_CACHE_TTL,))
                database.execute("""
                    INSERT INTO release_notes VALUES (?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET saved_at = excluded.saved_at, payload = excluded.payload
                """, (key, now, json.dumps(result, ensure_ascii=False)))
        except (OSError, sqlite3.Error):
            pass  # El informe puede continuar si la caché no está disponible.
