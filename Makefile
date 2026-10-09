.PHONY: dev test test-pg up down certs demo

dev:            ## API en local (SQLite + stockage disque chiffré)
	cd backend && uvicorn app.main:app --reload

test:           ## Tests (SQLite)
	cd backend && python -m pytest -q

test-pg:        ## Tests sur PostgreSQL (SIGED_TEST_DATABASE_URL requis)
	cd backend && python -m pytest -q

certs:          ## Certificat TLS de test
	sh deploy/scripts/gen-certs.sh

up: certs       ## Déploiement complet (Docker)
	docker compose up -d --build

down:
	docker compose down

demo:           ## Données de démonstration
	cd backend && python -m scripts.demo_data --url https://localhost --insecure
