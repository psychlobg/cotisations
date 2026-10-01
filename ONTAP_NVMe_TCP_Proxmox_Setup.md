# Configuration NVMe/TCP NetApp ONTAP 9.16 pour Cluster Proxmox VE via Ansible

Ce guide fournit une automatisation complète via Ansible pour la mise en place d'un stockage **NVMe/TCP** sous **NetApp ONTAP 9.16** dédié à un cluster **Proxmox VE**, ainsi que la documentation technique des choix d'architecture.

---

## 1. Architecture & Principes Fondamentaux

### Parallèle entre iSCSI et NVMe/TCP

| Notion iSCSI | Équivalent NVMe-oF / TCP | Description |
| :--- | :--- | :--- |
| **LUN** | **Namespace** | Espace de stockage block présenté à l'hôte. |
| **Igroup** | **Subsystem** | Groupe de contrôle d'accès associant les hôtes aux namespaces. |
| **IQN** | **NQN** (*NVMe Qualified Name*) | Identifiant unique du client (ex: nœud Proxmox). |
| **Target iSCSI / Portal** | **Subsystem + LIF NVMe** | Point de terminaison réseau et protocole d'écoute IP. |

### Provisioning, Elasticité & Discard (TRIM/UNMAP)

#### Volume vs Namespace
* **Volume FlexVol :** Conteneur ONTAP élastique (`space_guarantee: none` pour le Thin Provisioning). Il est configuré en **Autogrow** avec un surdimensionnement de **+10% à +15%** par rapport au Namespace afin d'absorber les métadonnées internes ONTAP.
* **Namespace NVMe :** Unité block de taille fixe vue par Proxmox. L'autogrow ne s'applique pas au Namespace car il présente une géométrie de disque fixe à l'OS. En cas de besoin d'extension, la taille du Namespace est augmentée via Ansible, puis réenclenchée côté Proxmox (`nvme rescan` et `pvresize`).

#### Spécificités du paramètre `discard` (Libération d'espace)
Pour éviter qu'un datastore Thin-Provisioned ne se remplisse définitivement sans jamais libérer l'espace supprimé par les machines virtuelles, le mécanisme de **TRIM/UNMAP** (`discard`) doit être activé bout-en-bout :

1. **Côté Guest OS (VM) :** Activer l'option `Discard` sur le disque virtuel VirtIO SCSI dans Proxmox.
2. **Côté Proxmox VE (LVM-Thin / Storage) :**
   * Pour un Thin Pool LVM, s'assurer que le paramètre `discards` est réglé sur `passdown`.
   * Pour un point de montage de système de fichiers (ex: ext4/xfs), utiliser l'option de montage `discard` ou exécuter périodiquement `fstrim`.
3. **Côté ONTAP 9.16 :** L'`ostype: linux` sur le Namespace permet au contrôleur ONTAP de traiter nativement les requêtes SCSI UNMAP / NVMe Dataset Management (DSM) Deallocate transmises par Proxmox et d'immédiatement réattribuer les blocs libérés à l'agrégat All-Flash.

---

## 2. Playbook Ansible Complet (`deploy_nvme_tcp.yml`)

### Prérequis
* Collection Ansible : `netapp.ontap` (v22.x ou supérieure recommandée pour ONTAP 9.16)
* Dépendances Python sur la machine d'exécution : `pip install requests netapp-lib`

