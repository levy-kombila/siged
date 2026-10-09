#!/usr/bin/env bash
# Récupère la dernière version depuis GitHub et redémarre.   Usage : bash deploy/oracle/mettre-a-jour.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
