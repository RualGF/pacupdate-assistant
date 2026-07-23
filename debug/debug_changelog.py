import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from github import fetch_release_notes
from config import load_github_token

token = load_github_token()
result = fetch_release_notes("CachyOS/linux-cachyos", "7.1.4", token)
print(result)

# y para ver qué tags existen realmente, sin filtrar:
import requests
headers = {"Authorization": f"Bearer {token}"} if token else {}
resp = requests.get("https://api.github.com/repos/CachyOS/linux-cachyos/releases?per_page=15", headers=headers)
for r in resp.json():
    print(r.get("tag_name"))