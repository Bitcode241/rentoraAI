# Deployment Guide

## Production checklist

- [ ] Set a strong `JWT_SECRET`.
- [ ] Set `ENVIRONMENT=production` and `DEBUG=false` (enables JSON logs).
- [ ] Replace the default `admin` user.
- [ ] Put the app behind a TLS-terminating reverse proxy (Nginx/Caddy/Traefik).
- [ ] Configure backups (see below).
- [ ] Restrict CORS origins if the dashboard is served from a fixed domain.

## Reverse proxy (example, Caddy)

```
rental.example.com {
    reverse_proxy localhost:8000
}
```

## Scaling workers

Set `WEB_CONCURRENCY` (read by the entrypoint) to run multiple Uvicorn workers:

```yaml
environment:
  - WEB_CONCURRENCY=4
```

> Note: with multiple workers, prefer PostgreSQL over SQLite.

## Migrating to PostgreSQL

1. Stand up a Postgres instance (e.g. add a `db` service in compose).
2. Set `DATABASE_URL=postgresql+psycopg2://user:pass@db:5432/rental`.
3. Add `psycopg2-binary` to `requirements.txt`.
4. Run `alembic upgrade head` against the new database.

The ORM models and migrations are database-agnostic; only the URL changes.

## Logging

Structured logs go to stdout (captured by Docker / your log driver). In
production (`DEBUG=false`) they are emitted as JSON for ingestion by log
aggregators. A persistent `logs` volume is mounted for any file-based output.

## Backups

Manual:

```bash
./scripts/backup.sh            # local data dir
./scripts/backup_docker.sh     # from the running container's volume
```

Restore:

```bash
./scripts/restore.sh backups/rental_YYYYMMDD_HHMMSS.db
docker compose restart api
```

Schedule with cron (host):

```
0 3 * * * cd /opt/rental-os && ./scripts/backup_docker.sh >> logs/backup.log 2>&1
```

## Health & monitoring

- `GET /health` returns `{"status":"healthy"}` and is wired into the Docker
  healthcheck.
- Audit events (booking create/confirm/cancel) are written to the `audit_logs`
  table.

## Security notes

- JWT auth with `admin` / `staff` roles; asset mutation is admin-only.
- Rate limiting via SlowAPI (`RATE_LIMIT`, default `100/minute`).
- Input validation through Pydantic schemas on every endpoint.
