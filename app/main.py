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
                            transfers)

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
          emails, reports, webhooks, dashboard, packages, transfers):
    app.include_router(r.router)


@app.get("/")
def root():
    return {"app": settings.app_name, "docs": "/docs", "admin": "/admin", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.error("unhandled_error", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
