#!/usr/bin/env bash
# Restore a database backup. Usage: ./scripts/restore.sh backups/rental_XXXX.db
set -e
SRC="$1"
DATA_DIR="${DATA_DIR:-./data}"
if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
    echo "Usage: $0 <path-to-backup.db>"
    exit 1
fi
mkdir -p "$DATA_DIR"
cp "$SRC" "$DATA_DIR/rental.db"
echo "[restore] Restored $SRC -> $DATA_DIR/rental.db"
echo "[restore] Restart the app: docker compose restart api"
