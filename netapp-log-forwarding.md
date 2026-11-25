# Remontée des logs NetApp ONTAP vers un collecteur syslog

## 1. Principe

ONTAP envoie ses événements (EMS) en syslog depuis les **LIF de management de chaque nœud** vers le collecteur (rsyslog, Graylog, Splunk, Vector…).

---

## 2. Ports à ouvrir

Sens : **LIF de management de chaque nœud → collecteur** (flux sortant depuis NetApp).

| Protocole   | Port                                              |
|-------------|---------------------------------------------------|
| Syslog UDP  | 514/UDP                                           |
| Syslog TCP  | 514/TCP                                           |
| Syslog TLS  | 6514/TCP (standard, mais le port est modifiable)  |

Ouvrir pour **toutes les IP de management des nœuds**, pas seulement la LIF cluster.

---

## 3. Configuration

### CLI

```
cluster log-forwarding create -destination 10.0.0.50 -port 514 -protocol udp-unencrypted -facility user
```

- `-protocol` : `udp-unencrypted`, `tcp-unencrypted` ou `tcp-encrypted` (TLS)
- `-verify-server true` : vérifie le certificat du collecteur (CA à installer)
- `-message-format rfc-5424` : recommandé pour un parsing propre

Exemple TLS :

```
cluster log-forwarding create -destination collecteur.mydomain.org -port 6514 -protocol tcp-encrypted -verify-server true -message-format rfc-5424 -facility user
```

Envoyer aussi les logs d'audit d'administration :

```
security audit modify -cliset on -cliget on -httpset on -httpget on
```

### System Manager

Cluster → Settings → Notification management → **Log forwarding** → Add : IP, port, protocole, facility.
(Le libellé peut varier selon la version.)

---

## 4. Vérifications

### Configuration ONTAP

```
cluster log-forwarding show -instance
```

### Connectivité

**Côté collecteur**

```
ss -lntup | grep -E ':514|:6514'                 # le service écoute
tcpdump -ni any host <IP_noeud> and port 514      # paquets reçus
```

**Côté ONTAP**

```
network ping -lif <lif-mgmt> -vserver <admin-vserver> -destination <IP_collecteur>
network connections active show -remote-host <IP_collecteur>
```

En TCP/TLS, la connexion établie doit apparaître.

**Depuis un hôte du même segment**

```
nc -vz <IP_collecteur> 6514
```

> L'UDP ne confirme rien : seul `tcpdump` prouve la réception.

### Test de bout en bout

Générer un événement (login SSH, changement de config avec l'audit activé) et vérifier sa réception sur le collecteur. Contrôler que **tous les nœuds** de chaque cluster remontent.

---

## 5. Vérifier TLS

1. **Installer le CA** qui a signé le certificat du collecteur côté ONTAP :

   ```
   security certificate install -type server-ca -vserver <admin-vserver>
   security certificate show -type server-ca
   ```

2. **SAN du certificat** : doit correspondre à l'IP ou au FQDN utilisé dans `-destination` si `-verify-server true`.

3. **Tester le certificat du collecteur** depuis un poste :

   ```
   openssl s_client -connect <collecteur>:6514 -CAfile ca.pem
   ```

   Chercher `Verify return code: 0 (ok)`, puis contrôler la chaîne, les dates d'expiration et le SAN.

4. **Confirmer le chiffrement** :

   ```
   tcpdump -ni any port 6514 -A
   ```

   On doit voir un handshake TLS puis du contenu illisible. Du texte en clair = pas de TLS.

5. **Erreurs possibles**
   - Collecteur (logs rsyslog/Vector) : `handshake failure`, `unknown ca`
   - ONTAP : `event log show -message-name *log*forward*` (nom exact variable selon la version)

---

## 6. Vector (vector.dev)

Outil open source de pipeline d'observabilité : il collecte, transforme et route logs et métriques. Ici, il joue le rôle de **collecteur syslog** : il reçoit les logs NetApp, les parse, puis les envoie vers Loki, Elasticsearch, Splunk, S3, un fichier, etc.

### Exemple minimal (UDP → fichier)

```toml
[sources.netapp]
type = "syslog"
address = "0.0.0.0:514"
mode = "udp"

[sinks.fichier]
type = "file"
inputs = ["netapp"]
path = "/var/log/netapp/%Y-%m-%d.log"
encoding.codec = "json"
```

### Exemple TCP + TLS

```toml
[sources.netapp_tls]
type = "syslog"
address = "0.0.0.0:6514"
mode = "tcp"

[sources.netapp_tls.tls]
enabled = true
crt_file = "/etc/vector/certs/collecteur.crt"
key_file = "/etc/vector/certs/collecteur.key"

[sinks.fichier]
type = "file"
inputs = ["netapp_tls"]
path = "/var/log/netapp/%Y-%m-%d.log"
encoding.codec = "json"
```

Valider la config avant de démarrer :

```
vector validate /etc/vector/vector.toml
```
