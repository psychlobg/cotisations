# Authentification Apache via Kerberos/SPNEGO (AD) — Procédure complète

## Contexte

- Serveur web Apache sur Debian
- Authentification des utilisateurs du domaine AD via Kerberos/SPNEGO (Negotiate)
- Keytab existant, portant le SPN `HTTP/fqdn`, généré sur un compte de service AD
- Objectif : SSO natif (poste Windows joint au domaine), tous les utilisateurs du domaine, sans restriction de groupe, **sans bind LDAP**

---

## 1. Prérequis système

```bash
apt update
apt install libapache2-mod-auth-gssapi krb5-user
```

Configurer `/etc/krb5.conf` :

```ini
[libdefaults]
    default_realm = MONDOMAINE.LOCAL
    dns_lookup_realm = true
    dns_lookup_kdc = true

[realms]
    MONDOMAINE.LOCAL = {
        kdc = dc1.mondomaine.local
        admin_server = dc1.mondomaine.local
    }

[domain_realm]
    .mondomaine.local = MONDOMAINE.LOCAL
    mondomaine.local = MONDOMAINE.LOCAL
```

> Le realm doit être en **majuscules**. Vérifier aussi la synchronisation horaire (`chronyc tracking` / `timedatectl`) : Kerberos tolère un écart d'environ 5 minutes par défaut.

---

## 2. Déploiement du keytab

```bash
cp http.keytab /etc/apache2/http.keytab
chown www-data:www-data /etc/apache2/http.keytab
chmod 600 /etc/apache2/http.keytab
```

---

## 3. Configuration Apache

```apache
<Location /secure>
    AuthType GSSAPI
    AuthName "Authentification AD"
    GssapiCredStore keytab:/etc/apache2/http.keytab
    GssapiLocalName On
    Require valid-user
</Location>
```

- **Aucun LDAP ici** : le flux est purement Kerberos. Le client obtient un ticket de service auprès du KDC, l'envoie à Apache dans l'en-tête `Authorization: Negotiate`, et Apache le déchiffre avec la clé du keytab. `REMOTE_USER` est extrait directement du ticket.
- `Require valid-user` = tout utilisateur du domaine avec un ticket valide est accepté (pas de filtrage par groupe).
- `GssapiLocalName On` retire le suffixe `@REALM` du nom d'utilisateur exposé à Apache.

Activer et recharger :

```bash
a2enmod auth_gssapi
apachectl configtest
systemctl reload apache2
```

---

## 4. SSO côté poste Windows

Prérequis AD/DNS :
- Le fqdn du site doit résoudre en DNS vers l'IP du serveur Apache.
- Le SPN doit être **unique**, enregistré uniquement sur le compte de service (sinon erreur `KRB_AP_ERR_MODIFIED`) :
  ```powershell
  setspn -Q HTTP/fqdn
  ```
  → doit renvoyer une seule ligne, pointant vers le bon compte.

Configuration navigateur :
- **IE / Edge legacy** : site dans la zone "Intranet local" ou "Sites de confiance".
- **Chrome / Edge Chromium** : via GPO `AuthServerAllowlist`, ou paramètres IE/zones.
- **Firefox** : `about:config` → `network.negotiate-auth.trusted-uris` → ajouter le fqdn (ou via `policies.json`/GPO).

Avec une session Windows ouverte sur un compte du domaine et la config ci-dessus, l'authentification est transparente (SSO) : aucune saisie de login/mot de passe.

---

## 5. Vérifier que le keytab est valide

### a) Structure du fichier (offline)

```bash
klist -kt /etc/apache2/http.keytab
```

À vérifier :
- Principal exact : `HTTP/fqdn@REALM` (realm en majuscules, fqdn sans erreur de casse/espace)
- KVNO (Key Version Number) : doit correspondre à la version actuelle du mot de passe du compte AD
- Plusieurs lignes normales (une par type de chiffrement : AES256, AES128, RC4...)

Pour voir le détail des types de chiffrement :
```bash
klist -kte /etc/apache2/http.keytab
```

### b) Comparer le KVNO avec AD

```powershell
Get-ADUser -Identity nomducompteservice -Properties msDS-KeyVersionNumber
```

Si le KVNO diffère de celui du keytab → keytab périmé (mot de passe changé depuis) → à régénérer.

### c) Test réel du keytab avec `kvno` (⚠️ ne pas utiliser `kinit -kt` sur un SPN)

**Piège classique** : `kinit -kt /etc/apache2/http.keytab HTTP/fqdn@MONDOMAINE.LOCAL` échoue avec `not found in Kerberos database`. C'est normal : `kinit` fait une requête AS-REQ, qui ne fonctionne que sur un **compte réel** (sAMAccountName/UPN), pas sur un SPN. Le SPN n'est résolvable que lors d'une requête TGS (ticket de service), pas lors de l'authentification initiale.

**Bon outil : `kvno`**, qui simule exactement ce que fait Apache.

Étape 1 — obtenir un TGT avec un compte utilisateur normal du domaine :
```bash
kinit toncompte@MONDOMAINE.LOCAL
klist
```

Étape 2 — demander un ticket de service pour le SPN et le déchiffrer avec le keytab :
```bash
kvno -k /etc/apache2/http.keytab HTTP/fqdn@MONDOMAINE.LOCAL
```

