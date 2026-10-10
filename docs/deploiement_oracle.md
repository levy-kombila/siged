# Mettre SIGED en ligne : du PC au serveur Oracle Cloud (gratuit)

Le parcours se fait en **trois étapes**, dans cet ordre. Chacune valide la précédente : si l'application marche à l'étape A, un problème à l'étape B vient de Docker, et un problème à l'étape C vient du serveur.

| Étape | Où | Ce qu'on vérifie | Durée |
|---|---|---|---|
| **A. Local (venv)** | Votre PC Windows, Python seul | Le code fonctionne | 10 min |
| **B. Docker local** | Votre PC, Docker Desktop | Toute la pile (PostgreSQL, MinIO, OCR, HTTPS) fonctionne en conteneurs | 30 min |
| **C. En ligne** | VM gratuite Oracle Cloud | Le site est accessible publiquement en HTTPS | 1 h |

Toutes les commandes Windows sont pour **PowerShell**. Les commandes du serveur sont pour **bash** (Linux), une fois connecté en SSH.

---

## Étape A — Lancer en local (venv)

```powershell
cd D:\Django\siged\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

* Ouvrez http://localhost:8000, puis connectez-vous avec `admin` / `Admin@SIGED2026`.
* Mode développement : base SQLite (`siged.db`) et fichiers chiffrés dans `backend\data\`. **Aucun `.env` n'est nécessaire.**
* L'OCR et le PDF/A ne fonctionnent que si Tesseract, Ghostscript et LibreOffice sont installés sur Windows. Ce n'est pas indispensable : l'étape B les fournit.
* Tests : `python -m pytest -q`.

Arrêt : `Ctrl+C`.

---

## Étape B — Docker sur votre PC

### B.1 Préparer le fichier `.env`

```powershell
cd D:\Django\siged
copy .env.example .env
python backend\scripts\generer_secrets.py
```

Ouvrez `.env` dans VS Code ou le Bloc-notes et remplacez chaque ligne par celle affichée par le script. **Ajoutez à la fin** la ligne suivante, absente du modèle :

```dotenv
SIGED_DOMAIN=localhost
```

Conservez ces valeurs dans un gestionnaire de mots de passe : ce seront aussi celles du serveur. Le détail de chaque variable est dans [guide_secrets.md](guide_secrets.md).

### B.2 Démarrer

Docker Desktop doit être lancé (icône de la baleine verte).

```powershell
docker compose up -d --build
```

La première construction prend 10 à 20 minutes, car l'image télécharge LibreOffice et Tesseract. Ensuite :

```powershell
docker compose ps                 # tous les services « running » ou « healthy »
docker compose logs -f api        # journal de l'API (Ctrl+C pour quitter)
```

* Ouvrez **https://localhost**. Le navigateur affiche un avertissement : le certificat est local et auto-signé, c'est normal. Cliquez sur *Paramètres avancés* puis *Continuer*.
* Connexion : `admin` + la valeur de `SIGED_BOOTSTRAP_ADMIN_PASSWORD`.
* Test complet : déposez un scan (photo d'une facture). Après quelques secondes, la fiche affiche « PDF/A-2b · OCR » et la recherche retrouve les mots de l'image.

Arrêt : `docker compose down` (les données sont conservées dans des volumes Docker). Pour **tout effacer** : `docker compose down -v`.

---

## Étape C — En ligne sur Oracle Cloud (Always Free)

### Pourquoi Oracle Cloud ?

L'offre **Always Free** d'Oracle fournit une vraie machine virtuelle, gratuite sans limite de durée : processeur ARM Ampere, **2 cœurs et 12 Go de mémoire** au total (allocation réduite en juin 2026), 200 Go de disque. C'est la seule offre gratuite qui fait tourner **toute** la pile SIGED (OCR, PDF/A, PostgreSQL, MinIO) sans mise en veille.

Les plateformes gratuites de type Render ou Koyeb n'offrent que 512 Mo de mémoire et se mettent en veille. LibreOffice et l'OCR n'y tiennent pas.

**Conditions** :

* Une **carte bancaire Visa ou Mastercard** est demandée pour vérifier l'identité. Les cartes prépayées sont refusées. Une empreinte de vérification peut apparaître, puis être annulée ; rien n'est prélevé tant que vous restez dans les ressources Always Free.
* Un numéro de téléphone.
* **Mise en veille forcée** : Oracle peut récupérer une VM gratuite inutilisée pendant 7 jours (processeur, réseau et mémoire sous 20 %). Une démonstration peu utilisée peut donc être concernée. Voir C.9.

### C.1 Créer le compte

1. Ouvrez [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) → **Start for free**.
2. Pays : Gabon. Renseignez nom, e-mail, mot de passe.
3. **Home Region** : choisissez **France Central (Paris)** ou **Germany Central (Frankfurt)**. ⚠ Ce choix est **définitif**, et les VM gratuites ne peuvent être créées que dans cette région.
4. Ajoutez la carte bancaire, puis validez. L'activation du compte peut prendre de quelques minutes à quelques heures (e-mail de confirmation).

### C.2 Créer une clé SSH sur Windows

La clé SSH remplace le mot de passe pour se connecter au serveur.

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\oracle_siged
# appuyez deux fois sur Entrée (pas de phrase secrète), ou choisissez-en une
Get-Content $HOME\.ssh\oracle_siged.pub
```

