# Guide de test des fonctionnalités principales de GitLab EE

Ce document décrit une procédure succincte pour tester les fonctionnalités principales de GitLab Enterprise Edition (EE), y compris Git LFS, le registre de conteneurs, les artefacts CI/CD, et les opérations Git standard. Il inclut les commandes Git et les fichiers de test nécessaires.

**Prérequis** :
- GitLab EE installé et configuré.
- Compte GitLab avec permissions Developer ou supérieur.
- Git et Git LFS installés localement.
- Docker installé pour tester le registre de conteneurs.
- Accès à l’interface GitLab et au terminal.

---

## 1. Création d’un projet de test

**Objectif** : Créer un projet pour tester les fonctionnalités.

1. **Créer un projet dans GitLab** :
   - Connectez-vous à votre instance GitLab EE.
   - Cliquez sur *New Project* > *Create blank project*.
   - Nommez le projet, par exemple, `test-project`.
   - Assurez-vous que *Initialize repository with a README* est décoché.
   - Créez le projet.

2. **Cloner le projet localement** :
   ```bash
   git clone <URL-du-projet> # Remplacez par l'URL SSH ou HTTPS du projet
   cd test-project
   ```

3. **Créer des fichiers de test** :
   - Créez un fichier texte simple :
     ```bash
     echo "Ceci est un fichier texte de test." > test.txt
     ```
   - Créez un fichier binaire volumineux pour LFS :
     ```bash
     head -c 10M /dev/urandom > large_file.bin # Crée un fichier de 10 Mo
     ```
   - Créez un fichier `.gitlab-ci.yml` pour simuler un pipeline CI :
     ```bash
     echo -e "image: alpine\nstages:\n  - test\njob1:\n  stage: test\n  script:\n    - echo 'Test CI' > artifact.txt\n  artifacts:\n    paths:\n      - artifact.txt" > .gitlab-ci.yml
     ```

---

## 2. Tester Git LFS (Large File Storage)

**Objectif** : Vérifier que Git LFS gère correctement les fichiers volumineux.

1. **Configurer Git LFS** :
   - Initialiser Git LFS dans le dépôt :
     ```bash
     git lfs install
     ```
   - Suivre les fichiers volumineux (par exemple, `.bin`) :
     ```bash
     git lfs track "*.bin"
     ```

2. **Ajouter et valider les fichiers** :
   - Ajouter le fichier `.gitattributes` généré et le fichier volumineux :
     ```bash
     git add .gitattributes large_file.bin
     git commit -m "Ajout du fichier volumineux avec LFS"
     ```

3. **Pousser vers GitLab** :
   ```bash
   git push origin main
   ```
   - Vérifiez dans l’interface GitLab que `large_file.bin` est marqué avec une icône LFS.

4. **Cloner et vérifier LFS** :
   - Clonez le dépôt dans un autre répertoire :
     ```bash
     git clone <URL-du-projet> test-project-clone
     cd test-project-clone
     git lfs pull
     ls -lh large_file.bin # Vérifiez que le fichier est téléchargé
     ```

5. **Vérification dans GitLab** :
   - Allez dans *Settings > General > Visibility, project features, permissions* et assurez-vous que *Git Large File Storage (LFS)* est activé.
   - Vérifiez que le fichier est affiché comme un objet LFS dans le dépôt.

---

## 3. Tester le registre de conteneurs (Container Registry)

**Objectif** : Vérifier que le registre peut stocker et gérer des images Docker.

1. **Activer le registre** :
   - Dans *Settings > General > Visibility, project features, permissions*, assurez-vous que *Container Registry* est activé.

2. **Créer une image Docker de test** :
   - Créez un fichier `Dockerfile` :
     ```bash
     echo -e "FROM alpine\nCMD echo 'Hello from test image'" > Dockerfile
     ```
   - Ajoutez et validez :
     ```bash
     git add Dockerfile
     git commit -m "Ajout du Dockerfile pour le registre"
     ```

3. **Construire et pousser une image** :
   - Connectez-vous au registre GitLab :
     ```bash
     docker login <votre-domaine-gitlab>:5050 -u <votre-utilisateur> -p <votre-mot-de-passe-ou-token>
     ```
   - Construisez et taguez l’image :
     ```bash
     docker build -t <votre-domaine-gitlab>:5050/<groupe>/<projet>/test-image:latest .
     ```
   - Poussez l’image :
     ```bash
     docker push <votre-domaine-gitlab>:5050/<groupe>/<projet>/test-image:latest
     ```

4. **Vérifier dans GitLab** :
   - Allez dans *Deploy > Container Registry* dans GitLab.
   - Confirmez que l’image `test-image:latest` est visible.

5. **Tester le téléchargement** :
   - Supprimez l’image localement :
     ```bash
     docker rmi <votre-domaine-gitlab>:5050/<groupe>/<projet>/test-image:latest
     ```
   - Téléchargez l’image depuis le registre :
     ```bash
     docker pull <votre-domaine-gitlab>:5050/<groupe>/<projet>/test-image:latest
     ```

---

## 4. Tester les artefacts CI/CD

**Objectif** : Vérifier que les artefacts sont générés et accessibles via un pipeline.

1. **Configurer le pipeline** :
   - Le fichier `.gitlab-ci.yml` créé précédemment définit un job qui génère un artefact (`artifact.txt`).
   - Ajoutez et poussez le fichier CI :
     ```bash
     git add .gitlab-ci.yml
     git commit -m "Ajout du fichier CI pour tester les artefacts"
     git push origin main
     ```

2. **Vérifier l’exécution du pipeline** :
   - Allez dans *CI/CD > Pipelines* dans GitLab.
   - Confirmez que le pipeline s’exécute et que le job `job1` réussit.

3. **Télécharger les artefacts** :
   - Dans l’interface du pipeline, cliquez sur le job `job1`.
   - Téléchargez l’artefact `artifact.txt` via le bouton *Download artifacts*.
   - Vérifiez le contenu :
     ```bash
     cat artifact.txt # Devrait afficher "Test CI"
     ```

4. **Vérifier les artefacts dans GitLab** :
   - Allez dans *CI/CD > Jobs* et confirmez que l’artefact est listé.

---

## 5. Tester les fonctionnalités de base de Git

**Objectif** : Vérifier les opérations Git standard.