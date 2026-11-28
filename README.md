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

Si alguna fuente falla, el informe indica cuál y muestra las actualizaciones
confirmadas de las demás. En ese caso el comando termina con código `1`.

El informe resume los nuevos pendientes y los paquetes que ofrecen otra versión
desde la última consulta completa. Si hay hasta tres cambios de este tipo,
incluye los nombres y las versiones. La referencia se actualiza con la lista
completa de pendientes en cada consulta completa.

Al buscar notas, el informe distingue una fuente sin identificar, una versión
localizada sin notas y una consulta incompleta. Las consultas de repositorios
que fallan se pueden volver a intentar en la siguiente ejecución.

Las notas verificadas se guardan durante 24 horas en `cache/release_notes.sqlite3`.
Si la fuente, sus ajustes o las versiones del salto cambian, se consulta de nuevo.
Cada ejecución comprueba las actualizaciones pendientes.

El informe muestra el texto de notas de hasta 550 caracteres. Para notas más
largas muestra el enlace a la fuente. Si faltara el enlace, muestra un extracto.

## Configuración

- `data/packages.yaml` agrupa los paquetes por uso. `development` reúne lenguajes
  como Python y PHP, editores y herramientas de desarrollo. `terminals` incluye
  emuladores y shells, y `desktop` agrupa Plasma, KWin y Wayland. También puedes
  usar `applications`, `gaming`, `tools`, `drivers`, `libraries` y `system`.
  El campo opcional `source` indica de dónde sacar el changelog.
  Los paquetes de `system`, incluidos los que están por clasificar, muestran
  su descripción de pacman. Para ver sus notas, asígnalos a otra categoría.
  Los paquetes `python-*` de `development` muestran la descripción de pacman
  antes de las notas de versión.
  - `github:owner/repo`
  - `gitlab:owner/repo`
  - Si la publicación de GitHub o GitLab carece de notas, se buscan archivos
    AppStream, `CHANGELOG` y `NEWS` en la etiqueta de la versión. Para indicar
    un archivo concreto del repositorio, usa `release_notes.file`.
  - En saltos de versiones numéricas se muestran las notas intermedias que se
    puedan identificar en las publicaciones consultadas o en bloques del archivo.
    Un archivo sin una entrada identificable se muestra como changelog general.
    Los enlaces fijos se muestran como fuentes generales.
  - `mozilla` (solo firefox/thunderbird, plantilla de URL propia)
  - `link:https://...` (enlace fijo, para proyectos sin API de releases)
  - `cachyos-kernel:nombre-del-pkgbase` verifica en `.SRCINFO` la etiqueta del
    código fuente del kernel y consulta sus notas publicadas, incluso si solo
    cambia el `pkgrel`.
  - `shared:nombre-del-paquete` para paquetes que siguen la versión y las notas
    de otro, como los idiomas de Firefox. Si ambos actualizan a la misma versión,
    el paquete vinculado aparece debajo del principal y se muestran las notas una vez.
  - Se detectan las actualizaciones de las aplicaciones, runtimes y extensiones
    Flatpak instalados. Las notas se buscan por versión exacta en AppStream.
    Un runtime o extensión que cambia de compilación dentro de la misma rama
    aparece como tal, con un aviso si faltan notas verificadas.
    Usa `flatpak:ID.de.LaAplicacion` para asignar un nombre y una categoría en este
    archivo. Si la versión es la misma, se muestra como actualización del paquete.
  - Para aplicaciones cuya web publica notas en tablas por plataforma, puedes
    añadir `release_notes` con `format: release-tables`, `url` y `platform`.
    Zoom usa esta fuente cuando AppStream no aporta notas para esa compilación.
- `data/aliases.yaml` — nombre bonito para mostrar en pantalla
- `cache/` — no tocar a mano; memoria de paquetes vistos y repos descubiertos
