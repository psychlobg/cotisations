# Procédure : paramètres NFS des ESXi, diagnostic des datastores en doublon et automatisation Ansible

Contexte : cluster vSphere 7, hôtes ESXi Lenovo, datastores NFS 4.1 sur NetApp ONTAP 9.16, 100 datastores montés par hôte, 52 hôtes.
Symptôme : datastores « répliques » inaccessibles suffixés `(n)`, visibles uniquement dans vCenter.

---

## 1. Paramètres avancés NFS à configurer sur les ESXi

| Paramètre | Défaut | Valeur cible | Redémarrage ESXi |
|---|---|---|---|
| `NFS.MaxVolumes` | 8 | **256** | Non (recommandé en pratique) |
| `Net.TcpipHeapSize` | 0 (selon version) | **32** | Oui |
| `Net.TcpipHeapMax` | variable | **512** | Oui |

> À valider avec la documentation VMware (KB « Increasing the default value that defines the maximum number of NFS mounts on an ESXi/ESX host ») et les bonnes pratiques NetApp (TR-4597, ONTAP tools for VMware vSphere) pour votre build exact.
> `NFS.MaxQueueDepth` peut aussi être évalué avec NetApp, mais ne l'appliquez pas sans validation.

### 1.1 Vérifier sur un hôte (SSH)

```bash
esxcli system settings advanced list -o /NFS/MaxVolumes
esxcli system settings advanced list -o /Net/TcpipHeapSize
esxcli system settings advanced list -o /Net/TcpipHeapMax
```

Lire la ligne `Int Value` (valeur courante) et `Default Int Value`.

### 1.2 Appliquer sur un hôte (SSH)

```bash
esxcli system settings advanced set -o /NFS/MaxVolumes   -i 256
esxcli system settings advanced set -o /Net/TcpipHeapSize -i 32
esxcli system settings advanced set -o /Net/TcpipHeapMax  -i 512
```

Redémarrer l'hôte (en maintenance) pour que les paramètres `Net.TcpipHeap*` soient pris en compte.

### 1.3 Vérifier sur tous les hôtes (PowerCLI)

```powershell
Connect-VIServer -Server vcenter.mydomain.org

Get-VMHost |
  Get-AdvancedSetting -Name NFS.MaxVolumes, Net.TcpipHeapSize, Net.TcpipHeapMax |
  Select-Object Entity, Name, Value |
  Sort-Object Name, Entity |
  Format-Table -AutoSize

# Hôtes dont une valeur diffère de la cible
$cible = @{ 'NFS.MaxVolumes' = 256; 'Net.TcpipHeapSize' = 32; 'Net.TcpipHeapMax' = 512 }
Get-VMHost | ForEach-Object {
  $h = $_
  foreach ($k in $cible.Keys) {
    $v = (Get-AdvancedSetting -Entity $h -Name $k).Value
    if ($v -ne $cible[$k]) { [pscustomobject]@{ Host=$h.Name; Setting=$k; Value=$v; Target=$cible[$k] } }
  }
}
```

### 1.4 Appliquer sur tous les hôtes (PowerCLI)

```powershell
Get-VMHost | ForEach-Object {
  Get-AdvancedSetting -Entity $_ -Name NFS.MaxVolumes    | Set-AdvancedSetting -Value 256 -Confirm:$false
  Get-AdvancedSetting -Entity $_ -Name Net.TcpipHeapSize | Set-AdvancedSetting -Value 32  -Confirm:$false
  Get-AdvancedSetting -Entity $_ -Name Net.TcpipHeapMax  | Set-AdvancedSetting -Value 512 -Confirm:$false
}
```

---

## 2. PowerCLI : lister et filtrer les datastores

```powershell
Connect-VIServer -Server vcenter.mydomain.org
```

### 2.1 Tous les datastores NFS

```powershell
Get-Datastore | Where-Object { $_.Type -like 'NFS*' } |
  Sort-Object Name |
  Select-Object Name, Type, State, Accessible, RemoteHost, RemotePath,
    @{N='NbHotes'; E={ $_.ExtensionData.Host.Count }},
    CapacityGB, FreeSpaceGB |
  Format-Table -AutoSize
```

### 2.2 Datastores inaccessibles ou indisponibles

```powershell
Get-Datastore |
  Where-Object { -not $_.Accessible -or $_.State -ne 'Available' } |
  Select-Object Name, Type, State, Accessible, RemoteHost, RemotePath
```

### 2.3 Datastores « répliques » (nom finissant par `(n)`)

```powershell
Get-Datastore | Where-Object { $_.Name -match '\(\d+\)$' } |
  Select-Object Name, State, Accessible, RemoteHost, RemotePath,
    @{N='NbHotes'; E={ $_.ExtensionData.Host.Count }}
```

### 2.4 Datastores sans aucun hôte rattaché (orphelins)

```powershell
Get-Datastore | Where-Object { $_.ExtensionData.Host.Count -eq 0 } |
  Select-Object Name, State
```

### 2.5 Hôtes rattachés à un datastore donné, avec l'état de montage

```powershell
$ds = Get-Datastore -Name 'NOM_DU_DATASTORE (10)'
$ds.ExtensionData.Host | ForEach-Object {
  [pscustomobject]@{
    Host               = (Get-VIObjectByVIView -MoRef $_.Key).Name
    Mounted            = $_.MountInfo.Mounted
    Accessible         = $_.MountInfo.Accessible
    InaccessibleReason = $_.MountInfo.InaccessibleReason
    Path               = $_.MountInfo.Path
  }
}
```

### 2.6 Comparer l'identité du datastore sain et du doublon

L'ordre des IP et les noms de serveur comptent en NFS 4.1.

