from rich.console import Console
from models import PackageUpdate, ChangeType, VersionBump
from config import load_aliases

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
    VersionBump.MAJOR: "🔴",
    VersionBump.SNAPSHOT: "🌀",
}

def display_name(pkg_name: str, aliases: dict[str, str]) -> str:
    return aliases.get(pkg_name, pkg_name)


def render(updates: list[PackageUpdate]) -> None:
    aliases = load_aliases()
    visible = [u for u in updates if u.visible]
    by_category: dict[str, list[PackageUpdate]] = {c: [] for c in CATEGORY_ORDER}
    for u in visible:
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
            else:  # solo rebuild, pero es "known" o "new" (si no, no llegaría aquí)
                console.print(
                    f"🟡 {u.name} (pkgrel {u.old_pkgrel}→{u.new_pkgrel})"
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