**Succès attendu :**
```
HTTP/fqdn@MONDOMAINE.LOCAL: kvno = 3
```

**Erreurs possibles :**

| Erreur | Cause | Action |
|---|---|---|
| `Server not found in Kerberos database` | SPN mal enregistré ou absent côté AD | Vérifier avec `setspn -Q HTTP/fqdn` |
| `Decrypt integrity check failed` | Keytab périmé (mot de passe du compte changé depuis) | Comparer les KVNO (klist vs AD), régénérer le keytab si besoin |
| `Preauthentication failed` (à l'étape 1) | Problème avec le compte utilisateur de test, pas lié au keytab | Vérifier le compte/mot de passe utilisé pour `kinit` |

---

## 6. Tests fonctionnels end-to-end

### a) Apache exige bien l'authentification

```bash
curl -v https://fqdn/secure/
```
→ Doit renvoyer `401 Unauthorized` avec l'en-tête `WWW-Authenticate: Negotiate`.

### b) Authentification SPNEGO complète (ligne de commande)

```bash
kinit toncompte@MONDOMAINE.LOCAL
curl -v --negotiate -u : https://fqdn/secure/
```
→ Doit renvoyer `200 OK` avec le contenu de la page.

### c) Vérification du user transmis à l'application

Ajouter temporairement une page de test affichant `REMOTE_USER` / `$_SERVER['REMOTE_USER']` pour confirmer le mapping utilisateur.

### d) Test navigateur (SSO réel)

Depuis un poste Windows joint au domaine, avec la config navigateur du point 4 : accéder au site, aucune invite ne doit apparaître, la page doit s'afficher directement.

### e) Debug en cas d'échec

```apache
LogLevel auth_gssapi:trace8
```
```bash
tail -f /var/log/apache2/error.log
```

Points de vigilance fréquents :
- Désynchronisation horaire avec le DC
- Résolution DNS incorrecte
- Realm mal casé (doit être en MAJUSCULES)
- SPN dupliqué sur plusieurs comptes AD

---

## Résumé des tests

| Test | Commande | Valide quoi |
|---|---|---|
| Structure du keytab | `klist -kt /etc/apache2/http.keytab` | Principal, KVNO du fichier |
| Synchronisation AD | `Get-ADUser ... msDS-KeyVersionNumber` | KVNO à jour côté AD |
| Validité fonctionnelle du keytab | `kvno -k keytab HTTP/fqdn@REALM` | SPN correct + clé correcte + communication KDC |
| Apache exige l'auth | `curl -v https://fqdn/secure/` | Configuration `mod_auth_gssapi` active |
| Auth complète (CLI) | `kinit` + `curl --negotiate` | Chaîne complète client → KDC → Apache |
| SSO réel | Navigateur sur poste Windows | Expérience utilisateur finale |


Pourquoi kinit -kt ... HTTP/fqdn échoue avec "not found in Kerberos database"

kinit fait une requête AS-REQ (demande de TGT initial) auprès du KDC. Or, un KDC Active Directory ne peut faire de l'AS-REQ que pour un compte réel (identifié par son sAMAccountName ou son userPrincipalName), pas pour un SPN brut.

Le SPN HTTP/fqdn n'est qu'un attribut (servicePrincipalName) posé sur ton compte de service — ce n'est pas un objet de compte à part entière. Il n'est résolvable que lors d'une TGS-REQ (demande de ticket de service), pas lors d'une authentification initiale. C'est pour ça que le KDC te répond qu'il ne trouve pas ce "principal" dans sa base : il cherche un compte nommé littéralement HTTP/fqdn, qui n'existe pas.

C'est un piège très classique avec ktpass/comptes de service portant un SPN.

Étape 1 — Obtenir un TGT en tant qu'utilisateur normal du domaine (le tien suffit) :

bash
kinit toncompte@MONDOMAINE.LOCAL
klist

Étape 2 — Demander un ticket de service pour le SPN et le faire déchiffrer avec le keytab de service :

bash
kvno -k /etc/apache2/http.keytab HTTP/fqdn@MONDOMAINE.LOCAL
Résultat attendu (succès)
HTTP/fqdn@MONDOMAINE.LOCAL: kvno = 3

Pas d'erreur = le KDC a délivré un ticket de service pour ce SPN, et ton keytab a réussi à le déchiffrer avec sa clé. Ça valide en une commande : le bon SPN, le bon compte associé, et la bonne clé/mot de passe dans le keytab. C'est le test le plus proche de ce que fait réellement mod_auth_gssapi.

En cas d'échec à cette étape
kvno: Server not found in Kerberos database → Le SPN n'est en réalité pas enregistré (ou mal orthographié/mauvaise casse) sur le compte AD. Vérifie depuis un poste Windows/RSAT :

Résumé rapide
Test	Valide quoi
klist -kt	Structure, principal, KVNO du fichier
Comparaison KVNO avec AD	Synchronisation avec le mot de passe actuel du compte
kinit -kt fichier principal	Clé correcte + communication KDC
curl --negotiate vers Apache	Fonctionnement bout en bout avec mod_auth_gssapi
