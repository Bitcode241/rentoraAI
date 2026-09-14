"""API keys for external integrations (an AI assistant, a website, a partner).

Security choices worth stating:

* The raw key is returned once, at creation, and only its SHA-256 hash is stored.
  A database leak therefore does not hand over working keys.
* Every key belongs to exactly one tenant. Using it sets the tenant context, so
  the same isolation that protects the admin protects the API.
* Scopes are checked per request: a `read` key cannot create bookings even if it
  finds the endpoint.
"""
import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.api_key import ApiKey

log = get_logger(__name__)

SCOPES = {
    "read": "Čitanje (kalendar, cijene, rezervacije)",
    "write": "Stvaranje i izmjena rezervacija",
}
PREFIX = "rok_"          # rentora operator key


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue(db: Session, *, name: str, scopes: str = "read",
          tenant_id: int = None) -> tuple:
    """Create a key. Returns (ApiKey, raw_key) — the raw value is never stored."""
    from app.core.tenancy import get_tenant, DEFAULT_TENANT_ID
    raw = PREFIX + secrets.token_urlsafe(32)
    wanted = [s.strip() for s in (scopes or "read").split(",") if s.strip() in SCOPES]
    row = ApiKey(
        name=(name or "Integracija")[:120],
        prefix=raw[:12],
        key_hash=_hash(raw),
        scopes=",".join(wanted or ["read"]),
        active=True,
        tenant_id=tenant_id or get_tenant() or DEFAULT_TENANT_ID,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log.info("api_key_issued", key_id=row.id, name=row.name, scopes=row.scopes)
    return row, raw


def verify(db: Session, raw: str):
    """Return the ApiKey for a raw key, or None. Also records usage."""
    if not raw or not raw.startswith(PREFIX):
        return None
    from app.core.tenancy import all_tenants
    with all_tenants(db):         # we don't know the tenant until we find the key
        row = (db.query(ApiKey)
               .filter(ApiKey.key_hash == _hash(raw), ApiKey.active == True)  # noqa: E712
               .first())
        if not row:
            return None
        row.last_used_at = datetime.now(timezone.utc)
        row.calls = (row.calls or 0) + 1
        db.commit()
    return row


def has_scope(row, scope: str) -> bool:
    return scope in [s.strip() for s in (row.scopes or "").split(",")]


def revoke(db: Session, key_id: int) -> bool:
    row = db.get(ApiKey, key_id)
    if not row:
        return False
    row.active = False
    db.commit()
    log.info("api_key_revoked", key_id=key_id)
    return True
