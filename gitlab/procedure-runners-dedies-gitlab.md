# Procédure : Création et affectation de runners dédiés multi-projets (GitLab Self-Hosted)

## Objectif

Créer un **project runner** dédié pour un développeur, l’associer dynamiquement à plusieurs de ses projets (en récupérant les IDs via l’API), le taguer avec le nom de chaque projet, puis le verrouiller.

Le tout en tant qu’**administrateur d’instance**.

---

## Prérequis

- Compte **administrateur** de l’instance GitLab
- Personal Access Token admin avec les scopes :
  - `api`
  - `create_runner`
  - `manage_runner`
- Collection Ansible : `community.general`
- Python module `python-gitlab` (installé sur la machine qui exécute le playbook)

```bash
ansible-galaxy collection install community.general
pip install python-gitlab
```

---

## Variables à préparer

Exemple de structure d’entrée (fichier `vars.yml` ou extra-vars) :

```yaml
gitlab_url: "https://gitlab.example.com"
gitlab_token: "glpat-xxxxxxxxxxxxxxxxxxxx"   # Token admin

# Liste des projets (path complet ou nom)
projects:
  - path: "groupe/jean/projet-a"
  - path: "groupe/jean/projet-b"
  - path: "groupe/jean/projet-c"

runner_description: "Runner dédié Jean"
run_untagged: true
```

---

## Playbook Ansible complet

Fichier : `create_dedicated_runner.yml`

```yaml
---
- name: Créer un runner dédié et l'affecter dynamiquement à plusieurs projets
  hosts: localhost
  gather_facts: false

  vars:
    gitlab_url: "https://gitlab.example.com"
    gitlab_token: "{{ vault_gitlab_token | default(lookup('env', 'GITLAB_TOKEN')) }}"
    runner_description: "Runner dédié Jean"
    run_untagged: true

    # Liste des projets (chemin complet group/subgroup/project)
    projects:
      - path: "groupe/jean/projet-a"
      - path: "groupe/jean/projet-b"
      - path: "groupe/jean/projet-c"

  tasks:
    # -------------------------------------------------
    # 1. Récupérer dynamiquement les IDs des projets
    # -------------------------------------------------
    - name: Récupérer les informations des projets
      ansible.builtin.uri:
        url: "{{ gitlab_url }}/api/v4/projects/{{ item.path | urlencode }}"
        method: GET
        headers:
          PRIVATE-TOKEN: "{{ gitlab_token }}"
        status_code: 200
      loop: "{{ projects }}"
      loop_control:
        label: "{{ item.path }}"
      register: projects_info

    - name: Construire la liste des projets avec ID + nom
      ansible.builtin.set_fact:
        projects_resolved: >-
          {{
            projects_resolved | default([]) + [{
              'id': item.json.id,
              'name': item.json.name,
              'path': item.json.path_with_namespace
            }]
          }}
      loop: "{{ projects_info.results }}"
      when: item.json is defined

    - name: Afficher les projets résolus
      ansible.builtin.debug:
        var: projects_resolved

    # -------------------------------------------------
    # 2. Créer le runner sur le premier projet
    # -------------------------------------------------
    - name: Créer le project runner (premier projet = owner)
      community.general.gitlab_runner:
        api_url: "{{ gitlab_url }}"
        api_token: "{{ gitlab_token }}"
        description: "{{ runner_description }}"
        project: "{{ projects_resolved[0].id }}"
        state: present
        locked: false
        run_untagged: "{{ run_untagged }}"
        tag_list:
          - "{{ projects_resolved[0].name | lower | regex_replace('[^a-z0-9]', '-') }}"
      register: runner_creation

    - name: Afficher les informations du runner créé
      ansible.builtin.debug:
        msg:
          - "Runner ID        : {{ runner_creation.runner.id }}"
          - "Auth Token       : {{ runner_creation.runner.token }}"
          - "Projet propriétaire : {{ projects_resolved[0].path }}"
          - "→ Utilisez le token ci-dessus pour enregistrer le runner physique"

    # -------------------------------------------------
    # 3. Affecter le runner aux autres projets
    # -------------------------------------------------
    - name: Affecter le runner aux projets restants
      ansible.builtin.uri:
        url: "{{ gitlab_url }}/api/v4/projects/{{ item.id }}/runners"
        method: POST
        headers:
          PRIVATE-TOKEN: "{{ gitlab_token }}"
        body_format: form-urlencoded
        body:
          runner_id: "{{ runner_creation.runner.id }}"
        status_code: [201, 409]   # 409 = déjà présent (idempotent)
      loop: "{{ projects_resolved[1:] }}"
      loop_control:
        label: "{{ item.path }}"
      when: projects_resolved | length > 1

    # -------------------------------------------------
    # 4. Mettre à jour les tags avec TOUS les noms de projets
    # -------------------------------------------------
    - name: Mettre à jour les tags du runner (noms de tous les projets)
      community.general.gitlab_runner:
        api_url: "{{ gitlab_url }}"
        api_token: "{{ gitlab_token }}"
        description: "{{ runner_description }}"
        project: "{{ projects_resolved[0].id }}"
        state: present
        locked: false
        run_untagged: "{{ run_untagged }}"
        tag_list: >-
          {{
            projects_resolved
            | map(attribute='name')
            | map('lower')
            | map('regex_replace', '[^a-z0-9]', '-')
            | list
          }}

    # -------------------------------------------------
    # 5. Verrouiller le runner
    # -------------------------------------------------
    - name: Verrouiller le runner (empêche toute nouvelle affectation)
      community.general.gitlab_runner:
        api_url: "{{ gitlab_url }}"
        api_token: "{{ gitlab_token }}"
        description: "{{ runner_description }}"
        project: "{{ projects_resolved[0].id }}"
        state: present
        locked: true
        run_untagged: "{{ run_untagged }}"
        tag_list: >-
          {{
            projects_resolved
            | map(attribute='name')
            | map('lower')
            | map('regex_replace', '[^a-z0-9]', '-')
            | list
          }}

    - name: Résumé final
      ansible.builtin.debug:
        msg:
          - "=============================================="
          - "Runner créé et verrouillé avec succès"
          - "ID          : {{ runner_creation.runner.id }}"
          - "Description : {{ runner_description }}"
          - "Tags        : {{ projects_resolved | map(attribute='name') | list }}"
          - "Projets     :"
          - "{{ projects_resolved | map(attribute='path') | list }}"
          - "=============================================="
          - "Token d'authentification (à utiliser pour gitlab-runner register) :"
          - "{{ runner_creation.runner.token }}"
```

