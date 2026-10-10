#!/bin/sh
# Sauvegarde quotidienne (01:00) : dump PostgreSQL + archive des objets MinIO (déjà chiffrés AES-256).
# Rétention : 30 sauvegardes quotidiennes. À compléter par une copie hors site (règle 3-2-1).
set -e
while true; do
  now=$(date +%H%M)
  if [ "$now" = "0100" ]; then
    stamp=$(date +%Y%m%d-%H%M)
    mkdir -p /backups/$stamp
    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /backups/$stamp/siged.dump
    tar -czf /backups/$stamp/objets.tar.gz -C /minio-data .
    sha256sum /backups/$stamp/* > /backups/$stamp/SHA256SUMS
    ls -1d /backups/*/ | sort | head -n -30 | xargs -r rm -rf
    echo "Sauvegarde $stamp terminée"
    sleep 61
  fi
  sleep 30
done
