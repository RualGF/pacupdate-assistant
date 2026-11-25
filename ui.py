from collections import defaultdict

from rich.console import Console
from rich.markdown import Markdown
from models import PackageUpdate, ChangeType, VersionBump
from config import load_aliases, load_github_token
from pacman import get_package_info
from updater import resolve_one_changelog, shared_notes_parent
from cache import ReleaseNotesCache, load_github_repo_cache
from updater import PLASMA_CHANGELOG

import re

console = Console(force_terminal=True)

CATEGORY_TITLES = {
    "applications": "📱 Aplicaciones",
    "desktop": "🖥️ Entorno de escritorio",
    "terminals": "⌨️ Terminales y shells",
    "development": "💻 Programación",
    "gaming": "🎮 Juegos y compatibilidad",
    "tools": "🛠️ Herramientas del sistema",
    "drivers": "🔌 Kernel y controladores",
    "libraries": "🔧 Bibliotecas",
    "system": "⚙️  Sistema",
}
CATEGORY_ORDER = tuple(CATEGORY_TITLES)
GROUP_TITLES = {"kf6": "KDE Frameworks", "kde-applications": "KDE Gear", "qt6": "Qt 6",
                "gcc": "GCC", "gtk4": "GTK 4", "mariadb": "MariaDB"}
GROUP_URLS = {
    "kf6": "https://kde.org/announcements/frameworks/{major}/{version}/",
    "kde-applications": "https://kde.org/es/announcements/gear/{version}/",
    "qt6": "https://code.qt.io/cgit/qt/qtreleasenotes.git/about/qt/{version}/release-note.md",
}

BUMP_ICONS = {
    VersionBump.MAJOR: "🔴 ",     # se deja un espacio al final para que no quede pegado
    VersionBump.SNAPSHOT: "🌀 ",  # el nombre del paquete
}

REFERENCE_RE = re.compile(r'^\[(\w+)\]:\s*(\S+)', re.MULTILINE)

def safe_markdown_preview(body: str, limit: int = 700) -> str:
    references = REFERENCE_RE.findall(body)
    if len(body) > limit:
        cut = body.rfind("\n", 0, limit)
        preview = body[: cut if cut > 0 else limit] + "\n..."
    else:
        preview = body
    if references:
        preview += "\n\n" + "\n".join(f"[{key}]: {url}" for key, url in references)
    return preview

def display_name(pkg_name: str, aliases: dict[str, str]) -> str:
    return aliases.get(pkg_name, pkg_name)


