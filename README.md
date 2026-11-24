# pacupdate-assistant

Asistente de actualizaciones inteligente para CachyOS/Arch: resume `checkupdates`,
distingue cambios reales de rebuilds, clasifica paquetes conocidos y busca
changelogs automáticamente en GitHub/GitLab.

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

Crea un archivo `.env` en la raíz con tu token de GitHub (classic, sin scopes,
solo para subir el límite de la API pública a 5000/hora):

    GITHUB_TOKEN=ghp_...

## Uso

    python3 main.py

## Configuración

- `data/packages.yaml` — paquetes que te importan, por categoría
  (`applications`, `drivers`, `desktop`, `libraries`), con `source` opcional
  para indicar de dónde sacar el changelog:
  - `github:owner/repo`
  - `gitlab:owner/repo`
  - Si la publicación de GitHub o GitLab carece de notas, se buscan archivos
    AppStream, `CHANGELOG` y `NEWS` en la etiqueta de la versión. Para indicar
    un archivo concreto del repositorio, usa `release_notes.file`.
  - `mozilla` (solo firefox/thunderbird, plantilla de URL propia)
  - `link:https://...` (enlace fijo, para proyectos sin API de releases)
  - Las aplicaciones Flatpak instaladas se detectan automáticamente y las notas
    se buscan por versión exacta en el catálogo AppStream local de su remoto.
    Usa `flatpak:ID.de.LaAplicacion` para asignar un nombre y una categoría en este
    archivo. Si la versión es la misma, se muestra como actualización del paquete.
  - Para aplicaciones cuya web publica notas en tablas por plataforma, puedes
    añadir `release_notes` con `format: release-tables`, `url` y `platform`.
    Zoom usa esta fuente cuando AppStream no aporta notas para esa compilación.
- `data/aliases.yaml` — nombre bonito para mostrar en pantalla
- `cache/` — no tocar a mano; memoria de paquetes vistos y repos descubiertos
