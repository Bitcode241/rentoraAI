# Faza 0 + Faza 1 — što je dodano

## Faza 0 — PostgreSQL

- `docker-compose.yml` sada diže **Postgres 16** servis (`db`) i API čeka da baza
  bude spremna prije pokretanja.
- Za produkciju u `.env` postavi:
  ```
  DATABASE_URL=postgresql+psycopg2://rental:rental_pass@db:5432/rental
  POSTGRES_USER=rental
  POSTGRES_PASSWORD=postavi-jaku-lozinku
  POSTGRES_DB=rental
  ```
- Za lokalno testiranje ostavi SQLite (default) — ništa ne treba mijenjati.
- Migracije rade na obje baze: `alembic upgrade head`.

## Faza 1 — AI + automatska obrada maila

### 1. Email preko IMAP/SMTP (mailcow)
Univerzalni IMAP/SMTP modul zamjenjuje vezanost za Gmail. Radi s mailcowom,
mailom na vlastitoj domeni, ili Gmailom. U `.env`:
```
EMAIL_IMAP_HOST=mail.tvojadomena.com
EMAIL_IMAP_PORT=993
EMAIL_SMTP_HOST=mail.tvojadomena.com
EMAIL_SMTP_PORT=465
EMAIL_USERNAME=info@tvojadomena.com
EMAIL_PASSWORD=lozinka
EMAIL_FROM=info@tvojadomena.com
EMAIL_USE_SSL=true
```
Ako ostaviš prazno, email radi u **simulacijskom modu** (samo logira) — sustav se
i dalje pokreće normalno.

### 2. Automatska obrada (scheduler)
Pozadinski scheduler svakih `EMAIL_POLL_SECONDS` sekundi pročita nove mailove,
prepozna namjeru (upit / potvrda / otkazivanje) na HR/DE/EN, i pusti AI agenta da
odgovori.
```
SCHEDULER_ENABLED=true
EMAIL_POLL_SECONDS=120
```
> Pri više workera, pokreni scheduler u jednom procesu (WEB_CONCURRENCY=1 na API
> servisu, ili odvojeni worker). Za tvoj volumen 1 worker je sasvim dovoljan.

### 3. Prag eskalacije (Rule 8)
- `AI_AUTO_SEND=true` — AI šalje odgovore sam kad je siguran.
- `AI_AUTO_SEND=false` — AI samo **priprema nacrt**, ništa se ne šalje dok ti ne
  pregledaš (sigurni mod dok gradiš povjerenje).
- Kad AI nije siguran, sam označi razgovor za ljudski pregled.

Korisni endpointi:
- `GET  /api/emails/status` — koji email provider je aktivan, je li AI upaljen.
- `POST /api/emails/process` — ručno pokreni obradu (osim schedulera).
- `GET  /api/emails/needs-human` — razgovori koje je AI eskalirao.
- `POST /api/emails/needs-human/{customer_id}/resolve` — označi kao riješeno.

### Uključivanje pravog AI-a
Stavi `OPENAI_API_KEY` u `.env`. Bez ključa AI radi u sigurnom fallbacku koji
nikad ne izmišlja podatke i sve šalje na ljudski pregled.
