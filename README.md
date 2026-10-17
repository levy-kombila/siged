# GEDarchive — Gestion électronique des documents et archivage

*(nom de code du dépôt : SIGED ; les variables d'environnement gardent le préfixe `SIGED_`)*

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
| Rayonnage | Localisation des exemplaires papier (site › salle › rayonnage › travée › tablette › boîte), capacité et remplissage des boîtes, contenu de chaque emplacement |
| Échéances | Date de fin de validité par document ; alertes d'obsolescence et de fin de DUA à J-90, J-30, J-7 et le jour même (cloche + e-mail), réglables par `SIGED_OBSOLESCENCE_ALERT_DAYS` |
| Sécurité | JWT, RBAC (5 rôles, 11 permissions), verrouillage de compte, AES-256-GCM au repos, TLS 1.3 |
| Conformité | Empreintes SHA-256 + contrôle nocturne, journal d'audit chaîné inaltérable, DUA / sort final / gel juridique, export AIP (BagIt) |
| Interopérabilité | OpenAPI (`/docs`), clés d'API, webhooks signés HMAC, notifications e-mail |

## Mise en route : local → Docker → en ligne

* Démonstration gratuite depuis votre PC (tunnel Cloudflare) : **[docs/mise_en_ligne_pc.md](docs/mise_en_ligne_pc.md)**.
* Site disponible 24 h/24 (Oracle Cloud ou VPS) : **[docs/deploiement_oracle.md](docs/deploiement_oracle.md)**.

**A. Local (développement, sans Docker)** — Python 3.11+ :

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

http://localhost:8000 — compte initial `admin` / `Admin@SIGED2026`. Base SQLite et fichiers chiffrés dans `backend/data`. Documentation de l'API : `/docs`.

**B. Docker sur votre PC** — toute la pile (Caddy HTTPS, API, worker OCR, PostgreSQL, MinIO, sauvegardes) :

```bash
cp .env.example .env                       # Windows : copy .env.example .env
python backend/scripts/generer_secrets.py  # puis recopier les valeurs dans .env (+ SIGED_DOMAIN=localhost)
docker compose up -d --build
```

https://localhost (certificat local auto-signé : avertissement du navigateur normal).

**C bis. En ligne depuis votre PC, gratuitement, sans compte** — tunnel Cloudflare (toutes les fonctionnalités, adresse `https://….trycloudflare.com`, tant que le PC est allumé) : [docs/mise_en_ligne_pc.md](docs/mise_en_ligne_pc.md)

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\en-ligne.ps1
```

**C. En ligne 24 h/24, gratuitement** — VM **Oracle Cloud Always Free** (ARM, 2 cœurs, 12 Go) + domaine DuckDNS ; Caddy obtient le certificat Let's Encrypt automatiquement :

```bash
bash deploy/oracle/installer.sh     # une fois : Docker, pare-feu, swap, mises à jour auto
bash deploy/oracle/demarrer.sh      # construit, démarre, vérifie https://SIGED_DOMAIN/health
bash deploy/oracle/mettre-a-jour.sh # après chaque git push
```

**Secrets et clés** — où obtenir chaque valeur : [docs/guide_secrets.md](docs/guide_secrets.md).

> ⚠️ Sauvegardez `SIGED_STORAGE_ENCRYPTION_KEY` hors du serveur : sans elle, les fichiers sont irrécupérables.

## Tests

```bash
cd backend
python -m pytest -q                                                    # SQLite
SIGED_TEST_DATABASE_URL=postgresql+psycopg://user:pwd@localhost:5432/siged_test python -m pytest -q   # PostgreSQL
```

78 tests, organisés par sprint (`tests/test_sprintN_*.py`) + mode serverless (`tests/test_deploiement_vercel.py`). Les tests de conversion sont ignorés automatiquement si OCRmyPDF, Ghostscript ou LibreOffice sont absents.

## Arborescence

```
siged/
├── backend/
│   ├── app/            api/ (routes) · services/ (métier) · core/ (config, sécurité, chiffrement) · jobs/ (worker) · static/ (IHM)
│   ├── sql/            objets PostgreSQL (index plein texte, déclencheurs d'audit)
│   ├── scripts/        données de démonstration
│   └── tests/          tests par sprint
├── deploy/             caddy (HTTPS, TLS 1.3), oracle (scripts serveur), sauvegarde, restauration
├── docs/
│   ├── deploiement_oracle.md · guide_secrets.md
│   ├── cahier_architecture.md / .docx / .pdf
│   ├── rapports/       rapports des sprints 0 à 7 + rapport final de recette
│   ├── diagrammes/     sources Mermaid + PNG
│   ├── captures/       captures d'écran
│   └── openapi.json    contrat d'API
├── docker-compose.yml  ·  .env.example  ·  Makefile  ·  .github/workflows/ci.yml
```