Copiez la ligne affichée (`ssh-ed25519 AAAA… `). C'est la **clé publique** ; le fichier sans `.pub` est la clé privée, qui ne doit jamais être partagée.

### C.3 Créer la machine virtuelle

Console Oracle → menu ☰ → **Compute → Instances → Create instance** :

| Champ | Valeur |
|---|---|
| Name | `siged` |
| Image | **Canonical Ubuntu 24.04** (bouton *Change image*) |
| Shape | *Change shape* → **Ampere** → **VM.Standard.A1.Flex** → **2 OCPU**, **12 GB** de mémoire |
| Networking | *Create new virtual cloud network* (valeurs par défaut) ; **Assign a public IPv4 address** coché |
| Add SSH keys | **Paste public keys** → collez la clé de C.2 |
| Boot volume | *Specify a custom boot volume size* → **100 GB** |

Cliquez sur **Create**. Après 1 à 2 minutes, l'état passe à **Running** : notez l'**adresse IP publique** (Public IPv4 address).

> **« Out of capacity »** : les VM ARM gratuites sont très demandées. Réessayez plus tard, souvent la nuit ou tôt le matin, ou changez de *Availability domain* dans la section Placement.

### C.4 Ouvrir les ports 80 et 443 côté Oracle

Page de l'instance → **Primary VNIC** → cliquez sur le **Subnet** → **Security** (ou *Security Lists*) → *Default Security List* → **Add Ingress Rules** :

| Source CIDR | IP Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

Le port 22 (SSH) est déjà ouvert par défaut. Le pare-feu **interne** de la VM est ouvert par le script de l'étape C.6.

### C.5 Obtenir un nom de domaine gratuit (DuckDNS)

Let's Encrypt (le certificat HTTPS gratuit) a besoin d'un nom de domaine, pas d'une adresse IP.

