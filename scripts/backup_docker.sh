#!/usr/bin/env bash
# Backup directly from the running Docker volume.
set -e
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p ./backups
docker compose exec -T api sqlite3 /app/data/rental.db ".backup '/app/data/backup_$STAMP.db'"
docker compose cp api:/app/data/backup_$STAMP.db ./backups/rental_$STAMP.db
docker compose exec -T api rm -f /app/data/backup_$STAMP.db
echo "[backup] -> ./backups/rental_$STAMP.db"
