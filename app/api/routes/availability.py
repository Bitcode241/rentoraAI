from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas import AvailabilityQuery
from app.services import availability

router = APIRouter(prefix="/api/availability", tags=["availability"])


@router.post("")
def query_availability(payload: AvailabilityQuery, db: Session = Depends(get_db),
                       _=Depends(get_current_user)):
    results = availability.find_available(
        db, payload.asset_type, payload.passengers,
        payload.start_datetime, payload.end_datetime)
    from app.services import pricing
    return [{
        "asset_id": r["asset"].id, "name": r["asset"].name,
        "capacity": r["asset"].capacity,
        "packages": pricing.list_packages(r["asset"]),
        "quote": r.get("quote"),
    } for r in results]


@router.get("/check")
def check_one(asset_id: int, start: str, end: str,
              db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Is a specific asset free in the given window? For admin booking warnings."""
    from datetime import datetime
    from app.models.asset import Asset
    from dateutil import parser as dtp
    asset = db.get(Asset, asset_id)
    if not asset:
        return {"available": False, "error": "asset_not_found"}
    try:
        s = dtp.parse(start)
        e = dtp.parse(end)
    except Exception:
        return {"available": True}  # don't block on parse issues
    ok = availability.is_asset_available(db, asset, s, e)
    return {"available": bool(ok)}
