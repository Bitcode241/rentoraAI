# Installation Guide

## 1. Prerequisites

- Docker + Docker Compose (recommended), **or**
- Python 3.12 for a local install.

## 2. Configuration

Copy the example environment file and edit it:

```bash
cp .env.example .env
```

Important values:

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET` | **Must change** to a long random string in production. |
| `DATABASE_URL` | `sqlite:///./data/rental.db` by default; switch to Postgres later. |
| `OPENAI_API_KEY` | Optional. Blank = safe deterministic AI fallback. |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | Point at any OpenAI-compatible endpoint. |
| `GOOGLE_CREDENTIALS_FILE` | Path to an OAuth client secret JSON (Calendar + Gmail). |
| `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_ID` | WhatsApp Cloud API credentials. |

## 3. Run with Docker

```bash
docker compose up -d --build
docker compose logs -f api      # follow logs
```

The container runs Alembic migrations on startup, seeds the admin user and a
demo fleet, then serves on port 8000.

## 4. Run locally (no Docker)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m scripts.seed_fleet
uvicorn app.main:app --reload
```

## 5. First login

- Open http://localhost:8000/admin
- Sign in with `admin` / `admin123`
- **Change the password / create your own admin user** via
  `POST /api/auth/users` (admin only), then disable the default.

## 6. Connecting Google (Calendar + Gmail)

1. In Google Cloud Console, create OAuth credentials (Desktop app) with the
   Calendar and Gmail scopes enabled.
2. Download the client secret as `credentials.json` in the project root.
3. Uncomment the credentials volume mount in `docker-compose.yml`.
4. On first run, complete the OAuth flow; a `data/token.json` is stored and
   reused thereafter.

Each asset has its own `calendar_id` (editable in the Assets page). Availability
is checked against that calendar before every confirmation, and a calendar event
is created when a booking is confirmed.

## 7. Connecting WhatsApp

Set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, and `WHATSAPP_VERIFY_TOKEN`. Point your
Meta webhook to `POST /api/webhooks/whatsapp`; verification uses
`GET /api/webhooks/whatsapp`.

## 8. Processing email

Call `POST /api/emails/process` (or wire it to a scheduler/cron) to pull unread
Gmail messages, detect intent (request / confirmation / cancellation), store the
thread, and let the AI agent draft a reply.
