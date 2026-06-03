#!/usr/bin/env bash
# Backup the SQLite database and logs into a timestamped archive.
set -e

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DATA_DIR="${DATA_DIR:-./data}"
LOG_DIR="${LOG_DIR:-./logs}"
STAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

if [ -f "$DATA_DIR/rental.db" ]; then
    # Use SQLite's online backup if available, else copy.
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$DATA_DIR/rental.db" ".backup '$BACKUP_DIR/rental_$STAMP.db'"
    else
        cp "$DATA_DIR/rental.db" "$BACKUP_DIR/rental_$STAMP.db"
    fi
    echo "[backup] Database -> $BACKUP_DIR/rental_$STAMP.db"
fi

tar -czf "$BACKUP_DIR/rental_backup_$STAMP.tar.gz" \
    -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")" \
    $( [ -d "$LOG_DIR" ] && echo "-C $(dirname "$LOG_DIR") $(basename "$LOG_DIR")" )
echo "[backup] Full archive -> $BACKUP_DIR/rental_backup_$STAMP.tar.gz"

# Retention: keep last 14 archives
ls -1t "$BACKUP_DIR"/rental_backup_*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "[backup] Done."