def render(updates: list[PackageUpdate], sources: dict[str, str], group_releases=None, absorbed=None, *,
           pkg_info=None, discovery_errors: dict[str, str] | None = None,
           notes_cache: ReleaseNotesCache | None = None) -> None:
    cache = load_github_repo_cache()
    token = load_github_token()
    absorbed = absorbed or set()
    aliases = load_aliases()
    if pkg_info is None:
        pkg_info = get_package_info()
    console.print(f"[bold]Actualizaciones pendientes: {len(updates)}[/bold]")

    def _print_update_detail(u: PackageUpdate) -> None:
        if u.category == "system":
            info = pkg_info.get(u.name)
            if info and info.description:
                console.print(f"   {info.description}", style="dim", markup=False)
            return

        changelog = resolve_one_changelog(u, sources, cache, token, discovery_errors=discovery_errors, notes_cache=notes_cache)
        parent = shared_notes_parent(sources.get(u.name, "")) if not u.flatpak_ref else ""
        if parent and u.change_type is ChangeType.VERSION:
            console.print(f"   [dim]Paquete vinculado a {display_name(parent, aliases)}.[/dim]")

        if changelog and changelog["type"] == "range":
            console.print("   📝 [bold]Notas identificadas en el salto:[/bold]")
            urls = set()
            for entry in changelog["entries"]:
                _print_version_notes(entry, entry["version"], urls)
            if changelog["target_found"]:
                return
            changelog = changelog["fallback"]

        if changelog and changelog["type"] in {"text", "link"}:
            _print_version_notes(changelog, u.new_pkgver.split(":")[-1], set())
        elif changelog and changelog["type"] == "general":
            console.print(f"   [dim]📝 Changelog general: {changelog['url']}[/dim]")
        elif changelog and changelog["type"] == "source":
            console.print(f"   [dim]📝 Fuente general: {changelog['url']}[/dim]")
        elif changelog and changelog["type"] == "reference":
            console.print("   [dim]Versión localizada sin notas oficiales.[/dim]")
            console.print(f"   [dim]Referencia de la versión: {changelog['url']}[/dim]")
        elif changelog and changelog["type"] == "diagnostic":
            prefix = "⚠ Consulta de notas incompleta. " if changelog["reason"] == "unavailable" else ""
            console.print(f"   {prefix}{changelog['message']}", style="dim", markup=False)
            if changelog.get("url"):
                console.print(f"   [dim]Referencia de la versión: {changelog['url']}[/dim]")
        elif u.change_type is ChangeType.VERSION and not parent:
            console.print("   [dim]Notas oficiales sin confirmar para esta versión.[/dim]")

    def _print_version_notes(notes: dict, version: str, urls: set[str]) -> None:
        url = notes["url"]
        label = f"Notas de la versión {version}"
        if notes["type"] == "text":
            console.print(f"   📝 [bold]{label}[/bold]")
            console.print(Markdown(safe_markdown_preview(notes["body"])))
            if url and url not in urls:
                console.print(f"   [dim]{url}[/dim]")
        elif url and url not in urls:
            console.print(f"   [dim]📝 {label}: {url}[/dim]")
        urls.add(url)
    
            
    visible = [u for u in updates if u.visible and (u.flatpak_ref or u.name not in absorbed)]
    parents = {(u.name, u.new_pkgver) for u in visible if not u.flatpak_ref
               and u.change_type is ChangeType.VERSION and not shared_notes_parent(sources.get(u.name, ""))}
    related = defaultdict(list)
    individual = []
    for u in visible:
        parent = shared_notes_parent(sources.get(u.name, ""))
        key = (parent, u.new_pkgver)
        if not u.flatpak_ref and u.change_type is ChangeType.VERSION and key in parents:
            related[key].append(u)
        else:
            individual.append(u)

    def _print_related(u: PackageUpdate) -> None:
        if not u.flatpak_ref:
            for companion in related.get((u.name, u.new_pkgver), []):
                name = display_name(companion.name, aliases)
                console.print(f"   [dim]Incluye: {name} {companion.old_pkgver} → {companion.new_pkgver}[/dim]")

     # Separamos los que piden clasificación de los que van a sus categorías normales
    to_classify = [u for u in individual if u.needs_classification]
    rest = [u for u in individual if not u.needs_classification]

    by_category: dict[str, list[PackageUpdate]] = {c: [] for c in CATEGORY_ORDER}
    for u in rest:
        by_category.setdefault(u.category, []).append(u)

    for category in CATEGORY_ORDER:
        items = by_category.get(category, [])
        matching_group = [r for r in (group_releases or []) if category == "desktop" and r["group"] == "plasma"]
        if not items and not matching_group:
            continue

        console.print(f"[bold]{'─' * 50}[/bold]")
        console.print(f"[bold]{CATEGORY_TITLES.get(category, category)}[/bold]")
        console.print(f"[bold]{'─' * 50}[/bold]")

        for u in items:
            name = display_name(u.name, aliases)
            if u.flatpak_ref:
                labels = {"user": "usuario", "system": "sistema"}
                scope = labels.get(u.flatpak_installation, u.flatpak_installation)
                name = f"{name} (Flatpak · {scope})"
            if u.flatpak_ref and u.old_pkgver == u.new_pkgver:
                version = f" {u.new_pkgver}" if u.new_pkgver else ""
                console.print(f"🟡 {name}{version} (actualización del paquete)")
            elif u.change_type is ChangeType.VERSION:
                marker = BUMP_ICONS.get(u.version_bump, "🆕 " if u.is_new else "🟢 ")
                console.print(f"{marker}{name} {u.old_pkgver or 'desconocida'} → {u.new_pkgver or 'desconocida'}")
                _print_related(u)
                _print_update_detail(u)
            else:  # solo rebuild, pero es "known" o "new" (si no, no llegaría aquí)
                console.print(f"🟡 {name} (pkgrel {u.old_pkgrel}→{u.new_pkgrel})")
                _print_update_detail(u)
    
        for rel in matching_group:
            marker = BUMP_ICONS.get(rel["bump"], "🟢 ")
            console.print(f"{marker}Paquetes de Plasma {rel['old']} → {rel['new']} ({rel['count']} paquetes más)")
            major = rel["new"].split(".")[0]
            old, new = rel["old"].split(":")[-1], rel["new"].split(":")[-1]
            console.print(f"   [dim]Anuncio: https://kde.org/es/announcements/plasma/{major}/{new}/[/dim]")
            console.print(f"   [dim]Changelog: {PLASMA_CHANGELOG.format(major=major, old=old, new=new)}[/dim]")
    
    otros = [r for r in (group_releases or []) if r["group"] != "plasma"]
    if otros:
        console.print(f"[bold]{'─' * 50}[/bold]")
        console.print("[bold]📦 Lanzamientos en bloque[/bold]")
        console.print(f"[bold]{'─' * 50}[/bold]")

        for rel in otros:
            marker = BUMP_ICONS.get(rel["bump"], "🟢 ")
            title = GROUP_TITLES.get(rel["group"], rel["group"])
            console.print(f"{marker}{title} {rel['old']} → {rel['new']} ({rel['count']} paquetes)")
            if members := rel.get("members"):
                console.print("   " + ", ".join(members), style="dim")
            template = GROUP_URLS.get(rel["group"])
            if template:
                version = rel["new"].split(":")[-1]
                major = version.split(".")[0]
                url = template.format(major=major, version=version)
                console.print(f"   [dim]📝 Notas de versión: {url}[/dim]")
            elif rel["bump"] is VersionBump.SNAPSHOT:
                console.print("   [dim]Instantánea de desarrollo.[/dim]")
            elif representative := rel.get("representative"):
                _print_update_detail(representative)
            
    if to_classify:
        console.print(f"[bold]{'─' * 50}[/bold]")
        console.print("[bold]❓ Sin clasificar[/bold]")
        console.print(f"[bold]{'─' * 50}[/bold]")
        for u in to_classify:
            name = display_name(u.name, aliases)
            marker = BUMP_ICONS.get(u.version_bump, "🆕 " if u.is_new else "🟢 ")
            console.print(f"{marker}{name} {u.old_pkgver} → {u.new_pkgver}")
            _print_related(u)
            _print_update_detail(u)
        console.print(
            "[dim]Añádelos a packages.yaml para clasificarlos.[/dim]"
        )

    # Paquetes de sistema colapsados: solo rebuild y no conocidos ni nuevos
    hidden = [
        u for u in updates
        if u.change_type is ChangeType.REBUILD and not u.visible
    ]
    if hidden:
        console.print(f"[bold]{'─' * 50}[/bold]")
        console.print("[dim]⚙️  Rebuilds (solo cambia el empaquetado):[/dim]")
        console.print(
            "[dim]" + ", ".join(display_name(u.name, aliases) for u in hidden) + "[/dim]"
        )

def render_pending_review(cache: dict[str, dict]) -> None:
    dudosos = {name: info for name, info in cache.items() if info["confidence"] != "high" and info["repo"]}
    if dudosos:
        console.print(f"[bold]{'─' * 50}[/bold]")
        console.print("[bold]🔍 Repos detectados sin confirmar[/bold]")
        console.print(f"[bold]{'─' * 50}[/bold]")
        for name, info in dudosos.items():
            console.print(f"[dim]{name} → {info['repo']} (confianza: {info['confidence']})[/dim]")
        console.print("[dim]Revísalos y, si son correctos, añádelos a packages.yaml.[/dim]")
