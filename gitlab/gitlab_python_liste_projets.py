#!/usr/bin/env python3
"""
Liste les projets GitLab avec pagination et export CSV.
"""

import csv
import sys
import requests

# ============== CONFIG ==============
GITLAB_URL = "https://gitlab.example.com"          # sans slash final
TOKEN = "glpat-xxxxxxxxxxxxxxxxxxxx"
PER_PAGE = 100

# Filtre possible :
#   - None                  → tous les projets auxquels tu as accès
#   - "group/sous-groupe"   → uniquement les projets de ce groupe (et sous-groupes)
GROUP_PATH = "mon-groupe"                          # ← mets None pour tout récupérer
# ====================================

headers = {"PRIVATE-TOKEN": TOKEN}
params = {
    "membership": True,
    "simple": True,
    "per_page": PER_PAGE,
    "order_by": "id",
    "sort": "asc",
}

if GROUP_PATH:
    # On récupère d'abord l'ID du groupe
    r = requests.get(
        f"{GITLAB_URL}/api/v4/groups/{GROUP_PATH.replace('/', '%2F')}",
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    group_id = r.json()["id"]
    url = f"{GITLAB_URL}/api/v4/groups/{group_id}/projects"
    params["include_subgroups"] = True
else:
    url = f"{GITLAB_URL}/api/v4/projects"

all_projects = []
page = 1

print(f"Récupération des projets (filtre groupe = {GROUP_PATH or 'aucun'})...", file=sys.stderr)

while True:
    params["page"] = page
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if not data:
        break

    all_projects.extend(data)
    print(f"  page {page} → {len(data)} projets (total: {len(all_projects)})", file=sys.stderr)
    page += 1

print(f"Total : {len(all_projects)} projets\n", file=sys.stderr)

# ============== Export CSV ==============
writer = csv.writer(sys.stdout)
writer.writerow(["id", "path_with_namespace", "name", "web_url", "visibility", "archived"])

for p in all_projects:
    writer.writerow([
        p["id"],
        p["path_with_namespace"],
        p["name"],
        p["web_url"],
        p.get("visibility", ""),
        p.get("archived", False),
    ])
    
    
   # Activer le venv
source .venv/bin/activate

# Sortie à l’écran
python list_projects.py

# Ou directement dans un fichier CSV
python list_projects.py > projets.csv 

id,path_with_namespace,name,web_url,visibility,archived
12,mon-groupe/projet-a,Projet A,https://gitlab.example.com/mon-groupe/projet-a,private,False
45,mon-groupe/sous-groupe/projet-b,Projet B,https://gitlab.example.com/mon-groupe/sous-groupe/projet-b,internal,False
