from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.roles import require
from app.models.api_key import ApiKey
from app.services import api_key_service

router = APIRouter(prefix="/api/keys", tags=["api-keys"])
# issuing a key grants access to the whole business — owner-level only
require_keys = require("platform")


@router.get("")
def list_keys(db: Session = Depends(get_db), _=Depends(require_keys)):
    rows = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return {"scopes": api_key_service.SCOPES,
            "keys": [{"id": k.id, "name": k.name, "prefix": k.prefix,
                      "scopes": k.scopes.split(","), "active": bool(k.active),
                      "calls": k.calls or 0, "last_used_at": k.last_used_at,
                      "created_at": k.created_at} for k in rows]}


@router.post("")
def create_key(payload: dict, db: Session = Depends(get_db),
               _=Depends(require_keys)):
    """Issue a key. The raw value is returned ONCE and never stored."""
    from app.services import audit
    name = (payload.get("name") or "").strip()
    if len(name) < 3:
        raise HTTPException(400, "Naziv mora imati barem 3 znaka.")
    scopes = payload.get("scopes") or ["read"]
    if isinstance(scopes, list):
        scopes = ",".join(scopes)
    row, raw = api_key_service.issue(db, name=name, scopes=scopes)
    audit.record(db, "api_key_issued", actor=getattr(_, "username", "admin"),
                 entity="api_key", entity_id=row.id,
                 detail=f"{name} — ovlasti: {row.scopes}")
    return {"ok": True, "id": row.id, "name": row.name,
            "scopes": row.scopes.split(","),
            "key": raw,
            "warning": "Ključ se prikazuje samo sada. Spremi ga na sigurno."}


@router.delete("/{key_id}")
def revoke_key(key_id: int, db: Session = Depends(get_db),
               _=Depends(require_keys)):
    from app.services import audit
    if not api_key_service.revoke(db, key_id):
        raise HTTPException(404, "Ključ nije pronađen.")
    audit.record(db, "api_key_revoked", actor=getattr(_, "username", "admin"),
                 entity="api_key", entity_id=key_id, detail="Ključ opozvan")
    return {"ok": True}
