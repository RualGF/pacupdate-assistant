import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ChangeType(Enum):
    VERSION = "version"    # pkgver cambió → actualización real
    REBUILD = "rebuild"    # solo pkgrel cambió

class VersionBump(Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    SNAPSHOT = "snapshot"  # paquete -git/-svn/-bzr, versión no comparable de forma fiable
    UNKNOWN = "unknown"


_VCS_SUFFIXES = ("-git", "-svn", "-bzr", "-hg", "-cvs")


def _numeric_parts(version: str) -> tuple[int, ...]:
    version = version.split(":")[-1]  # quita epoch (ej. "2:1.2.3" -> "1.2.3")
    return tuple(int(n) for n in re.findall(r"\d+", version))


def classify_bump(name: str, old_pkgver: str, new_pkgver: str) -> VersionBump:
    if name.endswith(_VCS_SUFFIXES):
        return VersionBump.SNAPSHOT

    old_parts = _numeric_parts(old_pkgver)
    new_parts = _numeric_parts(new_pkgver)
    if not old_parts or not new_parts:
        return VersionBump.UNKNOWN

    for i in range(min(len(old_parts), len(new_parts))):
        if old_parts[i] != new_parts[i]:
            if i == 0:
                return VersionBump.MAJOR
            if i == 1:
                return VersionBump.MINOR
            return VersionBump.PATCH
    return VersionBump.PATCH  # ej. añadió un componente nuevo (1.2 -> 1.2.1)

@dataclass
class PackageUpdate:
    name: str
    old_pkgver: str
    old_pkgrel: str
    new_pkgver: str
    new_pkgrel: str
    category: str = "system"   # "applications" | "drivers" | "desktop" | "system"
    known: bool = False        # ¿está en packages.yaml?
    is_new: bool = False       # ¿nunca visto antes en cache?

    @property
    def change_type(self) -> ChangeType:
        return ChangeType.VERSION if self.old_pkgver != self.new_pkgver else ChangeType.REBUILD

    @property
    def old_version(self) -> str:
        return f"{self.old_pkgver}-{self.old_pkgrel}"

    @property
    def new_version(self) -> str:
        return f"{self.new_pkgver}-{self.new_pkgrel}"

    @property
    def visible(self) -> bool:
        """¿Se debe mostrar en el resumen, o es ruido?"""
        if self.change_type is ChangeType.VERSION:
            return True
        return self.known or self.is_new
    
    @property
    def version_bump(self) -> VersionBump:
        if self.change_type is not ChangeType.VERSION:
            return VersionBump.UNKNOWN
        return classify_bump(self.name, self.old_pkgver, self.new_pkgver)