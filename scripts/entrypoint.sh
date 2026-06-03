#!/usr/bin/env bash
set -e

echo "[entrypoint] Preparing data/logs directories..."
mkdir -p /app/data /app/logs

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head || {
    echo "[entrypoint] Alembic failed; falling back to metadata create_all (dev)."
}

echo "[entrypoint] Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-1}"
