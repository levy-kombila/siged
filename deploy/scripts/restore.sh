#!/bin/sh
# Restauration : ./restore.sh 20261009-0100   (services api/worker arrêtés)
set -e
dir=/backups/$1
cd "$dir" && sha256sum -c SHA256SUMS
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists siged.dump
echo "Base restaurée. Restaurer les fichiers : docker compose run --rm -v siged_storage:/restore backup tar -xzf $dir/fichiers.tar.gz -C /restore"
echo "Puis lancer un contrôle d'intégrité : POST /api/admin/integrity/run"