```powershell
Get-Datastore -Name 'NOM_DU_DATASTORE*' | ForEach-Object {
  [pscustomobject]@{
    Name        = $_.Name
    RemotePath  = $_.RemotePath
    RemoteHosts = ($_.ExtensionData.Info.Nas.RemoteHostNames -join ',')
    Type        = $_.ExtensionData.Info.Nas.Type
    Security    = $_.ExtensionData.Info.Nas.SecurityType
    Url         = $_.ExtensionData.Info.Url
  }
}
```

### 2.7 Montages vus côté hôte (équivalent `esxcli`)

```powershell
$h = Get-VMHost 'esxi01.mydomain.org'
(Get-EsxCli -VMHost $h -V2).storage.nfs41.list.Invoke() |
  Select-Object VolumeName, Host, Share, Accessible, Mounted, Hardwareacceleration
```

### 2.8 Hôtes touchés : déconnexion/reconnexion avant tout retrait d'inventaire

```powershell
Set-VMHost -VMHost $h -State Disconnected -Confirm:$false
Set-VMHost -VMHost $h -State Connected    -Confirm:$false
```

---

## 3. Ansible

Collection requise : `community.vmware` (et `pyvmomi` sur le contrôleur).

```bash
ansible-galaxy collection install community.vmware
pip install pyvmomi
```

### 3.1 `ansible.cfg`

```ini
[defaults]
forks = 10        # >= taille du lot (serial), 5 minimum par défaut
```

### 3.2 Inventaire

```ini
[esxi]
esxi01.mydomain.org
esxi02.mydomain.org
# ...
```

### 3.3 Variables (mots de passe dans Ansible Vault)

`group_vars/all.yml` :

```yaml
vcenter_hostname: vcenter.mydomain.org
vcenter_username: "svc-ansible@vsphere.local"
vcenter_password: "{{ vault_vcenter_password }}"
vcenter_datacenter: DC_PROD
cluster_staging: CL_INST
cluster_cible: CL_PROD
nfs_advanced_options:
  NFS.MaxVolumes: 256
  Net.TcpipHeapSize: 32
  Net.TcpipHeapMax: 512
```

### 3.4 Lots de 5 hôtes en parallèle

Un play avec `serial: 5` traite les hôtes de l'inventaire par lots de 5, chaque lot en parallèle. `max_fail_percentage: 0` arrête tout le déploiement dès qu'un hôte échoue, ce qui évite de propager un problème aux lots suivants.

```yaml
- name: Paramétrage NFS des ESXi par lots de 5
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
```

Alternative : `throttle: 5` sur une tâche précise pour limiter sa concurrence sans découper tout le play.

### 3.5 Mise en maintenance

```yaml
  tasks:
    - name: Mettre l'hôte en maintenance
      community.vmware.vmware_maintenancemode:
        esxi_hostname: "{{ inventory_hostname }}"
        state: present
        evacuate: true      # évacue aussi les VM éteintes
        timeout: 3600
```

Les VM allumées sont migrées par DRS (mode entièrement automatique) ou doivent être migrées avant. Pour sortir de maintenance : même module avec `state: absent`.

### 3.6 Changement de cluster

L'hôte doit être en maintenance et rester dans le même datacenter (les dvSwitch et datastores sont des objets de niveau datacenter).

```yaml
    - name: Déplacer l'hôte vers le cluster de staging
      community.vmware.vmware_host:
        datacenter: "{{ vcenter_datacenter }}"
        cluster: "{{ cluster_staging }}"
        esxi_hostname: "{{ inventory_hostname }}"
        state: present
```

> Le comportement de `vmware_host` pour un hôte déjà présent dans un autre cluster dépend de la version de la collection : testez sur un hôte. Les paramètres `esxi_username` / `esxi_password` ne sont nécessaires que pour l'ajout initial. Solution de repli en PowerCLI :
> `Move-VMHost -VMHost $h -Destination (Get-Cluster 'CL_INST')`

### 3.7 Paramètres NFS

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

    - name: Attendre que l'hôte soit de nouveau connecté à vCenter
      community.vmware.vmware_host_facts:
        esxi_hostname: "{{ inventory_hostname }}"
      register: host_facts
      until: host_facts is succeeded
      retries: 20
      delay: 30
      when: nfs_params is changed
```

### 3.8 Remise en production

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

### 3.9 Ordre recommandé du playbook complet

1. Maintenance de l'hôte
2. Déplacement vers `CL_INST`
3. Vérification du dvSwitch et des vmkernel (réseau NFS) avant tout montage
4. Paramètres avancés NFS, puis redémarrage si nécessaire
5. Montage des datastores par sous-lots (10 à 20), avec contrôle de vCenter entre chaque lot
6. Contrôle : aucun datastore `(n)` ni inaccessible (section 2)
7. Déplacement vers le cluster cible, sortie de maintenance

---

## 4. Points de vigilance

- Les montages doivent être **strictement identiques sur tous les hôtes** : mêmes IP de la LIF dans le même ordre, même chemin d'export, même type de sécurité, même nom de datastore.
- Le dvSwitch est configuré par vCenter : un hôte sans dvSwitch ou sans vmkernel NFS fonctionnel donne des datastores inaccessibles.
- Évitez de lancer 100 montages sur 52 hôtes en même temps : étalez par lots.
- Conservez `vmkernel.log`, `vobd.log`, `hostd.log` de l'hôte et `vpxd.log` de la VCSA à l'heure d'apparition d'un doublon.
- Quand l'accès NetApp sera disponible : sessions et connexions NFSv4.1 par LIF, EMS, export-policy, `v4-id-domain`.
