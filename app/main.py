import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.database import Base, engine, SessionLocal
from app.api.routes import (auth, assets, customers, bookings, availability,
                            messages, emails, reports, webhooks, dashboard, packages,
                            transfers, calendar, mailboxes, payments, settings as settings_routes,
                            addons, public_booking)

configure_logging(settings.debug)
log = get_logger("main")

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    from app.bootstrap import seed
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    log.info("startup_complete", env=settings.environment)
    from app.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan,
              description="AI Rental Operating System — boats, jet skis, cars, vans.")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

app.mount("/static", StaticFiles(directory="app/static"), name="static")

for r in (auth, assets, customers, bookings, availability, messages,
          emails, reports, webhooks, dashboard, packages, transfers, calendar, mailboxes, payments, settings_routes, addons, public_booking):
    app.include_router(r.router)


@app.get("/")
def root():
    return {"app": settings.app_name, "docs": "/docs", "admin": "/admin", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


def _pay_page(title: str, msg: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(f"""<!doctype html><html lang="hr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;background:#0f6a7d;color:#fff;display:flex;
min-height:100vh;align-items:center;justify-content:center;margin:0}}.card{{background:#fff;
color:#0d2b32;padding:40px;border-radius:14px;max-width:420px;text-align:center;
box-shadow:0 10px 40px rgba(0,0,0,.2)}}h1{{margin:0 0 12px;font-size:22px}}
p{{color:#5a6b6f;line-height:1.5}}</style></head><body><div class="card">
<h1>{title}</h1><p>{msg}</p></div></body></html>""")


@app.get("/pay/success")
def pay_success(booking: int = 0):
    from app.core.database import SessionLocal
    from app.models.booking import Booking
    from app.models.customer import Customer
    msgs = {
        "hr": ("Hvala! Depozit je zaprimljen.", "Vaša rezervacija je potvrđena. Potvrdu smo poslali na Vaš email."),
        "en": ("Thank you! Your deposit has been received.", "Your booking is confirmed. We've emailed you the confirmation."),
        "de": ("Vielen Dank! Ihre Anzahlung ist eingegangen.", "Ihre Buchung ist bestätigt. Die Bestätigung wurde per E-Mail gesendet."),
    }
    lang = "en"
    if booking:
        try:
            db = SessionLocal()
            b = db.get(Booking, booking)
            if b:
                c = db.get(Customer, b.customer_id)
                if c and c.language:
                    lang = c.language.lower()[:2]
            db.close()
        except Exception:
            pass
    title, msg = msgs.get(lang, msgs["en"])
    return _pay_page(title, msg)


@app.get("/pay/cancel")
def pay_cancel():
    return _pay_page("Plaćanje otkazano / Payment cancelled",
                     "Rezervacija nije potvrđena. / Booking not confirmed.")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.error("unhandled_error", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
