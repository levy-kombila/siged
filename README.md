# SIGED — Système Intégré de Gestion Électronique des Documents

GED + archivage électronique (SAE) conforme aux principes **ISO 15489** et **ISO 14721 (OAIS)**.
Backend **Python / FastAPI**, PostgreSQL, MinIO (S3), OCRmyPDF/Tesseract/LibreOffice, interface web incluse.

## Fonctionnalités

| Domaine | Fonctions |
|---|---|
| Acquisition | Dépôt unitaire, import par lot (fichiers ou ZIP + `manifest.csv`), dossier partagé surveillé, messagerie IMAP, API (clé d'API) |
| Pérennisation | Conversion PDF/A-2b, OCR (français/anglais), original conservé |
| Métadonnées | Fiche obligatoire (titre, auteur, date, type, mots-clés, DUA), métadonnées libres, plan de classement + classement automatique |
| Recherche | 13 critères + plein texte avec extraits surlignés, tri, pagination |
| Consultation | Aperçu en ligne (pages en images, PDF inline), téléchargement original/PDF/A |
| Versions & workflow | v1.0 → v1.1 → v2.0, historique immuable ; brouillon → en validation → validé (figé), rejet motivé, séparation des tâches |
| Sécurité | JWT, RBAC (5 rôles, 10 permissions), verrouillage de compte, AES-256-GCM au repos, TLS 1.3 |
| Conformité | Empreintes SHA-256 + contrôle nocturne, journal d'audit chaîné inaltérable, DUA / sort final / gel juridique, export AIP (BagIt) |
| Interopérabilité | OpenAPI (`/docs`), clés d'API, webhooks signés HMAC, notifications e-mail |

## Démarrage rapide (développement, sans Docker)

Prérequis : Python 3.11+ ; pour la conversion PDF/A/OCR : `tesseract-ocr tesseract-ocr-fra ghostscript libreoffice`.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

* Interface : http://localhost:8000 — compte initial `admin` / `Admin@SIGED2026` (**à changer**)
* Documentation de l'API : http://localhost:8000/docs
* Données de démonstration : `python -m scripts.demo_data` (comptes `archiviste`, `valideur`, `redacteur`, `consultant`, mot de passe `Demo#SIGED2026`)

Par défaut : base SQLite `siged.db` et fichiers chiffrés dans `./data/storage`.

## Déploiement complet (Docker)

```bash
cp .env.example .env        # puis renseigner les secrets (voir commentaires du fichier)
sh deploy/scripts/gen-certs.sh    # certificat de test ; en production, certificat réel
docker compose up -d --build
```

Services : `nginx` (443, TLS 1.3), `api`, `worker` (OCR, intégrité, DUA, captures), `postgres`, `minio`, `backup`.

> ⚠️ Sauvegardez `SIGED_STORAGE_ENCRYPTION_KEY` hors du serveur : sans elle, les fichiers sont irrécupérables.

## Déploiement gratuit sur Vercel

Le dépôt est prêt pour Vercel (`index.py`, `requirements.txt`, `vercel.json` à la racine) avec Neon (PostgreSQL) et Supabase Storage (S3). Guide pas à pas et limites du mode serverless : [docs/deploiement_vercel.md](docs/deploiement_vercel.md).

**Secrets et clés** (où obtenir chaque valeur, Docker et Vercel) : [docs/guide_secrets.md](docs/guide_secrets.md) — et `python backend/scripts/generer_secrets.py` pour générer toutes les valeurs aléatoires.

## Tests

```bash
cd backend
python -m pytest -q                                                    # SQLite
SIGED_TEST_DATABASE_URL=postgresql+psycopg://user:pwd@localhost:5432/siged_test python -m pytest -q   # PostgreSQL
```

77 tests, organisés par sprint (`tests/test_sprintN_*.py`) + déploiement serverless (`tests/test_deploiement_vercel.py`). Les tests de conversion sont ignorés automatiquement si OCRmyPDF, Ghostscript ou LibreOffice sont absents.

## Arborescence

```
siged/
├── backend/
│   ├── app/            api/ (routes) · services/ (métier) · core/ (config, sécurité, chiffrement) · jobs/ (worker) · static/ (IHM)
│   ├── sql/            objets PostgreSQL (index plein texte, déclencheurs d'audit)
│   ├── scripts/        données de démonstration
│   └── tests/          tests par sprint
├── deploy/             nginx (TLS 1.3), scripts de certificats, sauvegarde, restauration
├── docs/
│   ├── cahier_architecture.md / .docx / .pdf
│   ├── rapports/       rapports des sprints 0 à 7 + rapport final de recette
│   ├── diagrammes/     sources Mermaid + PNG
│   ├── captures/       captures d'écran
│   └── openapi.json    contrat d'API
├── index.py · requirements.txt · vercel.json   (déploiement Vercel)
├── docker-compose.yml  ·  .env.example  ·  Makefile  ·  .github/workflows/ci.yml
```
