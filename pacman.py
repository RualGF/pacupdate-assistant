import subprocess
import re
import os

from models import PackageUpdate


def _run_pacman(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    return subprocess.run(args, capture_output=True, text=True, check=False, env=env)


def run_checkupdates() -> list[str]:
    try:
        result = subprocess.run(
            ["checkupdates"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        raise RuntimeError(
            "checkupdates no encontrado. Instala 'pacman-contrib'."
        )
    return [l for l in result.stdout.splitlines() if l.strip()]


def _split_version(version: str) -> tuple[str, str]:
    # "2:1.2.3-4" -> pkgver="2:1.2.3", pkgrel="4"
    pkgver, _, pkgrel = version.rpartition("-")
    return pkgver, pkgrel


def parse_checkupdates(lines: list[str]) -> list[PackageUpdate]:
    updates = []
    for line in lines:
        try:
            name, rest = line.split(" ", 1)
            old, new = rest.split(" -> ")
            old_pkgver, old_pkgrel = _split_version(old.strip())
            new_pkgver, new_pkgrel = _split_version(new.strip())
        except ValueError:
            continue  # línea inesperada, la ignoramos en vez de romper
        updates.append(
            PackageUpdate(
                name=name,
                old_pkgver=old_pkgver, old_pkgrel=old_pkgrel,
                new_pkgver=new_pkgver, new_pkgrel=new_pkgrel,
            )
        )
    return updates



            