1. Ouvrez [duckdns.org](https://www.duckdns.org) et connectez-vous avec GitHub.
2. Dans *sub domain*, tapez par exemple `siged-levy` → **add domain**.
3. Dans le champ *current ip*, mettez l'**IP publique** de la VM → **update ip**.

Votre site sera : **`https://siged-levy.duckdns.org`**. Si vous avez un vrai domaine, créez simplement un enregistrement DNS de type **A** vers l'IP de la VM.

### C.6 Se connecter et préparer le serveur

```powershell
ssh -i $HOME\.ssh\oracle_siged ubuntu@IP_PUBLIQUE
```

Répondez `yes` à la première connexion. Vous êtes maintenant **sur le serveur**, et les commandes suivantes sont en bash.

**Donner au serveur l'accès en lecture au dépôt privé (clé de déploiement)** :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_siged -N ""
cat ~/.ssh/github_siged.pub
```

Sur GitHub : dépôt `siged` → **Settings → Deploy keys → Add deploy key** → titre `oracle-vm`, collez la clé, **laissez « Allow write access » décoché** → *Add key*.

```bash
cat >> ~/.ssh/config <<'CONF'
Host github.com
    IdentityFile ~/.ssh/github_siged
    IdentitiesOnly yes
CONF
git clone git@github.com:levy-kombila/siged.git
cd siged
bash deploy/oracle/installer.sh
exit
```

Le script installe Docker, ouvre les ports 80/443 du pare-feu interne, crée un fichier d'échange de 2 Go et active les mises à jour de sécurité automatiques. La commande `exit` déconnecte la session pour que les droits Docker s'appliquent.

### C.7 Créer le `.env` du serveur

```powershell
ssh -i $HOME\.ssh\oracle_siged ubuntu@IP_PUBLIQUE
```

```bash
cd ~/siged
cp .env.example .env
nano .env
```

Dans l'éditeur `nano`, remplacez les valeurs par **celles de l'étape B.1** (copier sous Windows, puis clic droit dans PowerShell pour coller). Remplacez la dernière ligne par votre domaine :

```dotenv
SIGED_DOMAIN=siged-levy.duckdns.org
```

Enregistrez avec `Ctrl+O`, `Entrée`, puis quittez avec `Ctrl+X`. Protégez ensuite le fichier : `chmod 600 .env`.

### C.8 Démarrer

```bash
bash deploy/oracle/demarrer.sh
```

Le script vérifie le `.env`, construit l'image (10 à 20 minutes la première fois), démarre les 6 services et attend que le site réponde. Caddy obtient alors **automatiquement** le certificat Let's Encrypt et le renouvelle seul.

Ouvrez **https://siged-levy.duckdns.org** : cadenas valide, page de connexion SIGED.

**Données de démonstration** (depuis votre PC, dans le venv) :

```powershell
cd D:\Django\siged\backend
python -m scripts.demo_data --url https://siged-levy.duckdns.org --password "MOT_DE_PASSE_ADMIN"
```

### C.9 Exploitation courante

| Besoin | Commande (sur le serveur, dans `~/siged`) |
|---|---|
| État des services | `docker compose ps` |
| Journaux | `docker compose logs -f --tail 100 api worker caddy` |
| Mettre à jour après un `git push` | `bash deploy/oracle/mettre-a-jour.sh` |
| Redémarrer | `docker compose restart` |
| Sauvegardes (chaque nuit à 01:00) | `docker compose exec backup ls /backups` |
| Copier une sauvegarde sur votre PC | `docker compose cp backup:/backups ./backups` puis, depuis Windows : `scp -r -i $HOME\.ssh\oracle_siged ubuntu@IP:~/siged/backups .` |
| Espace disque | `df -h` et `docker system df` |

**Éviter la récupération de la VM inactive** : la solution recommandée par Oracle est de passer le compte en **Pay As You Go** (*Billing → Upgrade and Manage Payment*). Les ressources Always Free restent gratuites, et Oracle ne récupère plus les instances inactives. Créez aussitôt une **alerte budgétaire** à 1 € (*Billing → Budgets*) pour être prévenu de toute facturation imprévue. Sans ce passage, utilisez simplement l'application régulièrement.

### C.10 Dépannage

| Symptôme | Cause probable et solution |
|---|---|
| `ssh: connection timed out` | Mauvaise IP, ou instance arrêtée (console Oracle → Start) |
| `Permission denied (publickey)` | Clé non indiquée : ajoutez `-i $HOME\.ssh\oracle_siged` |
| `git clone` : *Permission denied* | Clé de déploiement absente sur GitHub (C.6) |
| Site injoignable depuis Internet | Règles d'entrée 80/443 manquantes (C.4), ou `installer.sh` non exécuté |
| Erreur de certificat sur le domaine | DuckDNS ne pointe pas vers la bonne IP (C.5), ou le port 80 est fermé. Voir `docker compose logs caddy` |
| `ERREUR : fichier .env absent` | Étape C.7 non faite (le `.env` n'est jamais sur GitHub) |
| `Configuration de production incomplète` dans `docker compose logs api` | Une variable obligatoire du `.env` est vide (le message indique laquelle) |

---

## Et Docker Hub ?

Docker Hub n'est **pas nécessaire** : le serveur construit l'image lui-même à partir du dépôt. L'image publiée depuis Windows (`levy2025/siged`) est en architecture **amd64**, alors que la VM Oracle est **ARM64** : elle n'y fonctionnerait pas telle quelle. Pour publier une image utilisable partout, il faudrait une construction multi-architecture (`docker buildx build --platform linux/amd64,linux/arm64 …`), par exemple automatisée dans GitHub Actions.
