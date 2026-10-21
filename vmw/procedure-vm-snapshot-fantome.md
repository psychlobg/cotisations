# VM bloquée « les disques doivent être consolidés » : repartir du disque de base

Contexte : environnement de test, datastore NFS 4.1 (NetApp), une seule VM sur le datastore. Un backup Veeam interrompu a laissé des fichiers de snapshot `<vm>-00000x.vmdk` orphelins. Aucun snapshot visible dans vCenter, *Consolider* échoue, la VM est éteinte et ne démarre pas. Plus aucun processus ni verrou apparent, Veeam arrêté.

Objectif : le plus court chemin pour retrouver une VM démarrable (ou la rebuilder).

Principe : le disque de base (`<vm>.vmdk` + `<vm>-flat.vmdk`) contient l'état de la VM **au moment où Veeam a pris le snapshot**. Tout ce qui a été écrit ensuite est dans les deltas `-00000x`, que cette procédure abandonne. Acceptable en test.

Remplacez partout `<ds>` (nom du datastore) et `<vm>` (nom du dossier/fichiers de la VM).

---

## 0. Préparer

1. La VM est **éteinte**.
2. Dans vCenter : clic droit sur la VM, *Supprimer de l'inventaire*. **Pas** « Supprimer du disque ».
3. Connexion SSH à l'hôte ESXi qui voit le datastore :

```bash
cd /vmfs/volumes/<ds>/<vm>
ls -lah
```

Notez la présence et la taille de :

| Fichier | Rôle | Attendu |
|---|---|---|
| `<vm>.vmdk` | descripteur du disque de base (petit fichier texte) | quelques centaines d'octets |
| `<vm>-flat.vmdk` | données du disque de base | taille du disque (peut être creux si thin) |
| `<vm>-00000x.vmdk` et `-delta.vmdk` / `-sesparse.vmdk` | disques de snapshot (à abandonner) | |

---

## 1. Vérifier le disque de base

```bash
vmkfstools -e <vm>.vmdk
```

Résultat attendu si tout est sain : `Disk chain is consistent.`

Vous obtenez une erreur : lisez le message et suivez le cas correspondant.

| Message (approximatif) | Cause probable | Aller au cas |
|---|---|---|
| `Failed to lock the file`, `Device or resource busy`, `Failed to open disk` avec mention de lock | Verrou NFS encore tenu côté serveur | **A** |
| `Cannot open the disk`, `file not found`, `No such file` | `-flat` ou descripteur manquant ou mal nommé | **B** puis **C** |
| `Disk chain is not consistent`, `parent ... CID mismatch`, erreur de lecture du descripteur | Descripteur corrompu ou incohérent | **B** |
| Erreurs d'E/S, `-flat` à 0 octet ou beaucoup trop petit | Données de base endommagées | **C** |

Vérifications complémentaires, sans danger :

```bash
cat <vm>.vmdk                                   # le descripteur est-il lisible ? (texte)
grep -E '^(CID|parentCID|createType)|RW|RDONLY' <vm>.vmdk
ls -l <vm>-flat.vmdk
vmkfstools -x check <vm>.vmdk                   # contrôle d'intégrité du disque
```

Dans le descripteur de la base : `parentCID=ffffffff` (pas de parent) et une ligne `RW <secteurs> VMFS "<vm>-flat.vmdk"` (ou `FLAT`).

---

## Cas A : verrou NFS résiduel

Aucun processus ne tourne, mais la session NFS 4.1 peut garder des verrous côté serveur. Avec une seule VM sur le datastore, le plus simple est de couper la session en démontant puis remontant le datastore.

```bash
esxcli storage nfs41 list                    # NOTER : Volume Name, Host(s), Share
esxcli storage nfs41 remove -v <nom_du_datastore>
esxcli storage nfs41 add -H <ip1,ip2> -s <share> -v <nom_du_datastore>
```

Remontez avec **exactement** les mêmes IP, dans le même ordre, le même chemin et le même nom, pour ne pas recréer un datastore en doublon dans vCenter. Puis relancez `vmkfstools -e <vm>.vmdk` (section 1).

