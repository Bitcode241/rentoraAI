# AI Rental Operating System

A production-grade backend + admin dashboard that acts as the **central source of
truth** for a business renting **boats, jet skis, cars, and vans**. It automates
booking management and customer communication across **email and WhatsApp**, with
**AI agents** that never guess availability or prices.

## Key principles

- **Single source of truth.** Availability always comes from the database and
  Google Calendar — never from the AI's imagination.
- **Business rules enforced in code**, not prompts: capacity filtering,
  no overlapping bookings, calendar checks before confirmation, calendar event
  creation, never inventing prices/availability, reply in the customer's language,
  and escalation to a human on low confidence.

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · SQLite (Postgres-ready) ·
Docker / Compose · Google Calendar API · Gmail API · WhatsApp Cloud API ·
OpenAI-compatible agents · JWT auth · structured logging.

## Quick start (Docker)

```bash
cp .env.example .env          # then edit secrets
docker compose up -d --build
```

Then open:

- API root:      http://localhost:8000
- Swagger docs:  http://localhost:8000/docs
- Admin console: http://localhost:8000/admin

Default login: **admin / admin123** (change immediately in production).

## Quick start (local, no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

## Running without external credentials

The system is designed to run **out of the box**:

- **No OpenAI key?** The AI agent runs in a safe deterministic fallback that never
  invents data and escalates to a human.
- **No Google credentials?** Calendar checks pass through (the database still
  enforces no-overlap) and emails are simulated/logged.
- **No WhatsApp token?** Outbound messages are logged instead of sent.

Add real credentials in `.env` to switch each integration on.

## Tests

```bash
pytest -q
```

## Project layout

```
app/
  core/          config, database, security (JWT), logging
  models/        SQLAlchemy ORM models
  schemas/       Pydantic request/response models
  services/      availability, pricing, bookings, reporting, conversations, audit
  integrations/  Google Calendar, Gmail, WhatsApp (graceful fallbacks)
  ai/            agent loop, callable tools, email intent processor
  api/routes/    auth, assets, customers, bookings, availability,
                 messages, emails, reports, webhooks, dashboard
  static/        admin dashboard (HTML/CSS/JS)
  bootstrap.py   seeds admin user + demo fleet
  main.py        FastAPI app
alembic/         migrations
scripts/         entrypoint, backup, restore
tests/           pytest suite
```

See `docs/INSTALL.md` and `docs/DEPLOY.md` for details.
