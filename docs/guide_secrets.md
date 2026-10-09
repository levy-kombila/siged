# Guide des secrets et clés de SIGED

Ce guide explique, variable par variable, **d'où vient chaque valeur** et **comment l'obtenir**, pour les deux modes de déploiement :

* **Docker** (votre serveur ou votre PC) : les valeurs vont dans le fichier `.env`, à la racine du projet.
* **Vercel** (hébergement gratuit) : les valeurs vont dans **Vercel → votre projet → Settings → Environment Variables**.

> **Règles d'or**
> 1. Le fichier `.env` ne doit **jamais** être envoyé sur GitHub (il est déjà exclu par `.gitignore`).
> 2. Rangez tous les secrets dans un gestionnaire de mots de passe (Bitwarden, KeePassXC, 1Password…).
> 3. La clé `SIGED_STORAGE_ENCRYPTION_KEY` est **irremplaçable** : si vous la perdez, tous les fichiers stockés deviennent illisibles. Gardez-en une copie hors du serveur.

---

## 1. Vue d'ensemble : 3 familles de valeurs

| Famille | Variables | Comment l'obtenir |
|---|---|---|
| **A. Générées par vous** (aléatoires) | `SIGED_SECRET_KEY`, `SIGED_STORAGE_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `CRON_SECRET`, `SIGED_BOOTSTRAP_ADMIN_PASSWORD` | Script fourni `generer_secrets.py` (§2) |
| **B. Fournies par un service en ligne** | `DATABASE_URL` (Neon), clés S3 Supabase, mots de passe SMTP/IMAP | Créées sur le site du service (§4 à §6) |
| **C. Simples réglages** | `SIGED_ENVIRONMENT`, `SIGED_STORAGE_BACKEND`, `SIGED_S3_BUCKET`, `SIGED_OCR_LANGUAGES`… | Valeurs fixes indiquées dans ce guide |

---

## 2. Générer toutes les valeurs aléatoires en une commande

Dans PowerShell, à la racine du projet (venv activé ou non, seul Python est nécessaire) :

```powershell
cd D:\Django\siged
python backend\scripts\generer_secrets.py
```

Le script **n'écrit aucun fichier** : il affiche deux blocs prêts à copier.

* **Bloc 1** → pour Docker : copiez-le dans votre `.env`.
* **Bloc 2** → pour Vercel : saisissez chaque ligne dans les variables d'environnement.

Chaque exécution produit de **nouvelles** valeurs. Lancez-le **une seule fois** par installation, puis conservez le résultat. Ne le relancez pas pour un système déjà en service : une nouvelle clé AES ne pourrait pas déchiffrer les fichiers existants.

### Si vous préférez générer chaque valeur à la main

```powershell
# SIGED_SECRET_KEY : signe les jetons de connexion (JWT)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# SIGED_STORAGE_ENCRYPTION_KEY : clé AES-256 (32 octets en base64)
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"

# POSTGRES_PASSWORD / MINIO_ROOT_PASSWORD (hexadécimal, sans caractère spécial)
python -c "import secrets; print(secrets.token_hex(16))"

# CRON_SECRET (Vercel uniquement)
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

---

## 3. Détail des variables générées

| Variable | Rôle | Format attendu | Remarques |
|---|---|---|---|
| `SIGED_SECRET_KEY` | Signe les jetons JWT de connexion | ≥ 32 caractères aléatoires | La changer déconnecte tous les utilisateurs (sans perte de données) |
| `SIGED_STORAGE_ENCRYPTION_KEY` | Chiffre chaque fichier en AES-256 avant stockage | 44 caractères base64 (= 32 octets) | **Ne jamais la changer** sur un système en service |
| `POSTGRES_PASSWORD` | Mot de passe de la base (Docker) | Hexadécimal conseillé | Doit être **identique** dans `SIGED_DATABASE_URL` |
| `MINIO_ROOT_PASSWORD` | Mot de passe du stockage MinIO (Docker) | ≥ 8 caractères | Doit être **identique** à `SIGED_S3_SECRET_KEY` |
| `CRON_SECRET` | Protège la route des tâches planifiées (Vercel) | ≥ 16 caractères | Vercel l'envoie automatiquement à chaque déclenchement |
| `SIGED_BOOTSTRAP_ADMIN_PASSWORD` | Mot de passe du compte `admin` créé **au premier démarrage** | ≥ 10 caractères, 3 types parmi : minuscules, majuscules, chiffres, symboles | Ne sert qu'une fois ; ensuite on change le mot de passe dans l'application |

