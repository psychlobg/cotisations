# Procédure Ansible – Mise à jour d’un GitLab Runner (EE) sur Debian

## Objectif

Mettre à jour un GitLab Runner de façon sécurisée :

- un runner à la fois (`serial: 1`)
- mise en pause + attente de la fin des jobs en cours
- mise à jour de la clé GPG du dépôt
- `apt update` + `upgrade`
- redémarrage du service
- réactivation du runner

---

## Playbook

```yaml
---
# playbook-update-gitlab-runner.yml
# Usage :
#   ansible-playbook -i inventory playbook-update-gitlab-runner.yml \
#     -e gitlab_url=https://gitlab.example.com \
#     -e gitlab_token=glpat-xxxxxxxx \
#     -e runner_id=42

- name: Mise à jour GitLab Runner (un par un)
  hosts: gitlab_runners
  become: true
  serial: 1                    # ← un runner à la fois
  any_errors_fatal: true

  vars:
    gitlab_url: "https://gitlab.example.com"   # à surcharger
    gitlab_token: ""                           # token avec scope manage_runner / api
    runner_id: ""                              # ID numérique du runner dans GitLab
    gpg_key_url: "https://packages.gitlab.com/runner/gitlab-runner/gpgkey/runner-gitlab-runner-49F16C5CC3A0F81F.pub.gpg"
    keyring_path: "/usr/share/keyrings/runner_gitlab-runner-archive-keyring.gpg"
    # ou /etc/apt/keyrings/runner_gitlab-runner-archive-keyring.gpg selon ton installation
    wait_timeout: 3600         # timeout max en secondes pour attendre la fin des jobs
    wait_delay: 30             # intervalle de polling

  tasks:

    # -------------------------------------------------------
    # 1. Vérifications préalables
    # -------------------------------------------------------
    - name: Vérifier que gitlab-runner est installé
      ansible.builtin.command: which gitlab-runner
      register: runner_bin
      changed_when: false
      failed_when: runner_bin.rc != 0

    - name: Afficher la version actuelle
      ansible.builtin.command: gitlab-runner --version
      register: current_version
      changed_when: false

    - name: Afficher version
      ansible.builtin.debug:
        msg: "Version actuelle → {{ current_version.stdout_lines[0] | default(current_version.stdout) }}"

    # -------------------------------------------------------
    # 2. Mettre le runner en pause via l'API GitLab
    # -------------------------------------------------------
    - name: Mettre le runner en pause (API)
      ansible.builtin.uri:
        url: "{{ gitlab_url }}/api/v4/runners/{{ runner_id }}"
        method: PUT
        headers:
          PRIVATE-TOKEN: "{{ gitlab_token }}"
        body_format: form-urlencoded
        body:
          paused: "true"
        status_code: 200
      register: pause_result
      when: runner_id | length > 0 and gitlab_token | length > 0

    - name: Confirmer la pause
      ansible.builtin.debug:
        msg: "Runner {{ runner_id }} mis en pause"

    # -------------------------------------------------------
    # 3. Attendre la fin des jobs en cours
    # -------------------------------------------------------
    - name: Attendre que tous les jobs soient terminés
      ansible.builtin.uri:
        url: "{{ gitlab_url }}/api/v4/runners/{{ runner_id }}/jobs?status=running"
        method: GET
        headers:
          PRIVATE-TOKEN: "{{ gitlab_token }}"
        status_code: 200
      register: running_jobs
      until: running_jobs.json | length == 0
      retries: "{{ (wait_timeout / wait_delay) | int }}"
      delay: "{{ wait_delay }}"
      when: runner_id | length > 0 and gitlab_token | length > 0

    - name: Afficher le statut d'attente
      ansible.builtin.debug:
        msg: "Aucun job en cours sur le runner {{ runner_id }}"

    # -------------------------------------------------------
    # 4. Mise à jour de la clé GPG du dépôt GitLab Runner
    # -------------------------------------------------------
    - name: Créer le répertoire keyrings si nécessaire
      ansible.builtin.file:
        path: "{{ keyring_path | dirname }}"
        state: directory
        mode: "0755"

    - name: Télécharger la nouvelle clé GPG
      ansible.builtin.get_url:
        url: "{{ gpg_key_url }}"
        dest: "/tmp/runner-gitlab-runner.pub.gpg"
        mode: "0644"
        force: true

    - name: Convertir et installer la clé GPG (dearmor)
      ansible.builtin.shell: |
        gpg --dearmor < /tmp/runner-gitlab-runner.pub.gpg > {{ keyring_path }}
      args:
        creates: "{{ keyring_path }}"
      changed_when: true

    - name: Forcer la mise à jour de la clé
      ansible.builtin.shell: |
        gpg --dearmor < /tmp/runner-gitlab-runner.pub.gpg > {{ keyring_path }}
      changed_when: true

    - name: Vérifier les permissions de la clé
      ansible.builtin.file:
        path: "{{ keyring_path }}"
        mode: "0644"
        owner: root
        group: root

    # Optionnel : nettoyer l'ancienne clé dans trusted.gpg si elle existe
    - name: Supprimer l'ancienne clé apt-key (si présente)
      ansible.builtin.command: apt-key del 3F01618A51312F3F
      register: aptkey_del
      failed_when: false
      changed_when: aptkey_del.rc == 0

    # -------------------------------------------------------
    # 5. Update + Upgrade système + gitlab-runner
    # -------------------------------------------------------
    - name: apt update
      ansible.builtin.apt:
        update_cache: true
        cache_valid_time: 0

    - name: Upgrade complet du système (recommandé)
      ansible.builtin.apt:
        upgrade: dist          # ou "safe" selon ta politique
        autoremove: true
        autoclean: true

    # Variante : upgrade uniquement du package runner
    # - name: Upgrade gitlab-runner uniquement
    #   ansible.builtin.apt:
    #     name: gitlab-runner
    #     state: latest

    - name: Afficher la nouvelle version
      ansible.builtin.command: gitlab-runner --version
      register: new_version
      changed_when: false

    - name: Version après upgrade
      ansible.builtin.debug:
        msg: "Nouvelle version → {{ new_version.stdout_lines[0] | default(new_version.stdout) }}"

    # -------------------------------------------------------
    # 6. Redémarrer le service (propre)
    # -------------------------------------------------------
    - name: Redémarrer le service gitlab-runner
      ansible.builtin.systemd:
        name: gitlab-runner
        state: restarted
        enabled: true
        daemon_reload: true

    - name: Attendre que le service soit actif
      ansible.builtin.systemd:
        name: gitlab-runner
      register: service_status
      until: service_status.status.ActiveState == "active"
      retries: 10
      delay: 3

    # -------------------------------------------------------
    # 7. Réactiver le runner
    # -------------------------------------------------------
    - name: Réactiver le runner (API)
      ansible.builtin.uri:
        url: "{{ gitlab_url }}/api/v4/runners/{{ runner_id }}"
        method: PUT
        headers:
          PRIVATE-TOKEN: "{{ gitlab_token }}"
        body_format: form-urlencoded
        body:
          paused: "false"
        status_code: 200
      when: runner_id | length > 0 and gitlab_token | length > 0

    - name: Vérifier que le runner est bien online
      ansible.builtin.command: gitlab-runner verify
      register: verify
      changed_when: false
      failed_when: "'is alive' not in verify.stdout and 'is alive' not in verify.stderr"

    - name: Fin de la procédure
      ansible.builtin.debug:
        msg: |
          ✅ Runner {{ inventory_hostname }} mis à jour avec succès.
          Version : {{ new_version.stdout_lines[0] | default(new_version.stdout) }}
```