```yaml
---
- name: Configuration NVMe/TCP sur NetApp ONTAP 9.16 pour Proxmox VE
  hosts: localhost
  gather_facts: false
  vars:
    # Information d'accès au Cluster NetApp
    netapp_hostname: "192.168.1.100"
    netapp_username: "admin"
    netapp_password: "YourSecurePassword"
    validate_certs: false

    # Paramètres de la SVM & Réseau
    svm_name: "svm_nvme_tcp"
    aggregate_name: "aggr1_nvme"
    vserver_root_volume: "svm_nvme_tcp_root"
    home_node: "node-01"
    home_port: "e0c"
    lif_name_1: "lif_nvme_tcp_01"
    lif_ip_1: "192.168.10.50"
    lif_netmask: "255.255.255.0"

    # Export Policy
    export_policy_name: "pol_nvme_proxmox"
    client_subnet: "192.168.10.0/24"

    # Volume & Namespace (Dimensions)
    volume_name: "vol_proxmox_ds01"
    volume_size_gb: 1100         # 1.1 TB (+10% overhead pour métadonnées)
    volume_max_size_gb: 1500     # Plafond Autogrow FlexVol
    namespace_name: "/vol/vol_proxmox_ds01/ns_proxmox_01"
    namespace_size_gb: 1000      # 1 TB utilisable pour Proxmox VE

    # Proxmox NQN & Subsystem
    subsystem_name: "subsys_proxmox_cluster"
    proxmox_nqns:
      - "nqn.2014-08.org.nvmexpress:uuid:f81d4fae-7dec-11d0-a765-00a0c91e6bf6" # Nœud Proxmox 1
      - "nqn.2014-08.org.nvmexpress:uuid:a12b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d" # Nœud Proxmox 2

  tasks:

    # ------------------------------------------------------------------
    # 1. CRÉATION SVM & SERVICE NVME
    # ------------------------------------------------------------------
    - name: Créer la Storage Virtual Machine (SVM)
      netapp.ontap.na_ontap_svm:
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
        validate_certs: "{{ validate_certs }}"
        state: present
        vserver: "{{ svm_name }}"
        aggr_list: ["{{ aggregate_name }}"]
        root_volume: "{{ vserver_root_volume }}"
        root_volume_aggregate: "{{ aggregate_name }}"

    - name: Activer le service protocole NVMe sur la SVM
      netapp.ontap.na_ontap_nvme:
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
        validate_certs: "{{ validate_certs }}"
        state: present
        vserver: "{{ svm_name }}"
        status: "up"

    - name: Créer la LIF NVMe/TCP
      netapp.ontap.na_ontap_interface:
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
        validate_certs: "{{ validate_certs }}"
        state: present
        vserver: "{{ svm_name }}"
        interface_name: "{{ lif_name_1 }}"
        role: data
        data_protocols:
          - nvme
        home_node: "{{ home_node }}"
        home_port: "{{ home_port }}"
        address: "{{ lif_ip_1 }}"
        netmask: "{{ lif_netmask }}"

    # ------------------------------------------------------------------
    # 2. EXPORT POLICY (Gestion des accès)
    # ------------------------------------------------------------------
    - name: Créer la Export Policy
      netapp.ontap.na_ontap_export_policy:
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
        validate_certs: "{{ validate_certs }}"
        state: present
        vserver: "{{ svm_name }}"
        name: "{{ export_policy_name }}"

    - name: Définir la règle de sécurité pour le sous-réseau Proxmox
      netapp.ontap.na_ontap_export_policy_rule:
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
        validate_certs: "{{ validate_certs }}"
        state: present
        vserver: "{{ svm_name }}"
        policy_name: "{{ export_policy_name }}"
        client_match: "{{ client_subnet }}"
        ro_rule: any
        rw_rule: any
        protocol: any
        super_user_security: any

    # ------------------------------------------------------------------
    # 3. VOLUME FLEXVOL & NAMESPACE NVME
    # ------------------------------------------------------------------
    - name: Créer le Volume FlexVol (Thin Provisioned avec Autogrow)
      netapp.ontap.na_ontap_volume:
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
        validate_certs: "{{ validate_certs }}"
        state: present
        vserver: "{{ svm_name }}"
        name: "{{ volume_name }}"
        aggregate_name: "{{ aggregate_name }}"
        size: "{{ volume_size_gb }}"
        size_unit: "g"
        space_guarantee: "none" # Thin Provisioning
        policy: "{{ export_policy_name }}"
        vol_attributes:
          space_extra_attributes:
            space_allocation: "true"
            auto_grow_default: "true"
            max_size: "{{ volume_max_size_gb }}"
            increase_by: "10%"

    - name: Créer le Namespace NVMe (Format Block Linux pour Proxmox)
      netapp.ontap.na_ontap_nvme_namespace:
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
        validate_certs: "{{ validate_certs }}"
        state: present
        vserver: "{{ svm_name }}"
        path: "{{ namespace_name }}"
        size: "{{ namespace_size_gb }}"
        size_unit: "g"
        ostype: "linux" # Indispensable pour la gestion efficace des TRIM/UNMAP avec Proxmox

    # ------------------------------------------------------------------
    # 4. NVME SUBSYSTEM & HOST MAPPING (NQN)
    # ------------------------------------------------------------------
    - name: Créer le NVMe Subsystem, ajouter les NQN Proxmox et associer le Namespace
      netapp.ontap.na_ontap_nvme_subsystem:
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
        validate_certs: "{{ validate_certs }}"
        state: present
        vserver: "{{ svm_name }}"
        subsystem: "{{ subsystem_name }}"
        ostype: "linux"
        hosts: "{{ proxmox_nqns }}"
        paths:
          - "{{ namespace_name }}"
```

---

## 3. Commandes de Connexion Côté Hôte Proxmox VE

Une fois le Playbook Ansible exécuté, voici les commandes CLI à exécuter sur chaque nœud Proxmox pour initialiser et joindre le Namespace NVMe/TCP.

1. **Installer les outils NVMe CLI :**
   ```bash
   apt-get update && apt-get install -y nvme-cli
   ```

2. **Récupérer le NQN local du nœud Proxmox (à renseigner dans le Playbook) :**
   ```bash
   cat /etc/nvme/hostnqn
   ```

3. **Découvrir les targets NVMe/TCP proposées par la SVM ONTAP :**
   ```bash
   nvme discover -t tcp -a 192.168.10.50 -s 8009
   ```

4. **Se connecter à la Target NVMe/TCP :**
   ```bash
   nvme connect-all -t tcp -a 192.168.10.50 -s 8009
   ```

5. **Vérifier l'état du Namespace NVMe et créer le stockage Proxmox :**
   ```bash
   nvme list
   # Exemple de disque retourné : /dev/nvme0n1

   # Initialisation LVM Physical Volume
   pvcreate /dev/nvme0n1
   vgcreate vg_nvme_ontap /dev/nvme0n1
   ```