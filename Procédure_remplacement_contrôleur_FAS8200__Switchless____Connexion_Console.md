# Procédure de remplacement d'un contrôleur NetApp FAS8200 (Switchless)

Ce document récapitule les commandes nécessaires pour se connecter en console depuis un poste d'administration Debian, vérifier l'état du système avant réintégration, et effectuer le *giveback* en toute sécurité.

---

## 1. Connexion au port console depuis Debian

La configuration série standard sur NetApp FAS8200 est **9600 bauds, 8N1**, sans contrôle de flux.

### Identifier le périphérique USB-Série
```bash
# Lister les ports série détectés
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null

# Vérifier le dernier périphérique branché via les logs noyau
dmesg | grep -iE "ttyUSB|ch341|cp210|ftdi|pl2303|serial" | tail -n 10
```

### Gérer les permissions (si nécessaire)
```bash
# Ajouter l'utilisateur courant au groupe dialout (nécessite une reconnexion de session)
sudo usermod -aG dialout $USER
```

### Se connecter avec `minicom`
```bash
# Installation (si non présent)
sudo apt update && sudo apt install minicom

# Connexion au port console (adapter ttyUSB0 si besoin)
minicom -D /dev/ttyUSB0 -b 9600
```
* **Raccourcis utiles dans `minicom` :**
  * `Ctrl+A` puis `O` : Ouvrir le menu de configuration (*Serial port setup* → vérifier `9600 8N1`, *Hardware Flow Control: No*, *Software Flow Control: No*).
  * `Ctrl+A` puis `X` : Quitter `minicom`.

### Alternative rapide avec `screen`
```bash
screen /dev/ttyUSB0 9600
# Pour quitter : Ctrl+A puis k puis y
```

---

## 2. Préparation du cluster (sur le contrôleur sain / survivant)

Désactiver le *giveback* automatique afin de pouvoir contrôler le matériel et les disques avant la bascule.

```text
# Désactiver l'auto-giveback
storage failover modify -node <nom_noeud_sain> -auto-giveback false

# Vérifier le paramètre
storage failover show -fields auto-giveback
```

---

## 3. Démarrage du nouveau contrôleur (via la console)

Après avoir recâblé les liens HA/cluster (*switchless*), les baies disques (SAS/FC), le port console et le réseau de management :

```text
# Si le contrôleur s'arrête au prompt LOADER>
boot_ontap
```
*Laisser le nœud démarrer jusqu'à l'état **`Waiting for giveback`**.*

---

## 4. Vérifications matérielles et cluster avant giveback

À exécuter depuis le contrôleur sain avant de rendre la main au contrôleur remplacé :

```text
# Vérifier l'état du failover et des partenaires HA
storage failover show

# Vérifier la santé globale du système et des nœuds
system health status show
system node show

# Vérifier qu'aucun disque n'est en erreur et contrôler la propriété des disques
storage disk show -broken
storage disk show -ownership

# Vérifier l'état des interfaces réseau (ports cluster, management et données)
network interface show
```

---

## 5. Exécution du giveback et finalisation

Une fois que toutes les vérifications sont conformes et que le nœud remplacé est en attente de giveback :

```text
# Lancer le giveback vers le contrôleur remplacé
storage failover giveback -ofnode <nom_noeud_remplace>

# Suivre la progression du giveback
storage failover show-giveback

# Une fois le giveback terminé et l'état HA revenu à la normale, réactiver l'auto-giveback
storage failover modify -node <nom_noeud_sain> -auto-giveback true
storage failover modify -node <nom_noeud_remplace> -auto-giveback true

# Contrôle final de l'état HA
storage failover show
```