---

## Inventory d’exemple

```ini
[gitlab_runners]
runner01 ansible_host=10.0.0.11 runner_id=42
runner02 ansible_host=10.0.0.12 runner_id=43
runner03 ansible_host=10.0.0.13 runner_id=44
```

---

## Lancement

```bash
ansible-playbook -i inventory playbook-update-gitlab-runner.yml \
  -e gitlab_url=https://gitlab.example.com \
  -e gitlab_token=glpat-xxxxxxxxxxxxxxxxxxxx \
  --limit runner01
```

---

## Récapitulatif des étapes

| Étape | Action |
|-------|--------|
| `serial: 1` | Un seul runner traité à la fois |
| Pause API | Le runner n’accepte plus de nouveaux jobs |
| Attente jobs | Polling de l’API `/runners/:id/jobs?status=running` |
| Clé GPG | Téléchargement de la clé `49F16C5CC3A0F81F` et installation dans le keyring |
| Upgrade | `apt upgrade dist` (ou uniquement `gitlab-runner`) |
| Restart | Redémarrage propre du service systemd |
| Resume | Réactivation via l’API |

---

## Variante sans API (graceful shutdown)

Si tu n’as pas de token API, remplace les étapes de pause / attente / resume par :

```yaml
- name: Arrêt gracieux (SIGQUIT)
  ansible.builtin.shell: |
    systemctl kill -s SIGQUIT gitlab-runner
    timeout {{ wait_timeout }} bash -c 'while pgrep -f "gitlab-runner run" > /dev/null; do sleep 10; done'
  ignore_errors: true
```

Puis redémarre le service après l’upgrade.
```
