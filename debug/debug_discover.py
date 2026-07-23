import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pacman import get_package_origins, get_foreign_packages, get_installed_version
from github import discover_github_repo, verify_repo
from config import load_github_token

origins = get_package_origins()
foreign = get_foreign_packages()
token = load_github_token()

for pkg in ["lutris", "maestral", "autofirma"]:
    info = origins.get(pkg, {})
    version = get_installed_version(pkg)
    repo = discover_github_repo(
        pkgname=pkg,
        pkgbase=info.get("base", pkg),
        is_foreign=pkg in foreign,
        installed_from=info.get("from", ""),
    )
    if repo:
        verification = verify_repo(repo, pkg, version, token)
        print(f"{pkg}: {repo} (versión instalada: {version}) -> {verification}")
    else:
        print(f"{pkg}: no se encontró ningún repo")