Si le verrou persiste, voir côté NetApp (quand vous aurez l'accès) : `vserver locks show -vserver <svm> -volume <vol>`. Si la VM de test n'a aucune valeur, passez directement au **cas C**.

---

## Cas B : descripteur corrompu ou manquant, `-flat` intact

À utiliser seulement si `<vm>-flat.vmdk` existe avec une taille cohérente.

```bash
ls -l <vm>-flat.vmdk        # noter la taille EXACTE en octets
```

1. Créer un disque temporaire de même taille (mêmes type de contrôleur et provisionnement que l'original ; `lsilogic` par défaut, `pvscsi` ou `buslogic` selon la VM) :

```bash
vmkfstools -c <taille_en_octets> -d thin -a lsilogic <vm>_tmp.vmdk
```

2. Supprimer le `-flat` temporaire et ne garder que son descripteur :

```bash
rm <vm>_tmp-flat.vmdk
```

3. Pointer ce descripteur sur le vrai `-flat` :

```bash
vi <vm>_tmp.vmdk
# modifier la ligne RW ... : remplacer "<vm>_tmp-flat.vmdk" par "<vm>-flat.vmdk"
```

4. Remplacer l'ancien descripteur (sauvegardez-le d'abord) :

```bash
mv <vm>.vmdk <vm>.vmdk.bak 2>/dev/null
mv <vm>_tmp.vmdk <vm>.vmdk
vmkfstools -e <vm>.vmdk
```

Si `Disk chain is consistent.` : passez au **cas D**. Sinon : **cas C**.

---

## Cas C : base inutilisable, ou rebuild souhaité

Rien à récupérer : on supprime le dossier et on recrée la VM.

```bash
cd /vmfs/volumes/<ds>
rm -rf <vm>
```

Si `rm` échoue sur un verrou, appliquez le **cas A** (démontage/remontage), puis recommencez. Recréez ensuite la VM (modèle, ISO, ou playbook Ansible).

---

## Cas D : base saine, écarter les snapshots et démarrer

1. Déplacer les fichiers de snapshot hors du dossier (au lieu de les supprimer) :

```bash
cd /vmfs/volumes/<ds>/<vm>
mkdir ../ancien
mv *-0000*.vmdk *-0000*-delta.vmdk *-0000*-sesparse.vmdk *.vmsd *.vmsn *.vmem ../ancien/ 2>/dev/null
ls -lah
```

Une erreur de verrou sur le `mv` : retour au **cas A**.

2. Faire pointer la VM sur la base :

```bash
vi <vm>.vmx
```

Pour chaque disque (`scsi0:0`, `scsi0:1`, …) :
```
scsi0:0.fileName = "<vm>.vmdk"
```
Supprimez toute ligne `snapshot.*`.

3. Réenregistrer la VM :

```bash
vim-cmd solo/registervm /vmfs/volumes/<ds>/<vm>/<vm>.vmx
```

4. Dans vCenter, allumer la VM et répondre **« J'ai déplacé »** à la question affichée.

5. Après validation du démarrage et de l'état des applications, supprimer définitivement `../ancien/`.

---

## 2. Contrôles finaux

```bash
ls -lah /vmfs/volumes/<ds>/<vm>     # plus de -0000x.vmdk, plus de .vmsd/.vmsn orphelins
vmkfstools -e /vmfs/volumes/<ds>/<vm>/<vm>.vmdk
```

Dans vCenter : plus d'alerte « disques à consolider », aucun datastore `(n)` ajouté, datastore accessible.

## 3. Avant de relancer Veeam

- Aucun disque de la VM ne doit rester attaché à un proxy hot-add :

```powershell
Get-VM | Get-HardDisk |
  Where-Object { $_.Filename -like '*<vm>*' -and $_.Parent.Name -ne '<vm>' } |
  Select-Object Parent, Filename
```

Si un proxy apparaît, retirez le disque **du proxy sans supprimer les fichiers** (`Remove-HardDisk` sans `-DeletePermanently`).
- Vérifiez que le proxy et l'hôte de la VM voient le même datastore sain (pas un doublon `(n)` inaccessible).
- Lancez d'abord un job de test sur cette seule VM, en surveillant l'apparition éventuelle d'un snapshot Veeam résiduel.
