import subprocess
import os

from models import PackageUpdate
from typing import Optional
from dataclasses import dataclass, field

@dataclass
class PackageInfo:
    description: str = ""
    installed_from: str = ""
    base: str = ""
    required_by: list[str] = field(default_factory=list)

def get_package_info() -> dict[str, PackageInfo]:
    """Una sola llamada a pacman -Qi, captura todo lo que necesitamos de golpe."""
    result = _run_pacman(["pacman", "-Qi"])
    info: dict[str, PackageInfo] = {}
    current = None
    name = base = None

    for line in result.stdout.splitlines():
        if line.startswith("Installed From"):
            current = PackageInfo(installed_from=line.split(":", 1)[1].strip())
        elif line.startswith("Name"):
            name = line.split(":", 1)[1].strip()
            base = name
        elif line.startswith("Description"):
            if current:
                current.description = line.split(":", 1)[1].strip()
        elif line.startswith("Base"):
            base = line.split(":", 1)[1].strip()
        elif line.startswith("Required By"):
            raw = line.split(":", 1)[1].strip()
            if current:
                current.required_by = [] if raw == "None" else raw.split()
        elif line == "" and name and current:
            current.base = base
            info[name] = current
            name = base = current = None

    return info

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

def get_foreign_packages() -> set[str]:
    result = _run_pacman(["pacman", "-Qmq"])
    return set(result.stdout.split())

def get_installed_version(pkgname: str) -> Optional[str]:
    result = _run_pacman(["pacman", "-Q", pkgname])
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split()
    return parts[1] if len(parts) == 2 else None
           