---

## Exécution

```bash
# Avec un fichier de variables
ansible-playbook create_dedicated_runner.yml -e @vars.yml

# Ou avec un vault
ansible-playbook create_dedicated_runner.yml --ask-vault-pass

# Ou en passant le token en variable d'environnement
export GITLAB_TOKEN="glpat-xxxxxxxx"
ansible-playbook create_dedicated_runner.yml
```

---

## Enregistrement du runner physique

Sur la machine qui hébergera le runner :

```bash
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com" \
  --token "<token_affiché_par_le_playbook>" \
  --executor "docker" \
  --docker-image "alpine:latest" \
  --description "Runner dédié Jean"
```

---

## Notes importantes

1. **Premier projet = owner project**  
   Le runner appartient au premier projet de la liste. On ne peut pas le retirer de ce projet.

2. **Tags**  
   Les tags sont générés automatiquement à partir des noms des projets (minuscules + caractères spéciaux remplacés par `-`).

3. **Idempotence**  
   Le playbook peut être relancé sans problème.  
   - Si le runner existe déjà → il est mis à jour.  
   - Si déjà assigné à un projet → code 409 ignoré.

4. **Sécurité**  
   Une fois `locked: true`, même un Maintainer ne peut plus ajouter le runner à d’autres projets.

5. **Admin**  
   Grâce au token admin, vous n’avez pas besoin d’être membre des projets des utilisateurs.

---

## Extension possible

Pour gérer plusieurs développeurs en une seule exécution, transformez la variable `projects` en une structure plus complexe :

```yaml
developers:
  - name: "Jean"
    projects:
      - "groupe/jean/projet-a"
      - "groupe/jean/projet-b"
  - name: "Marie"
    projects:
      - "groupe/marie/app-frontend"
      - "groupe/marie/app-backend"
```

Puis bouclez sur `developers`.
