from pathlib import Path
import yaml

DATA_DIR = Path(__file__).parent / "data"


def load_packages_map() -> dict[str, str]:
    """Devuelve {nombre_paquete: categoria} a partir de packages.yaml"""
    raw = yaml.safe_load((DATA_DIR / "packages.yaml").read_text())
    mapping = {}
    for category, entries in raw.items():
        # soporta tanto lista simple como dict con metadata
        items = entries.keys() if isinstance(entries, dict) else entries
        for name in items:
            mapping[name] = category
    return mapping


def load_aliases() -> dict[str, str]:
    """Nombre real del paquete -> nombre bonito para mostrar"""
    path = DATA_DIR / "aliases.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}