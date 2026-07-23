# debug_bulk_discover_cachyos.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pacman import get_package_origins, get_foreign_packages, get_installed_version
from github import discover_github_repo, verify_repo
from config import load_github_token

origins = get_package_origins()
foreign = get_foreign_packages()
token = load_github_token()

cachyos_pkgs = sorted(
    name for name, info in origins.items()
    if info.get("from", "").startswith("cachyos") and name not in foreign
)

print(f"Probando {len(cachyos_pkgs)} paquetes de CachyOS...\n")

for pkg in cachyos_pkgs:
    info = origins.get(pkg, {})
    version = get_installed_version(pkg)
    repo = discover_github_repo(
        pkgname=pkg,
        pkgbase=info.get("base", pkg),
        is_foreign=False,
        installed_from=info.get("from", ""),
    )
    if repo:
        v = verify_repo(repo, pkg, version, token)
        print(f"{pkg:30s} -> {repo:40s} [{v['confidence']}]")
    else:
        print(f"{pkg:30s} -> (no encontrado)")