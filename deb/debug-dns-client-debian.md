# Debug DNS côté client Debian

## 1. Vérifier le résolveur utilisé

```bash
# Configuration actuelle
resolvectl status

# Fichier classique
cat /etc/resolv.conf

# Ancienne commande (si systemd-resolved)
systemd-resolve --status
```

Points à regarder :
- Serveurs DNS listés
- DNSSEC activé ou non
- Cache local actif (systemd-resolved)

---

## 2. Interroger et gérer le cache (systemd-resolved)

```bash
# Voir une entrée (indique si elle vient du cache)
resolvectl query nom.exemple.com

# Vider tout le cache
resolvectl flush-caches

# Statistiques du cache
resolvectl statistics
```

---

## 3. Vérifier le TTL et les détails d’une réponse

```bash
# TTL + détails
dig +ttlunits nom.exemple.com

# Version complète
dig nom.exemple.com
```

Dans la sortie de `dig`, regarder la colonne **TTL**.

---

## 4. Précharger un nom dans le cache

```bash
# Méthodes simples
ping -c 1 nom.exemple.com
dig nom.exemple.com
resolvectl query nom.exemple.com
```

Après ces commandes, le nom est normalement en cache (jusqu’à expiration du TTL).  
Un `curl` juste après a de fortes chances de ne plus refaire de requête DNS.

---

## 5. Tests basiques de résolution

```bash
# Résolution simple
dig +short google.com
dig +short nom.interne.entreprise

# Avec timeout court
dig +time=2 +tries=1 google.com

# Voir le temps de réponse
dig google.com | grep -E "Query time|ANSWER|TTL"
```

---

## 6. Voir exactement quel serveur DNS a répondu et en combien de temps

```bash
# Méthode la plus claire
dig +stats nom.exemple.com

# Version encore plus détaillée
dig +qr +stats nom.exemple.com
```

Informations utiles dans la sortie :
- **SERVER** : adresse IP du serveur DNS qui a répondu
- **Query time** : temps de réponse en millisecondes
- **MSG SIZE** : taille de la réponse
- **WHEN** : horodatage

Exemple de sortie typique :
```
;; Query time: 12 msec
;; SERVER: 10.0.0.53#53(10.0.0.53)
;; WHEN: Thu Sep 17 21:35:00 CEST 2026
;; MSG SIZE  rcvd: 55
```

### Tester un serveur DNS précis (contourne le cache local)

```bash
# Interroger directement un serveur
dig @IP_DU_BIND google.com
dig @IP_DU_DC   ad.domaine.local

# Avec stats
dig +stats @IP_DU_BIND google.com
```

---

## 7. Logs utiles

```bash
# Logs de systemd-resolved
journalctl -u systemd-resolved -n 50 --no-pager

# Suivre en direct
journalctl -u systemd-resolved -f
```

---

## Résumé rapide des commandes les plus utiles

| Objectif                              | Commande                              |
|---------------------------------------|---------------------------------------|
| Voir le résolveur actuel              | `resolvectl status`                   |
| Interroger + voir si cache            | `resolvectl query <nom>`              |
| Vider le cache                        | `resolvectl flush-caches`             |
| Voir TTL + temps de réponse           | `dig +stats <nom>`                    |
| Forcer un serveur DNS précis          | `dig @IP <nom>`                       |
| Précharger un nom                     | `dig <nom>` ou `ping -c1 <nom>`       |
| Logs                                  | `journalctl -u systemd-resolved -n 50`|
