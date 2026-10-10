#!/usr/bin/env bash
# Construit et démarre SIGED, puis vérifie qu'il répond.   Usage : bash deploy/oracle/demarrer.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

[ -f .env ] || { echo "ERREUR : fichier .env absent (voir docs/guide_secrets.md)"; exit 1; }
domain=$(grep -E '^SIGED_DOMAIN=' .env | cut -d= -f2- | tr -d '[:space:]' || true)
[ -n "$domain" ] || { echo "ERREUR : ajoutez SIGED_DOMAIN=votre-domaine dans .env"; exit 1; }
grep -qE '^SIGED_STORAGE_ENCRYPTION_KEY=.{40,}' .env || { echo "ERREUR : SIGED_STORAGE_ENCRYPTION_KEY vide dans .env"; exit 1; }

echo "==> Construction de l'image et démarrage (la 1re fois : 10 à 20 minutes)"
docker compose up -d --build

echo "==> Attente de l'application"
for i in $(seq 1 60); do
    if curl -fsk --resolve "$domain:443:127.0.0.1" "https://$domain/health" >/dev/null 2>&1; then
        echo "SIGED est en ligne : https://$domain"
        curl -sk --resolve "$domain:443:127.0.0.1" "https://$domain/health"; echo
        exit 0
    fi
    sleep 5
done
echo "L'application ne répond pas encore. Diagnostic : docker compose ps   puis   docker compose logs --tail 50 api caddy"
exit 1
