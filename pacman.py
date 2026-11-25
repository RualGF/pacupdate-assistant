import subprocess
import os

from models import PackageUpdate, UpdateCheckError
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path

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

def _run_pacman(args: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    return subprocess.run(args, capture_output=True, text=True, check=False, env=env, timeout=timeout)


def run_checkupdates() -> list[str]:
    try:
        result = _run_pacman(["checkupdates", "--nocolor"], timeout=60)
    except FileNotFoundError as error:
        raise UpdateCheckError("No se encontró checkupdates. Instala pacman-contrib.") from error
    except subprocess.TimeoutExpired as error:
        raise UpdateCheckError("checkupdates tardó más de 60 segundos.") from error
    except OSError as error:
        raise UpdateCheckError(f"No se pudo ejecutar checkupdates. {error}") from error

    if result.returncode == 2:
        return []
    if result.returncode != 0:
        detail = result.stderr.strip() or f"checkupdates terminó con código {result.returncode}."
        raise UpdateCheckError(detail)
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


def get_foreign_package_versions() -> dict[str, str]:
    try:
        result = _run_pacman(["pacman", "-Qm"], timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UpdateCheckError(f"No se pudieron consultar los paquetes foráneos. {error}") from error

    if result.returncode == 1 and not (result.stdout.strip() or result.stderr.strip()):
        return {}
    if result.returncode != 0 or result.stderr.strip():
        detail = result.stderr.strip() or f"pacman -Qm terminó con código {result.returncode}."
        raise UpdateCheckError(detail)

    installed = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            raise UpdateCheckError("pacman -Qm devolvió un listado inesperado.")
        name, version = fields
        installed[name] = version
    return installed


def compare_versions(first: str, second: str) -> int:
    try:
        result = _run_pacman(["vercmp", first, second], timeout=5)
        if result.returncode != 0:
            raise UpdateCheckError("vercmp no pudo comparar las versiones de AUR.")
        return int(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise UpdateCheckError(f"No se pudo comparar la versión de AUR con vercmp. {error}") from error

def get_installed_version(pkgname: str) -> Optional[str]:
    result = _run_pacman(["pacman", "-Q", pkgname])
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split()
    return parts[1] if len(parts) == 2 else None

def get_package_groups() -> dict[str, str]:
    """Una sola llamada barata: {nombre: primer_grupo}"""
    result = _run_pacman(["pacman", "-Qg"])
    groups: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            group, name = parts
            groups.setdefault(name, group)
    return groups


def get_package_bases(updates: list[PackageUpdate]) -> dict[str, str]:
    native = [update for update in updates if not update.flatpak_ref]
    if not native:
        return {}
    try:
        result = _run_pacman(["pacman-conf", "DBPath"])
    except FileNotFoundError:
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}

    database = Path(result.stdout.strip()) / "local"
    bases = {}
    for update in native:
        versions = dict.fromkeys((update.old_version, update.old_version.split(":", 1)[-1]))
        for version in versions:
            desc = database / f"{update.name}-{version}" / "desc"
            try:
                fields = desc.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            if "%BASE%" in fields:
                index = fields.index("%BASE%") + 1
                if index < len(fields) and fields[index] and not fields[index].startswith("%"):
                    bases[update.name] = fields[index]
            break
    return bases
