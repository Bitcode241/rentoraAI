#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Preparing data/logs directories..."
mkdir -p /app/data /app/logs

# --- Wait for the database to accept connections (Postgres in prod) ---
# Parse host:port from DATABASE_URL if it's postgres; SQLite needs no waiting.
if [[ "${DATABASE_URL:-}" == postgresql* ]]; then
    echo "[entrypoint] Waiting for PostgreSQL to be ready..."
    python - <<'PYWAIT'
import os, time, sys, re
url = os.environ.get("DATABASE_URL", "")
m = re.search(r"@([^:/]+)(?::(\d+))?/", url)
host = m.group(1) if m else "db"
port = int(m.group(2)) if (m and m.group(2)) else 5432
import socket
for i in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint] DB reachable at {host}:{port}")
            sys.exit(0)
    except OSError:
        print(f"[entrypoint] DB not ready ({i+1}/30), retrying...")
        time.sleep(2)
print("[entrypoint] DB never became reachable", file=sys.stderr)
sys.exit(1)
PYWAIT
fi

# --- Run migrations. If they FAIL, stop — do NOT start the app half-migrated. ---
echo "[entrypoint] Running Alembic migrations..."
if ! alembic upgrade head; then
    echo "[entrypoint] ERROR: Alembic migrations failed. Refusing to start." >&2
    echo "[entrypoint] Fix the migration, then restart. The app was NOT started" >&2
    echo "[entrypoint] so the database is never left in a half-applied state." >&2
    exit 1
fi
echo "[entrypoint] Migrations OK."

echo "[entrypoint] Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-1}"
