# Synthèse – Arrêt et Redémarrage NetApp 7-Mode (Paire HA)  
**Sans sanitization – Période de rétention**

---

## 1. Procédure d’arrêt (Clean Shutdown)

### Prérequis
- Arrêt des accès clients (CIFS, NFS, iSCSI/FCP, SnapMirror, backups…)
- Sauvegardes terminées

### Étapes

1. **Accès console** (sur chaque nœud)
   ```bash
   ssh admin@<IP_SP>
   system console
   ```

2. **Désactivation du failover** (sur un des deux nœuds)
   ```bash
   cf disable
   cf status
   ```

3. **Halt propre** (sur **chaque** nœud)
   ```bash
   halt -f
   ```
   Attendre le prompt **`LOADER>`** sur les deux nœuds.

4. **Mise hors tension** (depuis le SP de chaque nœud)
   ```bash
   # Quitter la console avec Ctrl-D
   system power off
   ```
   Confirmer avec `y`.

> Les contrôleurs sont maintenant éteints proprement et peuvent rester hors tension pendant toute la période de rétention.

---

## 2. Procédure de redémarrage via SP (pendant la période de rétention)

### Étapes

1. **Connexion au SP** de chaque nœud
   ```bash
   ssh admin@<IP_SP>
   ```

2. **Allumage du nœud**
   ```bash
   system power on
   ```

3. **Suivi du boot** (recommandé)
   ```bash
   system console
   ```
   Appuyer sur Entrée pour voir le démarrage.  
   Attendre l’arrivée au prompt ONTAP (`filer>` ou `node>`).

4. **Répéter** la même opération sur le second nœud.

5. **Réactivation du failover** (une fois les deux nœuds démarrés)
   ```bash
   cf enable
   cf status
   ```

---

## Ordre recommandé de redémarrage

| Ordre | Action                          | Commentaire                              |
|-------|---------------------------------|------------------------------------------|
| 1     | Allumer les disk shelves        | Si shelves externes                      |
| 2     | `system power on` nœud 1        | Attendre le boot complet                 |
| 3     | `system power on` nœud 2        | Attendre le boot complet                 |
| 4     | `cf enable`                     | Réactiver le HA                          |

---

## Points importants

- Le `halt -f` empêche tout takeover pendant l’arrêt.
- Le `system power off` / `system power on` depuis le SP est la méthode propre pour une période de rétention.
- Ne jamais faire un `system power cycle` ou `system power off` tant que ONTAP tourne encore (risque de dirty shutdown).
- Après redémarrage, vérifier l’état de la paire HA avec `cf status` et `sysconfig -a`.

---

## Résumé ultra-court

**Arrêt :**
```
system console → cf disable → halt -f → system power off
```

**Redémarrage :**
```
system power on → system console → cf enable
```
