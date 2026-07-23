from rich.console import Console
from rich.markdown import Markdown
from models import PackageUpdate, ChangeType, VersionBump
from config import load_aliases
from pacman import get_package_info

console = Console()

CATEGORY_TITLES = {
    "applications": "📱 Aplicaciones",
    "drivers": "🎮 Drivers",
    "desktop": "🖥️ Escritorio",
    "libraries": "🔧 Bibliotecas",
    "system": "⚙️  Sistema",
}
CATEGORY_ORDER = ["applications", "drivers", "desktop", "libraries", "system"]

BUMP_ICONS = {
    VersionBump.MAJOR: "🔴 ",     # se deja un espacio al final para que no quede pegado
    VersionBump.SNAPSHOT: "🌀 ",  # el nombre del paquete
}

def display_name(pkg_name: str, aliases: dict[str, str]) -> str:
    return aliases.get(pkg_name, pkg_name)


def render(updates: list[PackageUpdate], changelogs: dict[str, dict]) -> None:
    aliases = load_aliases()
    pkg_info = get_package_info()  # una sola llamada, se usa en toda la función

    def _print_detail(u: PackageUpdate) -> None:
        info = pkg_info.get(u.name)
        if not info:
            return
        if info.description:
            console.print(f"   [dim]{info.description}[/dim]")
        if info.required_by:
            usados_por = ", ".join(info.required_by)
            console.print(f"   [dim]usado por: {usados_por}[/dim]")
    
            
    visible = [u for u in updates if u.visible]
     # Separamos los que piden clasificación de los que van a sus categorías normales
    to_classify = [u for u in visible if u.needs_classification]
    rest = [u for u in visible if not u.needs_classification]

    by_category: dict[str, list[PackageUpdate]] = {c: [] for c in CATEGORY_ORDER}
    for u in rest:
        by_category.setdefault(u.category, []).append(u)

    for category in CATEGORY_ORDER:
        items = by_category.get(category, [])
        if not items:
            continue

        console.print(f"[bold]{'─' * 50}[/bold]")
        console.print(f"[bold]{CATEGORY_TITLES.get(category, category)}[/bold]")
        console.print(f"[bold]{'─' * 50}[/bold]")

        for u in items:
            name = display_name(u.name, aliases)
            if u.change_type is ChangeType.VERSION:
                marker = BUMP_ICONS.get(u.version_bump, "🆕 " if u.is_new else "🟢 ")
                console.print(f"{marker}{u.name} {u.old_pkgver} → {u.new_pkgver}")
                # Solo en Sistema mostramos descripción, en las categorías que ya conoces no hace falta
                if category == "system":
                    _print_detail(u)
                
                changelog = changelogs.get(u.name)
                if changelog:
                    if changelog["type"] == "text":
                        # recortamos a un tamaño razonable para no inundar la terminal
                        preview = changelog["body"][:400]
                        if len(changelog["body"]) > 400:
                            preview += "..."
                        console.print("   📝 [bold]Notas de la versión:[/bold]")
                        console.print(Markdown(changelog["body"][:600]))
                        console.print(f"   [dim]{changelog['url']}[/dim]")
                    else:
                        console.print(f"   [dim]📝 Notas de versión: {changelog['url']}[/dim]")
            else:  # solo rebuild, pero es "known" o "new" (si no, no llegaría aquí)
                console.print(
                    f"🟡 {u.name} (pkgrel {u.old_pkgrel}→{u.new_pkgrel})"
                )

    if to_classify:
        console.print(f"[bold]{'─' * 50}[/bold]")
        console.print("[bold]❓ Sin clasificar[/bold]")
        console.print(f"[bold]{'─' * 50}[/bold]")
        for u in to_classify:
            name = display_name(u.name, aliases)
            marker = BUMP_ICONS.get(u.version_bump, "🆕 " if u.is_new else "🟢 ")
            console.print(f"{marker}{name} {u.old_pkgver} → {u.new_pkgver}")
            _print_detail(u)
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
        console.print("[dim]⚙️  Rebuilds menores (sin cambio real):[/dim]")
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