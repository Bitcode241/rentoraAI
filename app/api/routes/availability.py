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
