import requests

from models import UpdateCheckError
from pacman import compare_versions

AUR_RPC_URL = "https://aur.archlinux.org/rpc/v5/info"


def check_aur_updates(foreign_packages: set[str], installed_versions: dict[str, str]) -> list[dict]:
    """
    Consulta de golpe la última versión publicada en AUR de todos tus paquetes foráneos,
    y devuelve los que tienen versión más nueva que la instalada.
    """
    if not foreign_packages:
        return []

    # la API acepta varios 'arg[]' en una sola petición, evitamos 1 request por paquete
    params = [("arg[]", pkg) for pkg in foreign_packages]
    try:
        resp = requests.get(AUR_RPC_URL, params=params, timeout=10)
    except requests.Timeout as error:
        raise UpdateCheckError("AUR no respondió en el tiempo previsto.") from error
    except requests.RequestException as error:
        raise UpdateCheckError("No se pudo conectar con AUR.") from error
    if resp.status_code != 200:
        raise UpdateCheckError(f"AUR devolvió HTTP {resp.status_code}.")

    try:
        data = resp.json()
    except ValueError as error:
        raise UpdateCheckError("AUR devolvió una respuesta JSON inválida.") from error
    if not isinstance(data, dict) or data.get("type") == "error" or not isinstance(data.get("results"), list):
        raise UpdateCheckError("AUR no devolvió un listado válido de paquetes.")
    updates = []
    for result in data["results"]:
        if not isinstance(result, dict):
            raise UpdateCheckError("AUR devolvió un paquete con datos incompletos.")
        name = result.get("Name")
        aur_version = result.get("Version")
        if not isinstance(name, str) or not name or not isinstance(aur_version, str) or not aur_version:
            raise UpdateCheckError("AUR devolvió un paquete sin nombre o versión.")
        current = installed_versions.get(name)
        if current and aur_version != current and compare_versions(aur_version, current) > 0:
            updates.append({"name": name, "old": current, "new": aur_version})
    return updates
