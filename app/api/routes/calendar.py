from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.booking import Booking
from app.models.asset import Asset
from app.models.customer import Customer

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

ACTIVE = ("pending", "confirmed", "completed")


@router.get("")
def calendar(start: Optional[str] = None, end: Optional[str] = None,
             asset_type: Optional[str] = None,
             db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Return assets (as rows) and their bookings in a date range (as events).
    Used by the visual scheduler in the dashboard."""
    now = datetime.utcnow()
    if start:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    else:
        start_dt = now - timedelta(days=now.weekday())
    if end:
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    else:
        end_dt = start_dt + timedelta(days=14)

    aq = db.query(Asset).filter(Asset.active.is_(True))
    if asset_type:
        aq = aq.filter(Asset.asset_type == asset_type)
    assets = aq.order_by(Asset.asset_type, Asset.name).all()
    asset_ids = [a.id for a in assets]

    events = []
    if asset_ids:
        bookings = db.query(Booking).filter(
            Booking.asset_id.in_(asset_ids),
            Booking.status.in_(ACTIVE),
            and_(Booking.start_datetime < end_dt, Booking.end_datetime > start_dt),
        ).all()
        cust_ids = {b.customer_id for b in bookings}
        custs = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all()} if cust_ids else {}
        for b in bookings:
            c = custs.get(b.customer_id)
            events.append({
                "id": b.id,
                "asset_id": b.asset_id,
                "title": (c.full_name if c else "—"),
                "package": b.package_name or "",
                "start": b.start_datetime.isoformat(),
                "end": b.end_datetime.isoformat(),
                "status": b.status,
                "total_price": b.total_price,
            })

    return {
        "range": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        "assets": [{"id": a.id, "name": a.name, "type": a.asset_type,
                    "capacity": a.capacity} for a in assets],
        "events": events,
    }