**Pourquoi l'hexadécimal pour PostgreSQL ?** Le mot de passe est aussi écrit dans l'URL `postgresql+psycopg://siged:MOTDEPASSE@postgres:5432/siged`. Des caractères comme `@`, `/`, `:` ou `#` casseraient cette URL. Le format hexadécimal (`0-9a-f`) n'en contient aucun.

---

## 4. Base de données

### 4.a Docker : rien à créer

Le conteneur `postgres` crée la base au premier démarrage avec `POSTGRES_DB`, `POSTGRES_USER` et `POSTGRES_PASSWORD`. Il suffit que l'URL soit cohérente :

```dotenv
POSTGRES_DB=siged
POSTGRES_USER=siged
POSTGRES_PASSWORD=3f9c...e21          # valeur générée
SIGED_DATABASE_URL=postgresql+psycopg://siged:3f9c...e21@postgres:5432/siged
```

### 4.b Vercel : base Neon (gratuite)

1. Connectez-vous sur [vercel.com](https://vercel.com) avec votre compte GitHub.
2. Dans le menu du haut, ouvrez **Storage**, puis **Create Database**.
3. Choisissez **Neon** (Serverless Postgres), puis **Continue**.
4. Région : **Europe — Frankfurt (eu-central-1)**, la plus proche de la fonction Vercel (Paris). Offre : **Free**.
5. Nommez la base `siged`, puis **Create**.
6. Sur la page de la base : **Connect Project** → choisissez le projet `siged` → cochez *Production*, *Preview* et *Development*.

Vercel ajoute alors automatiquement `DATABASE_URL` (et d'autres variables `PG*`) dans votre projet. **Vous n'avez rien à recopier** : SIGED lit `DATABASE_URL` et la convertit lui-même au bon format.

Pour la voir : **Storage → votre base → .env.local** (ou onglet *Quickstart*). Elle ressemble à :

```
postgresql://neondb_owner:xxxx@ep-xxxx-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
```

Le mot `-pooler` signale la connexion « mutualisée », celle qui convient à Vercel.

---

## 5. Stockage des fichiers

### 5.a Docker : MinIO (inclus)

Le conteneur `minio` utilise `MINIO_ROOT_USER` et `MINIO_ROOT_PASSWORD`. SIGED s'y connecte avec **les mêmes valeurs** :

```dotenv
SIGED_STORAGE_BACKEND=s3
SIGED_S3_ENDPOINT_URL=http://minio:9000
SIGED_S3_ACCESS_KEY=siged                 # = MINIO_ROOT_USER
SIGED_S3_SECRET_KEY=7a1b...90             # = MINIO_ROOT_PASSWORD
SIGED_S3_BUCKET=siged-documents           # créé automatiquement
MINIO_ROOT_USER=siged
MINIO_ROOT_PASSWORD=7a1b...90
```

Console d'administration MinIO (facultatif) : `http://localhost:9001` si vous ajoutez le port `9001` dans `docker-compose.yml`.

### 5.b Vercel : Supabase Storage (gratuit, compatible S3)

**Créer le projet**

1. Inscrivez-vous sur [supabase.com](https://supabase.com) (bouton *Start your project*, connexion possible avec GitHub).
2. **New project** : nom `siged`, mot de passe de base au choix (inutile pour SIGED, mais à noter), région **West EU (Paris)**, offre **Free**.
3. Attendez environ 2 minutes que le projet soit prêt.

**Créer le bucket**

4. Menu de gauche : **Storage** → **New bucket**.
5. Nom : `siged-documents`. Laissez **Public bucket désactivé** (bucket privé). **Create**.

**Récupérer l'endpoint, la région et les clés S3**

6. Menu de gauche : **Project Settings** (roue dentée) → **Storage**. Selon la version de l'interface, la section peut aussi se trouver dans **Storage → Settings**.
7. Section **S3 Connection** : activez **Enable connection via S3 protocol** si ce n'est pas déjà fait.
8. Notez :
   * **Endpoint**, de la forme `https://<identifiant>.storage.supabase.co/storage/v1/s3` → `SIGED_S3_ENDPOINT_URL`
   * **Region**, par exemple `eu-west-3` → `SIGED_S3_REGION`
9. Section **S3 Access Keys** → **New access key** → description `siged-vercel` → **Create access key**.
10. Copiez immédiatement :
    * **Access key ID** → `SIGED_S3_ACCESS_KEY`
    * **Secret access key** → `SIGED_S3_SECRET_KEY` (**affiché une seule fois**)

Ces clés donnent un accès complet au stockage : elles ne doivent exister que dans les variables Vercel et dans votre gestionnaire de mots de passe.

```dotenv
SIGED_STORAGE_BACKEND=s3
SIGED_S3_ENDPOINT_URL=https://abcdefgh.storage.supabase.co/storage/v1/s3
SIGED_S3_REGION=eu-west-3
SIGED_S3_ACCESS_KEY=6f1c...
SIGED_S3_SECRET_KEY=9b7e...
SIGED_S3_BUCKET=siged-documents
```

---

## 6. Notifications et capture par e-mail (facultatif)

Laissez ces variables **vides** si vous n'en avez pas besoin : SIGED fonctionne sans.

### 6.a Avec un compte Gmail

Gmail refuse votre mot de passe habituel pour les applications : il faut un **mot de passe d'application**.

1. Activez la **validation en deux étapes** : [myaccount.google.com](https://myaccount.google.com) → **Sécurité** → *Validation en deux étapes*.
2. Ouvrez [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
3. Nom de l'application : `SIGED` → **Créer**.
4. Copiez le code de 16 lettres affiché (les espaces sont facultatifs).

```dotenv
# Envoi des notifications (soumission, validation, rejet)
SIGED_SMTP_HOST=smtp.gmail.com
SIGED_SMTP_PORT=587
SIGED_SMTP_USER=votre.adresse@gmail.com
SIGED_SMTP_PASSWORD=abcdefghijklmnop        # mot de passe d'application
SIGED_SMTP_FROM=votre.adresse@gmail.com

# Capture des pièces jointes reçues (chaque PJ devient un document)
SIGED_IMAP_HOST=imap.gmail.com
SIGED_IMAP_USER=votre.adresse@gmail.com
SIGED_IMAP_PASSWORD=abcdefghijklmnop        # même mot de passe d'application
```

Conseil : utilisez une adresse **dédiée** (par exemple `siged.archives@gmail.com`). Avec l'IMAP activé, SIGED transforme en document **toutes** les pièces jointes des messages non lus de la boîte.

### 6.b Avec une messagerie professionnelle

Demandez au service informatique le serveur SMTP (port 587, STARTTLS), le serveur IMAP (port 993, SSL) et un compte de service.

---

## 7. Fichiers complets à obtenir

### 7.a `.env` pour Docker

```dotenv
SIGED_ENVIRONMENT=prod
SIGED_SECRET_KEY=<généré>
SIGED_STORAGE_ENCRYPTION_KEY=<généré>

POSTGRES_DB=siged
POSTGRES_USER=siged
POSTGRES_PASSWORD=<généré>
SIGED_DATABASE_URL=postgresql+psycopg://siged:<même valeur>@postgres:5432/siged

SIGED_STORAGE_BACKEND=s3
SIGED_S3_ENDPOINT_URL=http://minio:9000
SIGED_S3_ACCESS_KEY=siged
SIGED_S3_SECRET_KEY=<généré>
SIGED_S3_BUCKET=siged-documents
MINIO_ROOT_USER=siged
MINIO_ROOT_PASSWORD=<même valeur que SIGED_S3_SECRET_KEY>

SIGED_BOOTSTRAP_ADMIN_PASSWORD=<généré>
SIGED_RETENTION_AUTO_EXECUTE=false
SIGED_OCR_LANGUAGES=fra+eng

SIGED_SMTP_HOST=
SIGED_SMTP_USER=
SIGED_SMTP_PASSWORD=
SIGED_SMTP_FROM=ged@exemple.ga
SIGED_IMAP_HOST=
SIGED_IMAP_USER=
SIGED_IMAP_PASSWORD=
```

Le plus simple : `copy .env.example .env`, puis remplacez les valeurs par celles du **Bloc 1** du script.

### 7.b Variables Vercel

Dans **Vercel → projet siged → Settings → Environment Variables**, pour chaque ligne : *Key* = nom, *Value* = valeur, environnements **Production + Preview**, puis **Save**.

| Variable | Valeur |
|---|---|
| `SIGED_ENVIRONMENT` | `prod` |
| `SIGED_SECRET_KEY` | Bloc 2 du script |
| `SIGED_STORAGE_ENCRYPTION_KEY` | Bloc 2 du script |
| `SIGED_BOOTSTRAP_ADMIN_PASSWORD` | Bloc 2 du script |
| `CRON_SECRET` | Bloc 2 du script |
| `SIGED_STORAGE_BACKEND` | `s3` |
| `SIGED_S3_BUCKET` | `siged-documents` |
| `SIGED_S3_ENDPOINT_URL` | Supabase (§5.b) |
| `SIGED_S3_REGION` | Supabase (§5.b) |
| `SIGED_S3_ACCESS_KEY` | Supabase (§5.b) |
| `SIGED_S3_SECRET_KEY` | Supabase (§5.b) |
| `DATABASE_URL` | **automatique** (Neon, §4.b) |

Astuce : la page Environment Variables accepte un **copier-coller de plusieurs lignes** `CLE=valeur` dans le premier champ *Key* ; Vercel les répartit lui-même.

Après toute modification de variable : **Deployments → … → Redeploy**, car les variables ne sont lues qu'au déploiement.

---

## 8. Vérifier que tout est correct

| Test | Résultat attendu |
|---|---|
| `https://<projet>.vercel.app/health` (ou `https://localhost/health` en Docker) | `{"status":"ok","database":true,"storage":true}` |
| `"database": false` | `DATABASE_URL` absente (base Neon non liée) ou mot de passe incohérent en Docker |
| `"storage": false` | Endpoint, région, clés ou nom du bucket incorrects |
| Erreur `Configuration de production incomplète` dans les logs | Le message indique la variable manquante |
| Connexion `admin` refusée | Le mot de passe initial n'est appliqué qu'à la **création** du compte : si la base existait déjà, c'est l'ancien qui reste valable |

---

## 9. Changer ou renouveler un secret

| Secret | Peut-on le changer ? | Conséquence |
|---|---|---|
| `SIGED_SECRET_KEY` | Oui | Tout le monde doit se reconnecter |
| `SIGED_STORAGE_ENCRYPTION_KEY` | **Non** (sans migration) | Fichiers existants illisibles |
| Clés Supabase S3 | Oui | Créer une nouvelle clé, mettre à jour Vercel, redéployer, puis supprimer l'ancienne |
| `CRON_SECRET` | Oui | Redéployer |
| `POSTGRES_PASSWORD` (Docker) | Oui, mais aussi dans la base | `ALTER USER siged PASSWORD '...'` dans PostgreSQL, puis mettre à jour `.env` |
| Mot de passe `admin` | Oui | Dans l'application (gestion des utilisateurs) |

En cas de fuite d'un secret (par exemple un `.env` envoyé par erreur sur GitHub) : changez-le immédiatement. Supprimer le fichier du dépôt ne suffit pas, car il reste dans l'historique Git.
