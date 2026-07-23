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
  - `mozilla` (solo firefox/thunderbird, plantilla de URL propia)
  - `link:https://...` (enlace fijo, para proyectos sin API de releases)
- `data/aliases.yaml` — nombre bonito para mostrar en pantalla
- `cache/` — no tocar a mano; memoria de paquetes vistos y repos descubiertos
