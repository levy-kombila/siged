# Déployer SIGED gratuitement sur Vercel

Architecture gratuite proposée :

| Rôle | Service (offre gratuite) | Pourquoi |
|---|---|---|
| Application (API + interface) | **Vercel** Hobby, fonction Python, région Paris (`cdg1`) | Déploiement automatique à chaque `git push`, HTTPS inclus |
| Base de données | **Neon** PostgreSQL (via le Marketplace Vercel) | Ajoutée en un clic depuis Vercel, variable `DATABASE_URL` injectée automatiquement |
| Fichiers (chiffrés AES-256) | **Supabase Storage** (API compatible S3) | Stockage objet gratuit, sans carte bancaire |
| Tâches planifiées | **Vercel Cron Jobs** (1 fois/jour en Hobby) | Intégrité SHA-256, DUA, reprise des conversions |

> Vercel n'a ni disque persistant ni processus permanent : la base et les fichiers doivent être hébergés ailleurs, d'où Neon et Supabase.

## Différences avec le déploiement Docker

| Fonction | Docker (serveur) | Vercel (serverless) |
|---|---|---|
| Conversion PDF/A + OCR | ✔ (OCRmyPDF, Tesseract, LibreOffice) | ✘ outils absents : texte extrait des PDF et DOCX natifs seulement (statut `PARTIAL`) |
| Taille max d'un fichier | 200 Mo | **4 Mo** (corps de requête limité à 4,5 Mo par Vercel) |
| Dossier partagé surveillé | ✔ | ✘ (pas de disque persistant) |
| Contrôle d'intégrité / DUA | toutes les nuits (worker) | 1 fois/jour (Vercel Cron) |
| Messagerie IMAP | toutes les 5 min | 1 fois/jour (dans la tâche quotidienne) |

Tout le reste est identique : recherche, versions, workflow, RBAC, chiffrement, audit chaîné, aperçu, export AIP, webhooks.

## Étape 1 — Base de données Neon (depuis Vercel)

1. Sur [vercel.com](https://vercel.com), connectez-vous avec GitHub.
2. Menu **Storage → Create Database → Neon (Postgres)**, région **Europe (Frankfurt)**, offre gratuite.
3. Vous liez la base au projet à l'étape 3 : Vercel ajoutera alors automatiquement `DATABASE_URL`.

SIGED convertit lui-même `postgres://…` en URL SQLAlchemy et désactive le pool local et les requêtes préparées automatiques en serverless (compatibilité PgBouncer).

## Étape 2 — Stockage des fichiers sur Supabase

1. Créez un compte et un projet sur [supabase.com](https://supabase.com) (région **Paris / eu-west-3** de préférence).
2. **Storage → New bucket** : nom `siged-documents`, **Private** (non public).
3. **Project Settings → Storage → S3 Connection** : activez la connexion S3, notez l'**Endpoint** et la **Region**.
4. Dans la même page, **New access key** : notez l'**Access key ID** et le **Secret access key** (affiché une seule fois).

Les fichiers sont chiffrés par SIGED **avant** l'envoi : Supabase ne stocke que des données illisibles.

## Étape 3 — Importer le dépôt dans Vercel

1. **Add New… → Project → Import** le dépôt `levy-kombila/siged`.
2. Framework : **FastAPI** (détecté grâce à `requirements.txt` et `index.py` à la racine). Laissez *Root Directory* vide.
3. Avant de cliquer sur **Deploy**, ouvrez **Environment Variables** et ajoutez :

| Variable | Valeur |
|---|---|
| `SIGED_ENVIRONMENT` | `prod` |
| `SIGED_SECRET_KEY` | chaîne aléatoire ≥ 32 caractères (voir commande ci-dessous) |
| `SIGED_STORAGE_ENCRYPTION_KEY` | clé AES-256 en base64 (voir commande) — **à conserver hors ligne** |
| `SIGED_STORAGE_BACKEND` | `s3` |
| `SIGED_S3_ENDPOINT_URL` | endpoint Supabase, ex. `https://xxxx.storage.supabase.co/storage/v1/s3` |
| `SIGED_S3_REGION` | région affichée par Supabase, ex. `eu-west-3` |
| `SIGED_S3_ACCESS_KEY` | Access key ID Supabase |
| `SIGED_S3_SECRET_KEY` | Secret access key Supabase |
| `SIGED_S3_BUCKET` | `siged-documents` |
| `SIGED_BOOTSTRAP_ADMIN_PASSWORD` | mot de passe du compte `admin` créé au premier démarrage |
| `CRON_SECRET` | chaîne aléatoire ≥ 16 caractères (protège la route des tâches planifiées) |
| `DATABASE_URL` | ajoutée automatiquement en liant la base Neon (Storage → Connect Project) |

Générer les secrets (PowerShell ou terminal, dans le venv) :

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                     # SIGED_SECRET_KEY
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"  # SIGED_STORAGE_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(24))"                     # CRON_SECRET
```

4. Liez la base Neon au projet (**Storage → votre base → Connect Project**), puis **Deploy**.

Au premier appel, SIGED crée les tables, les index plein texte, les déclencheurs d'audit, les rôles, le compte `admin` et le plan de classement. Si une variable obligatoire manque, le démarrage échoue avec un message explicite dans **Logs**.

## Étape 4 — Vérifier

* `https://<votre-projet>.vercel.app/health` → `{"status":"ok","database":true,"storage":true}`
* `https://<votre-projet>.vercel.app/` → connexion `admin` + mot de passe choisi ; changez-le ensuite.
* `https://<votre-projet>.vercel.app/docs` → documentation de l'API.
* **Settings → Cron Jobs** : la tâche `/api/cron/daily` apparaît (exécutée vers 02 h UTC, soit 03 h à Libreville). Le bouton **Run** permet de la tester.

Données de démonstration depuis votre poste :

```bash
cd backend
python -m scripts.demo_data --url https://<votre-projet>.vercel.app --password "<mot de passe admin>"
```

## Mises à jour

Chaque `git push` sur `main` redéploie automatiquement ; chaque branche ou pull request obtient une URL de prévisualisation.

## Dépannage

| Symptôme | Cause probable |
|---|---|
| `Configuration de production incomplète` dans les logs | Variable manquante (secret, clé AES, `DATABASE_URL` ou `SIGED_STORAGE_BACKEND=s3`) |
| `/health` : `"storage": false` | Endpoint, région, clés ou nom du bucket Supabase incorrects |
| `413` au dépôt | Fichier > 4 Mo (limite Vercel) |
| `401` sur `/api/cron/daily` | `CRON_SECRET` modifié sans redéploiement |
| Lenteur au premier appel | Démarrage à froid de la fonction et réveil de la base Neon (quelques secondes) |
