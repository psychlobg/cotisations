# Podman rootless – Mapping UID/GID & CI de test

## 1. Problématique (rappel)

En mode **rootless**, Podman mappe les UID/GID du conteneur vers une plage d’UID/GID secondaires définie dans `/etc/subuid` et `/etc/subgid`.

Format :
```text
utilisateur:start:count
```

Exemple par défaut (souvent insuffisant) :
```text
gitlab-runner:100000:65536
```

Cette plage est consommée par :
- les fichiers de l’image (UID élevés)
- les conteneurs imbriqués (Buildah, multi-stage, `podman run` depuis un job…)
- les jobs parallèles (même utilisateur = même plage)

Résultat fréquent : `insufficient UIDs or GIDs available in user namespace`.

---

## 2. Configuration recommandée sur l’hôte

### 2.1 Identifier l’utilisateur du runner

```bash
ps aux | grep -E 'gitlab-runner|podman' | head
id gitlab-runner
```

### 2.2 Voir les plages actuelles

```bash
grep -E 'gitlab-runner|^' /etc/subuid /etc/subgid
```

### 2.3 Agrandir les plages (recommandé : 1 048 576 ou plus)

Éditer `/etc/subuid` et `/etc/subgid` :

```text
# Avant (exemple)
gitlab-runner:100000:65536

# Après (recommandé pour runners intensifs)
gitlab-runner:100000:1048576
```

**Important** : les plages de tous les utilisateurs doivent être **disjointes**.

Exemple de répartition saine :
```text
user1:100000:1048576
user2:1148576:1048576
gitlab-runner:2197152:2097152
```

### 2.4 Appliquer le changement

```bash
# Vérifier qu’il n’y a pas de chevauchement
awk -F: '{print $1, $2, $2+$3-1}' /etc/subuid | sort -k2 -n

# Redémarrer le runner (et éventuellement Podman)
systemctl restart gitlab-runner
# systemctl restart podman   # si applicable
```

### 2.5 Vérification rapide côté hôte

```bash
# En tant que gitlab-runner (ou via sudo -u)
sudo -u gitlab-runner podman unshare cat /proc/self/uid_map
sudo -u gitlab-runner podman unshare cat /proc/self/gid_map

# Doit afficher une plage large, ex. :
# 0 100000 1048576
```

---

## 3. CI de test GitLab

Place ce fichier dans ton projet (ex. `.gitlab-ci.yml` ou un job dédié).

### 3.1 Job minimal de diagnostic

```yaml
stages:
  - test

# À adapter selon ton runner (tag, image, etc.)
variables:
  # Si tu utilises le socket Podman rootless
  DOCKER_HOST: "unix:///run/user/1000/podman/podman.sock"  # adapter l’UID
  # ou laisser vide si le runner est déjà configuré en executor docker/podman

test-uid-mapping:
  stage: test
  image: quay.io/podman/stable:latest   # ou une image légère avec podman
  tags:
    - your-runner-tag                   # adapter
  script:
    - echo "=== Identité dans le job ==="
    - id
    - echo "=== UID/GID map du user namespace ==="
    - cat /proc/self/uid_map || true
    - cat /proc/self/gid_map || true
    - echo "=== subuid/subgid visibles (si montés) ==="
    - cat /etc/subuid 2>/dev/null || echo "pas de /etc/subuid dans le conteneur"
    - cat /etc/subgid 2>/dev/null || echo "pas de /etc/subgid dans le conteneur"
    - echo "=== Test mapping simple (podman unshare) ==="
    - podman unshare cat /proc/self/uid_map
    - podman unshare cat /proc/self/gid_map
    - echo "=== Test création d’un conteneur rootless ==="
    - podman run --rm alpine:latest id
    - echo "=== Test avec une image qui a des UID un peu plus élevés ==="
    - podman run --rm ubuntu:22.04 bash -c "id; ls -ln /usr/bin/sudo; getent passwd | tail -5"
    - echo "=== OK si aucun message 'insufficient UIDs/GIDs' ==="
  allow_failure: false
```

### 3.2 Job plus stressant (imbrication + build)

```yaml
test-uid-mapping-nested:
  stage: test
  image: quay.io/podman/stable:latest
  tags:
    - your-runner-tag
  script:
    - echo "=== Conteneur de 1er niveau ==="
    - podman run --rm alpine:latest id

    - echo "=== Conteneur imbriqué (2e niveau) ==="
    - |
      podman run --rm -v /run/user/$(id -u)/podman/podman.sock:/run/podman/podman.sock \
        quay.io/podman/stable:latest \
        podman run --rm alpine:latest id

    - echo "=== Test Buildah (si disponible) ==="
    - |
      if command -v buildah >/dev/null; then
        buildah from --name test-ctr alpine:latest
        buildah run test-ctr id
        buildah rm test-ctr
      else
        echo "buildah non présent – skip"
      fi

    - echo "=== Résumé des maps ==="
    - podman unshare cat /proc/self/uid_map
    - podman unshare cat /proc/self/gid_map
  allow_failure: false
```

### 3.3 Critères de succès

| Test                              | Attendu                                      |
|-----------------------------------|----------------------------------------------|
| `cat /proc/self/uid_map`          | Plage large (ex. count ≥ 1048576)           |
| `podman run alpine id`            | Affiche `uid=0(root) gid=0(root)` sans erreur |
| Conteneur imbriqué                | Même chose, sans `insufficient UIDs/GIDs`   |
| Aucun message d’erreur newuidmap  | Job vert                                    |

---

## 4. Checklist rapide

- [ ] `/etc/subuid` et `/etc/subgid` contiennent une plage ≥ 1 048 576 pour l’utilisateur du runner
- [ ] Aucun chevauchement de plages entre utilisateurs
- [ ] `systemctl restart gitlab-runner` effectué après modification
- [ ] Job `test-uid-mapping` passe au vert
- [ ] Job `test-uid-mapping-nested` passe au vert (si tu fais des builds imbriqués)

---

## 5. Commandes utiles de diagnostic sur l’hôte

```bash
# Plages actuelles
grep gitlab-runner /etc/subuid /etc/subgid

# Voir le mapping effectif
sudo -u gitlab-runner podman unshare cat /proc/self/uid_map

# Lister les plages de tous les utilisateurs (pour détecter les chevauchements)
echo "=== subuid ==="
awk -F: '{printf "%-20s %10d → %10d (%d)\n", $1, $2, $2+$3-1, $3}' /etc/subuid | sort -k2 -n
echo "=== subgid ==="
awk -F: '{printf "%-20s %10d → %10d (%d)\n", $1, $2, $2+$3-1, $3}' /etc/subgid | sort -k2 -n
```
