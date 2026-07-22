from pathlib import Path
import yaml
import os

DATA_DIR = Path(__file__).parent / "data"

def load_github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN")

def load_packages_map() -> dict[str, str]:
    """Devuelve {nombre_paquete: categoria} a partir de packages.yaml"""
    raw = yaml.safe_load((DATA_DIR / "packages.yaml").read_text())
    mapping = {}
    for category, entries in raw.items():
        for name in (entries or {}):
            mapping[name] = category
    return mapping


def load_aliases() -> dict[str, str]:
    """Nombre real del paquete -> nombre bonito para mostrar"""
    path = DATA_DIR / "aliases.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}