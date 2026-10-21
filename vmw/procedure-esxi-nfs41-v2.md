# Datastores NFS 4.1 en doublon `(n)` dans vCenter : diagnostic et automatisation

Contexte : vSphere 7, ESXi Lenovo, NetApp ONTAP 9.16, NFS 4.1, 100 datastores montés sur chacun des 52 hôtes.
Symptôme : datastores « répliques » inaccessibles suffixés `(n)`, **visibles uniquement dans vCenter** (pas dans `esxcli` sur l'hôte). Corrigé en retirant puis réintégrant l'hôte (8 hôtes sur 52).
Les recommandations NetApp pour VMware sont déjà appliquées : elles sont vérifiées en section 3, mais ne sont pas la piste principale.

---

## 1. Causes probables, par ordre

| # | Hypothèse | Pourquoi elle colle aux symptômes | Comment la confirmer |
|---|---|---|---|
| 1 | Montages lancés **avant que le dvSwitch et le vmkernel NFS soient prêts** (ordre des tâches Ansible, hôtes ayant perdu ou jamais eu le dvSwitch) | Seuls certains hôtes sont touchés ; les montages échouent ou sont relancés et vCenter crée des objets parasites | §2.5 et §2.6, puis corrélation avec les logs (§6) |
| 2 | **Montage non identique** d'un hôte à l'autre (liste d'IP, ordre des IP, nom de serveur, chemin, sécurité) | vCenter déduit l'identité du datastore de ces éléments : une différence crée un nouvel objet suffixé | §2.3 et §2.4 |
| 3 | **Rafale de montages** (52 hôtes × 100 datastores en parallèle) avec timeouts et relances | Peu de VM, mais beaucoup de sessions NFS 4.1 simultanées | Horodatage des doublons vs lancement des playbooks |
| 4 | **Dérive de paramètres** sur les hôtes touchés malgré l'application des recommandations NetApp | Un hôte déployé avant le correctif, un redémarrage manquant, ou un host profile incomplet | §3 |
| 5 | Désynchronisation de l'inventaire vCenter (vpxd) | Le retrait/réintégration d'hôte purge les associations hôte-datastore | Reconnexion de l'hôte (§4) |

Côté NetApp (sessions NFSv4.1 par LIF, EMS, export-policy), à regarder quand vous aurez l'accès, mais ce n'est pas la première piste puisque les doublons n'existent que dans vCenter.

---

## 2. PowerCLI : collecter les preuves

```powershell
Connect-VIServer -Server vcenter.mydomain.org
```

### 2.1 Datastores inaccessibles ou indisponibles

```powershell
Get-Datastore |
  Where-Object { -not $_.Accessible -or $_.State -ne 'Available' } |
  Select-Object Name, Type, State, Accessible, RemoteHost, RemotePath
```

### 2.2 Doublons (nom finissant par `(n)`) et orphelins

```powershell
# Doublons
Get-Datastore | Where-Object { $_.Name -match '\(\d+\)$' } |
  Select-Object Name, State, Accessible, @{N='NbHotes'; E={ $_.ExtensionData.Host.Count }}

# Datastores sans aucun hôte rattaché
Get-Datastore | Where-Object { $_.ExtensionData.Host.Count -eq 0 } | Select-Object Name, State
```

### 2.3 Comparer l'identité du datastore sain et du doublon

```powershell
Get-Datastore -Name 'NOM_DU_DATASTORE*' | ForEach-Object {
  [pscustomobject]@{
    Name        = $_.Name
    RemotePath  = $_.RemotePath
    RemoteHosts = ($_.ExtensionData.Info.Nas.RemoteHostNames -join ',')   # l'ordre compte
    Type        = $_.ExtensionData.Info.Nas.Type
    Security    = $_.ExtensionData.Info.Nas.SecurityType
    Url         = $_.ExtensionData.Info.Url
  }
}
```

### 2.4 Détecter les montages hétérogènes sur l'ensemble des datastores

Regroupe par chemin d'export les liste d'IP distinctes : plus d'un résultat par chemin = montages non identiques.

```powershell
Get-Datastore | Where-Object { $_.Type -like 'NFS*' } |
  Select-Object @{N='Path';E={$_.RemotePath}},
                @{N='Servers';E={$_.ExtensionData.Info.Nas.RemoteHostNames -join ','}} |
  Group-Object Path | Where-Object { ($_.Group.Servers | Select-Object -Unique).Count -gt 1 }
```

### 2.5 Hôtes rattachés à un doublon, avec état de montage

```powershell
$ds = Get-Datastore -Name 'NOM_DU_DATASTORE (10)'
$ds.ExtensionData.Host | ForEach-Object {
  [pscustomobject]@{
    Host               = (Get-VIObjectByVIView -MoRef $_.Key).Name
    Mounted            = $_.MountInfo.Mounted
    Accessible         = $_.MountInfo.Accessible
    InaccessibleReason = $_.MountInfo.InaccessibleReason
  }
}
```

### 2.6 Réseau : hôtes sans dvSwitch ou sans vmkernel NFS

```powershell
$vds = Get-VDSwitch -Name 'NOM_DU_DVSWITCH'
$attaches = Get-VMHost -DistributedSwitch $vds

# Hôtes NON rattachés au dvSwitch
Get-VMHost | Where-Object { $_.Name -notin $attaches.Name } | Select-Object Name, ConnectionState

# vmkernel de chaque hôte (vérifier le vmk NFS : IP, portgroup)
Get-VMHost | Get-VMHostNetworkAdapter -VMKernel |
  Select-Object VMHost, Name, IP, PortGroupName, SubnetMask | Sort-Object VMHost, Name
```

Comparez les 8 hôtes touchés avec des hôtes sains.

### 2.7 Montages vus côté hôte

```powershell
$h = Get-VMHost 'esxi01.mydomain.org'
(Get-EsxCli -VMHost $h -V2).storage.nfs41.list.Invoke() |
  Select-Object VolumeName, Host, Share, Accessible, Mounted
```

---

## 3. Vérifier les paramètres NFS (déjà appliqués, on contrôle seulement la conformité)

Valeurs indiquées dans la documentation NetApp (ONTAP tools for VMware vSphere) :

| Paramètre | Valeur | Remarque |
|---|---|---|
| `NFS.MaxVolumes` | 256 | |
| `NFS41.MaxVolumes` | 256 | **Spécifique NFS 4.1** : à vérifier en priorité |
| `NFS.MaxQueueDepth` | 128 ou plus | Peut ne pas fonctionner correctement sur ESXi 7.0.1 et 7.0.2 (KB VMware 86331) |
| `Net.TcpipHeapSize` | 32 | |
| `Net.TcpipHeapMax` | 1024 (MB) | Redémarrage nécessaire |
| `SunRPC.MaxConnPerIP` | 128 | Concerne surtout le NFSv3 |

```powershell
# Version et build des hôtes (repérer 7.0.1 / 7.0.2)
Get-VMHost | Select-Object Name, Version, Build | Sort-Object Name

# Valeurs courantes sur tous les hôtes
Get-VMHost |
  Get-AdvancedSetting -Name NFS.MaxVolumes, NFS41.MaxVolumes, NFS.MaxQueueDepth,
                            Net.TcpipHeapSize, Net.TcpipHeapMax, SunRPC.MaxConnPerIP |
  Select-Object Entity, Name, Value | Sort-Object Name, Entity | Format-Table -AutoSize
```

Sur un hôte (SSH) :

```bash
vmware -vl
esxcli system settings advanced list -o /NFS41/MaxVolumes
esxcli system settings advanced list -o /NFS/MaxQueueDepth
esxcli system settings advanced list -o /Net/TcpipHeapMax
```

---

## 4. Remédiation d'un hôte touché (sans le retirer de l'inventaire)

Dans l'ordre, en s'arrêtant dès que les doublons disparaissent :

```powershell
# 1. Déconnecter puis reconnecter l'hôte dans vCenter
Set-VMHost -VMHost $h -State Disconnected -Confirm:$false
Set-VMHost -VMHost $h -State Connected    -Confirm:$false
```

```bash
# 2. Redémarrer les agents de gestion sur l'hôte (SSH)
/etc/init.d/hostd restart
/etc/init.d/vpxa restart
```

3. Vérifier qu'aucun datastore `(n)` ne subsiste (§2.2). Un datastore sans hôte rattaché disparaît de vCenter.
4. En dernier recours seulement : retrait puis réintégration de l'hôte.

---

## 5. Ansible

Collection : `community.vmware` (+ `pyvmomi` sur le contrôleur).

```bash
ansible-galaxy collection install community.vmware
pip install pyvmomi
```

`ansible.cfg` :

```ini
[defaults]
forks = 10        # >= taille du lot
```

`group_vars/all.yml` (secrets dans Ansible Vault) :

```yaml
vcenter_hostname: vcenter.mydomain.org
vcenter_username: "svc-ansible@vsphere.local"
vcenter_password: "{{ vault_vcenter_password }}"
vcenter_datacenter: DC_PROD
cluster_staging: CL_INST
cluster_cible: CL_PROD
dvs_name: NOM_DU_DVSWITCH
vmk_nfs_name: vmk1            # vmkernel NFS attendu
nfs_advanced_options:
  NFS.MaxVolumes: 256
  NFS41.MaxVolumes: 256
  NFS.MaxQueueDepth: 128
  Net.TcpipHeapSize: 32
  Net.TcpipHeapMax: 1024
```

### 5.1 Play : lots de 5 hôtes en parallèle

`serial: 5` traite l'inventaire par lots de 5 hôtes, chaque lot en parallèle. `max_fail_percentage: 0` arrête le déploiement dès qu'un hôte échoue, pour ne pas propager le problème aux lots suivants.

```yaml
- name: Préparation et montage NFS des ESXi (lots de 5)
  hosts: esxi
  gather_facts: false
  connection: local
  serial: 5
  max_fail_percentage: 0
  vars:
    ansible_python_interpreter: "{{ ansible_playbook_python }}"
  module_defaults:
    group/vmware:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      validate_certs: false

  tasks:
```

Alternative : `throttle: 5` sur une tâche précise pour limiter sa concurrence sans découper tout le play.

### 5.2 Mise en maintenance

```yaml
    - name: Mettre l'hôte en maintenance
      community.vmware.vmware_maintenancemode:
        esxi_hostname: "{{ inventory_hostname }}"
        state: present
        evacuate: true
        timeout: 3600
```

Sortie de maintenance : même module avec `state: absent`.

### 5.3 Changement de cluster

L'hôte doit être en maintenance et rester dans le **même datacenter** (dvSwitch et datastores sont des objets de niveau datacenter).

```yaml
    - name: Déplacer l'hôte vers le cluster de staging
      community.vmware.vmware_host:
        datacenter: "{{ vcenter_datacenter }}"
        cluster: "{{ cluster_staging }}"
        esxi_hostname: "{{ inventory_hostname }}"
        state: present
```

> Le comportement de `vmware_host` sur un hôte déjà présent dans un autre cluster dépend de la version de la collection : testez sur un hôte. Repli PowerCLI : `Move-VMHost -VMHost $h -Destination (Get-Cluster 'CL_INST')`.

### 5.4 Paramètres NFS

```yaml
    - name: Appliquer les paramètres NFS
      community.vmware.vmware_host_config_manager:
        esxi_hostname: "{{ inventory_hostname }}"
        options: "{{ nfs_advanced_options }}"
      register: nfs_params

    - name: Redémarrer l'hôte si les paramètres ont changé
      community.vmware.vmware_host_powerstate:
        esxi_hostname: "{{ inventory_hostname }}"
        state: reboot-host
      when: nfs_params is changed

    - name: Attendre le retour de l'hôte
      ansible.builtin.wait_for:
        host: "{{ inventory_hostname }}"
        port: 443
        delay: 60
        timeout: 1200
      when: nfs_params is changed

    - name: Attendre la reconnexion à vCenter
      community.vmware.vmware_host_facts:
        esxi_hostname: "{{ inventory_hostname }}"
      register: host_facts
      until: host_facts is succeeded
      retries: 20
      delay: 30
      when: nfs_params is changed
```

### 5.5 Barrière réseau : ne pas monter tant que dvSwitch et vmkernel NFS ne sont pas prêts (hypothèse n°1)

```yaml
    - name: Rattacher l'hôte au dvSwitch (idempotent)
      community.vmware.vmware_dvs_host:
        esxi_hostname: "{{ inventory_hostname }}"
        switch_name: "{{ dvs_name }}"
        vmnics: "{{ dvs_vmnics }}"      # liste définie dans host_vars
        state: present

    - name: Lire les vmkernel de l'hôte
      community.vmware.vmware_vmkernel_info:
        esxi_hostname: "{{ inventory_hostname }}"
      register: vmks

    - name: Bloquer si le vmkernel NFS est absent
      ansible.builtin.assert:
        that:
          - vmks.host_vmk_info[inventory_hostname] | map(attribute='device') | list is contains(vmk_nfs_name)
        fail_msg: "vmkernel NFS {{ vmk_nfs_name }} absent sur {{ inventory_hostname }}"
```

> Adaptez le contrôle à la structure retournée par `vmware_vmkernel_info` dans votre version (`debug: var=vmks` pour la voir).

### 5.6 Montage des datastores en séquence avec pause

Le `loop` est séquentiel par hôte ; avec `serial: 5`, cela donne au plus 5 hôtes montant en parallèle, un datastore à la fois, au lieu d'une rafale de 100 montages simultanés.

```yaml
    - name: Monter les datastores NFS 4.1
      community.vmware.vmware_host_datastore:
        esxi_hostname: "{{ inventory_hostname }}"
        datastore_name: "{{ item.name }}"
        datastore_type: nfs41
        nfs_server: "{{ item.server }}"
        nfs_path: "{{ item.path }}"
        nfs_ro: false
        state: present
      loop: "{{ nfs_datastores }}"
      loop_control:
        pause: 2
        label: "{{ item.name }}"
```

> Pour NFS 4.1 en multi-LIF, vérifiez que votre version de la collection accepte une liste d'IP dans `nfs_server`. Sinon : `esxcli storage nfs41 add -H ip1,ip2 -s /chemin -v NOM` via `community.vmware.vmware_host_esxcli`. **La même liste d'IP dans le même ordre doit être utilisée sur tous les hôtes.**

### 5.7 Remise en production

```yaml
    - name: Déplacer l'hôte vers le cluster cible
      community.vmware.vmware_host:
        datacenter: "{{ vcenter_datacenter }}"
        cluster: "{{ cluster_cible }}"
        esxi_hostname: "{{ inventory_hostname }}"
        state: present

    - name: Sortir l'hôte de maintenance
      community.vmware.vmware_maintenancemode:
        esxi_hostname: "{{ inventory_hostname }}"
        state: absent
```

### 5.8 Ordre du playbook

1. Maintenance → 2. déplacement vers `CL_INST` → 3. paramètres NFS (+ redémarrage si besoin) → 4. dvSwitch + barrière vmkernel → 5. montage séquentiel → 6. contrôle (§2.2, aucun `(n)`, tous accessibles) → 7. cluster cible → 8. sortie de maintenance.

---

## 6. Corréler les doublons avec les logs

Pour chaque apparition d'un doublon, notez l'horodatage dans vCenter (Tasks/Events de l'hôte), puis cherchez à cette heure :

- VCSA : `/var/log/vmware/vpxd/vpxd.log`
- Hôte : `/var/log/vmkernel.log`, `/var/log/vobd.log`, `/var/log/hostd.log` (mots-clés `NFS41`, `dvs`, `vmk`, `timeout`, `mount`)
- Vos logs d'exécution Ansible à la même heure

Questions à trancher : le dvSwitch ou le vmkernel NFS était-il absent à ce moment ? Le montage a-t-il été relancé ? L'hôte a-t-il été déconnecté de vCenter pendant l'opération ?
