# debug_bulk_discover_cachyos.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import random
from pacman import get_package_info, get_foreign_packages, get_installed_version
from github import discover_github_repo, verify_repo
from config import load_github_token

origins = get_package_info()
foreign = get_foreign_packages()
token = load_github_token()

cachyos_pkgs = sorted(
    name for name, info in origins.items()
    if info.installed_from.startswith("cachyos") and name not in foreign
)

muestra = random.sample(cachyos_pkgs, min(15, len(cachyos_pkgs)))


print(f"Probando una muestra de {len(muestra)} de {len(cachyos_pkgs)} paquetes de CachyOS...\n")

for pkg in muestra:
    info = origins.get(pkg, {})
    version = get_installed_version(pkg)
    repo = discover_github_repo(
        pkgname=pkg,
        pkgbase=info.base if info else pkg,
        is_foreign=True,
        installed_from=info.installed_from if info else "",
    )
    if repo:
        v = verify_repo(repo, pkg, version, token)
        print(f"{pkg:30s} -> {repo:40s} [{v['confidence']}]")
    else:
        print(f"{pkg:30s} -> (no encontrado)")