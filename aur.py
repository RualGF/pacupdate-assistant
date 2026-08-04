import requests
from typing import Optional

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
    resp = requests.get(AUR_RPC_URL, params=params, timeout=10)
    if resp.status_code != 200:
        return []

    data = resp.json()
    updates = []
    for result in data.get("results", []):
        name = result["Name"]
        aur_version = result["Version"]
        current = installed_versions.get(name)
        if current and aur_version != current:
            updates.append({"name": name, "old": current, "new": aur_version})
    return updates