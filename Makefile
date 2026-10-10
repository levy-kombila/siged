.PHONY: dev test test-pg up down logs demo secrets

dev:            ## API en local (SQLite + stockage disque chiffré)
	cd backend && uvicorn app.main:app --reload

test:           ## Tests (SQLite)
	cd backend && python -m pytest -q

test-pg:        ## Tests sur PostgreSQL (SIGED_TEST_DATABASE_URL requis)
	cd backend && python -m pytest -q

secrets:        ## Affiche des secrets aléatoires à recopier dans .env
	python3 backend/scripts/generer_secrets.py

up:             ## Déploiement complet (Docker + HTTPS automatique Caddy)
	docker compose up -d --build

logs:
	docker compose logs -f --tail 100 api worker caddy

down:
	docker compose down

demo:           ## Données de démonstration
	cd backend && python -m scripts.demo_data --url https://localhost --insecure
