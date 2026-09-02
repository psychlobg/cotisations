# Procédure de mise à niveau GitLab EE — Debian 12

**Chemin de mise à niveau :** `18.11.2 → 18.11.11 → 19.0.8 → 19.3.1`
**Méthode d'installation supposée :** paquet Linux officiel (Omnibus) via `apt`
**Date de rédaction :** 2 septembre 2026 — à revérifier avant exécution (patchs GitLab publiés 2x/mois)

---

## 0. Mise en maintenance (avant toute opération)

Avant de commencer, mettre l'instance en mode maintenance pour éviter toute écriture en base pendant les migrations.

```bash
# Activer le mode maintenance (lecture seule)
sudo gitlab-ctl deploy-page up
sudo gitlab-ctl status

# Basculer l'application en mode maintenance (lecture seule) via l'API interne
sudo gitlab-rails runner "Gitlab::Database.set_read_only" 2>/dev/null || true
```

> ⚠️ Selon la version, la commande recommandée pour le mode maintenance en lecture seule peut varier. Vérifier dans l'admin (`Admin Area > Settings > General`) qu'un bandeau de maintenance est actif, ou utiliser la page de déploiement (`deploy-page`) comme page d'attente statique pendant l'upgrade.

**Avant de couper :**

```bash
# 1. Vérifier l'espace disque disponible (prévoir large pour le dump)
df -h

# 2. Sauvegarde complète (obligatoire avant chaque upgrade majeur)
sudo gitlab-backup create BACKUP=pre-upgrade-$(date +%F)

# 3. Sauvegarder aussi gitlab.rb et gitlab-secrets.json
sudo cp /etc/gitlab/gitlab.rb /etc/gitlab/gitlab.rb.bak-$(date +%F)
sudo cp /etc/gitlab/gitlab-secrets.json /etc/gitlab/gitlab-secrets.json.bak-$(date +%F)

# 4. Copier ces sauvegardes hors serveur (S3, NAS, etc.)
```

---

## Étape 1 — 18.11.2 → 18.11.11 (dernier patch de la branche 18.11)

```bash
sudo apt update
sudo apt-cache madison gitlab-ee | grep 18.11
sudo apt install gitlab-ee=18.11.11-ee.0
```

```bash
# Vérifier la version installée
sudo gitlab-rake gitlab:env:info | grep -i "gitlab information"
sudo cat /opt/gitlab/version-manifest.txt | grep gitlab-ee

# Vérifier que les migrations sont terminées
sudo gitlab-rake db:migrate:status | grep down
```

> ℹ️ Sur les versions 18.11.0 à 18.11.6, l'upgrade ne détecte pas les configurations Mattermost obsolètes. C'est pourquoi il faut impérativement passer par **18.11.11** (et non rester en 18.11.2) avant de poursuivre vers 19.0.

**Attendre la fin des migrations en arrière-plan** avant de continuer :

```bash
sudo gitlab-rails runner -e production 'puts Gitlab::BackgroundMigration.remaining'
```

---

## Étape 2 — 18.11.11 → 19.0.8

```bash
sudo apt update
sudo apt-cache madison gitlab-ee | grep 19.0
sudo apt install gitlab-ee=19.0.8-ee.0
```

```bash
sudo gitlab-ctl reconfigure
sudo gitlab-rake db:migrate:status | grep down
```

**Points de vigilance spécifiques à cette étape :**
- Support des distributions SUSE supprimé à partir de 19.0 (non applicable ici, Debian 12).
- Paquets Linux pour Ubuntu 20.04 non fournis à partir de 19.0 (non applicable ici, Debian 12).
- Support de Redis 6 supprimé en 19.0 : vérifier la version de Redis si externe.

```bash
redis-cli --version
```

Si Redis < 7.0, migrer vers Redis 7.0+ ou Valkey 7.2+ **avant** cette étape.

**Attendre la fin des migrations en arrière-plan** avant de continuer.

---

## Étape 3 — 19.0.8 → 19.3.1 (dernière version stable)

```bash
sudo apt update
sudo apt-cache madison gitlab-ee | grep 19.3
sudo apt install gitlab-ee=19.3.1-ee.0
```

```bash
sudo gitlab-ctl reconfigure
sudo gitlab-rake db:migrate:status | grep down
```

> ℹ️ Aucun arrêt obligatoire intermédiaire (19.1/19.2) n'est requis : les points de passage obligatoires dans la série 19.x se situent aux versions x.2, x.5, x.8, x.11, et 19.5 n'est pas encore publié à cette date.

---

## 4. Vérifications post-upgrade

```bash
# Statut général des services
sudo gitlab-ctl status

# Vérification de la configuration
sudo gitlab-rake gitlab:check SANITIZE=true

# Version finale
sudo cat /opt/gitlab/version-manifest.txt | grep gitlab-ee
```

Tester manuellement :
- Connexion utilisateur (SSO/SAML/LDAP si utilisé)
- Clone/push Git (HTTPS et SSH)
- Pipelines CI/CD
- Accès aux projets et groupes

---

## 5. Sortie du mode maintenance

```bash
sudo gitlab-ctl deploy-page down
sudo gitlab-rails runner "Gitlab::Database.set_read_only(false)" 2>/dev/null || true
sudo gitlab-ctl status
```

Confirmer dans l'interface d'administration que l'instance est repassée en lecture/écriture normale.

---

## 6. Nettoyage

```bash
# Supprimer les anciens paquets .deb téléchargés si besoin d'espace disque
sudo apt-get autoremove
sudo apt-get clean

# Conserver la sauvegarde pre-upgrade au moins jusqu'à validation complète en production
```

---

## Notes générales

- Toujours consulter les **notes de version spécifiques** de chaque version cible avant l'upgrade (breaking changes, dépréciations) : `https://docs.gitlab.com/update/versions/`
- Les commandes `apt-cache madison gitlab-ee` permettent de vérifier les numéros de build exacts disponibles (`-ee.0`, `-ee.1`, etc.) — ajuster les commandes `apt install` en conséquence.
- Prévoir une fenêtre de maintenance suffisamment longue : chaque étape majeure peut déclencher des migrations de fond longues selon la taille de l'instance.
- Si l'instance est en cluster/multi-nœuds, suivre la procédure « zero-downtime » officielle plutôt que cette procédure mono-nœud.
