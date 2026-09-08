# Analyse de performance Podman pour GitLab Runners

Ce document compare les options de configuration Podman pour optimiser les runners de projet (performance) par rapport aux runners d’instance (sécurité).

---

## 1. Pull Policy : `if-not-present` vs `always`

| Aspect                    | `always` (sécurité)                          | `if-not-present` (performance)                  | Gain attendu |
|---------------------------|----------------------------------------------|--------------------------------------------------|--------------|
| **Comportement**          | Télécharge **toujours** l’image              | Utilise l’image locale si elle existe           | — |
| **Temps de démarrage**    | Réseau + vérification de digest à chaque job | Quasi immédiat si l’image est en cache          | **Très important** |
| **Bande passante**        | Consommée à chaque job                       | Quasi nulle après le premier pull               | Énorme sur images lourdes |
| **Sécurité**              | Garantit toujours la dernière version        | Risque d’utiliser une ancienne image            | Moins sûr |
| **Cas d’usage idéal**     | Runners d’instance partagés                  | Runners de projet dédiés                        | — |

### Gains concrets

| Type d’image                          | Gain de temps par job      |
|---------------------------------------|----------------------------|
| Images légères (alpine, busybox…)     | 2 à 8 secondes             |
| Images moyennes (node, python, golang)| 10 à 30 secondes           |
| Images lourdes (CI complexes, Android…)| 30 à 90+ secondes         |

> **Note** : Avec `if-not-present`, l’image n’est jamais mise à jour automatiquement. Il faut périodiquement faire un `podman image prune` ou un `podman rmi` pour forcer le re-pull.

---

## 2. Storage Driver : `overlay` vs `vfs`

| Aspect                         | `vfs`                                      | `overlay` (recommandé)                       | Gain attendu |
|--------------------------------|--------------------------------------------|----------------------------------------------|--------------|
| **Principe**                   | Copie complète de toutes les couches       | Copy-on-Write (CoW)                          | — |
| **Vitesse création conteneur** | Lente (copie physique)                     | Très rapide                                  | **Important** |
| **Vitesse I/O**                | Mauvaise                                   | Bonne (surtout native overlay)               | **Important** |
| **Espace disque**              | Très gourmand (pas de partage de couches)  | Beaucoup plus efficace                       | **Énorme** |
| **Compatibilité rootless**     | Toujours disponible                        | Native (kernel ≥ 5.11) ou fuse-overlayfs     | — |

### Ordre de performance (du plus rapide au plus lent)

1. **Native overlay** (kernel ≥ 5.11) → le meilleur
2. **fuse-overlayfs**
3. **vfs** → le plus lent

### Gains concrets observés

| Métrique                        | Gain typique                  |
|---------------------------------|-------------------------------|
| Création de conteneur           | 2× à 5× plus rapide           |
| Builds d’images                 | 20 à 50 % plus rapides        |
| Consommation disque             | 50 à 80 % d’espace en moins   |
| I/O (lecture/écriture)          | Nettement meilleures          |

---

## 3. Comment vérifier si Native Overlay est disponible

Exécutez ces commandes **avec l’utilisateur qui fait tourner le runner** (rootless) :

```bash
podman info -f '{{.Store.GraphDriverName}}'
podman info -f '{{index .Store.GraphStatus "Native Overlay Diff"}}'
```

### Interprétation des résultats

| GraphDriverName | Native Overlay Diff | Signification                    |
|-----------------|---------------------|----------------------------------|
| `overlay`       | `true`              | **Native overlay** (le meilleur) |
| `overlay`       | `false`             | fuse-overlayfs                   |
| `vfs`           | `false`             | VFS (le plus lent)               |

### Exemples

**Native overlay disponible et actif :**
```bash
$ podman info -f '{{.Store.GraphDriverName}}'
overlay
$ podman info -f '{{index .Store.GraphStatus "Native Overlay Diff"}}'
true
```

**fuse-overlayfs :**
```bash
overlay
false
```

**VFS :**
```bash
vfs
false
```

### Conditions pour native overlay en rootless

- Kernel **≥ 5.11** (idéalement ≥ 5.13)
- Podman ≥ 3.1
- Pas de `mount_program = "/usr/bin/fuse-overlayfs"` forcé dans `~/.config/containers/storage.conf`

Vérifier la version du kernel :
```bash
uname -r
```

---

## 4. Configuration recommandée pour runners de projet

### Dans `config.toml` du runner

```toml
[[runners]]
  # ...
  [runners.docker]
    pull_policy = "if-not-present"
    # autres options...
```

### Dans `~/.config/containers/storage.conf` (utilisateur du runner)

```toml
[storage]
driver = "overlay"

# Uniquement si native overlay n’est pas disponible
# [storage.options.overlay]
# mount_program = "/usr/bin/fuse-overlayfs"
```

Après modification de `storage.conf` :
```bash
podman system reset   # Attention : supprime toutes les images et conteneurs existants
```

---

## 5. Résumé des gains attendus

| Optimisation              | Gain principal                          | Impact typique          |
|---------------------------|-----------------------------------------|-------------------------|
| `if-not-present`          | Temps de démarrage des jobs             | Fort (surtout images lourdes) |
| `overlay` vs `vfs`        | Création de conteneurs + I/O + espace   | Très fort               |
| Les deux combinés         | Expérience globale du développeur       | Très notable            |
