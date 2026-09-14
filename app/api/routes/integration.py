"""Integration API — what an external assistant or website talks to.

Authenticate with a header:  X-API-Key: rok_...

Everything is scoped to the key's business. A `read` key can look at the
calendar, prices and bookings; creating a booking needs `write`.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.tenancy import set_tenant
from app.services import api_key_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["integration-api"])


def api_key(x_api_key: str = Header(None, alias="X-API-Key"),
            db: Session = Depends(get_db)):
    """Authenticate the caller and scope the request to their business."""
    row = api_key_service.verify(db, x_api_key or "")
    if not row:
        raise HTTPException(401, "Neispravan ili nedostaje X-API-Key.")
    set_tenant(row.tenant_id, db)
    return row


def needs(scope: str):
    def _dep(key=Depends(api_key)):
        if not api_key_service.has_scope(key, scope):
            raise HTTPException(403, f"Ključ nema ovlast '{scope}'.")
        return key
    return _dep


read_key = needs("read")
write_key = needs("write")


# ---------------------------------------------------------------- catalogue --

@router.get("/ping")
def ping(key=Depends(read_key)):
    """Cheap call to confirm the key works."""
    return {"ok": True, "business_id": key.tenant_id, "name": key.name,
            "scopes": key.scopes.split(",")}


@router.get("/tours")
def tours(asset_type: str = "", db: Session = Depends(get_db),
          key=Depends(read_key)):
    """What can be booked, with current prices and durations."""
    from app.models.tour_type import TourType
    q = db.query(TourType).filter(TourType.active == True)  # noqa: E712
    if asset_type:
        q = q.filter(TourType.asset_type == asset_type)
    rows = q.order_by(TourType.asset_type, TourType.sort_order).all()
    return {"tours": [{
        "id": t.id, "name": t.name, "asset_type": t.asset_type,
        "duration_minutes": t.duration_minutes, "price": t.price,
        "deposit_percent": t.deposit_percent, "guided": bool(t.guided),
        "description": t.description or ""} for t in rows]}


@router.get("/transfers")
def transfers(db: Session = Depends(get_db), key=Depends(read_key)):
    from app.models.transfer import TransferZone
    rows = (db.query(TransferZone)
            .filter(TransferZone.active == True)  # noqa: E712
            .order_by(TransferZone.sort_order).all())
    return {"zones": [{"id": z.id, "name": z.name, "car_price": z.car_price,
                       "van_price": z.van_price} for z in rows]}


@router.get("/fleet")
def fleet(db: Session = Depends(get_db), key=Depends(read_key)):
    from app.models.asset import Asset
    rows = db.query(Asset).filter(Asset.active == True).all()  # noqa: E712
    return {"assets": [{"id": a.id, "name": a.name, "type": a.asset_type,
                        "capacity": a.capacity,
                        "out_of_service": bool(a.out_of_service)} for a in rows]}


# -------------------------------------------------------------- availability --

@router.get("/availability")
def availability(asset_type: str = "jetski", date: str = "",
                 days: int = 7, db: Session = Depends(get_db),
                 key=Depends(read_key)):
    """Free units per hour — the question "is Tuesday at 11 free?"."""
    from app.api.routes.dashboard import dashboard_free
    if days < 1 or days > 60:
        raise HTTPException(400, "days mora biti 1–60.")
    return dashboard_free(asset_type=asset_type, days=days, db=db, _=key)


@router.get("/day")
def day(date: str = "", db: Session = Depends(get_db), key=Depends(read_key)):
    """Everything happening on one day: who, when, contact, what's owed."""
    from app.api.routes.dashboard import dashboard_day
    return dashboard_day(date=date, db=db, _=key)


@router.get("/bookings")
def bookings(days_ahead: int = 30, db: Session = Depends(get_db),
             key=Depends(read_key)):
    """Upcoming bookings with guest details and payment state."""
    from app.models.booking import Booking
    from app.models.customer import Customer
    from app.models.asset import Asset
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=max(1, min(days_ahead, 365)))
    rows = (db.query(Booking)
            .filter(Booking.start_datetime >= now - timedelta(days=1),
                    Booking.start_datetime <= until,
                    Booking.status != "cancelled")
            .order_by(Booking.start_datetime).all())
    custs = {c.id: c for c in db.query(Customer).all()}
    assets = {a.id: a for a in db.query(Asset).all()}
    out = []
    for b in rows:
        c = custs.get(b.customer_id)
        a = assets.get(b.asset_id)
        paid = (b.amount_paid or 0) + (getattr(b, "cash_collected", 0) or 0)
        out.append({
            "id": b.id,
            "start": b.start_datetime, "end": b.end_datetime,
            "tour": b.package_name or "",
            "asset": (a.name if a else ""), "asset_type": (a.asset_type if a else ""),
            "guest": {"name": (c.full_name if c else ""),
                      "phone": (c.phone if c else ""),
                      "email": (c.email if c else "")},
            "passengers": getattr(b, "passengers", 0) or 0,
            "total": round(b.total_price or 0, 2),
            "paid": round(paid, 2),
            "balance": round(max((b.total_price or 0) - paid, 0), 2),
            "status": b.status, "payment_status": b.payment_status,
            "pickup": getattr(b, "pickup_location", "") or "",
        })
    return {"count": len(out), "bookings": out}


# -------------------------------------------------------------------- write --

@router.post("/bookings")
def create_booking(payload: dict, db: Session = Depends(get_db),
                   key=Depends(write_key)):
    """Create a booking. Same rules as the admin: availability and blocks apply."""
    from app.api.routes.bookings import quick_booking
    from app.services import audit
    res = quick_booking(payload, db=db, _=key)
    audit.record(db, "api_booking_created", actor=f"api:{key.name}",
                 entity="booking",
                 entity_id=",".join(str(i) for i in res.get("booking_ids", [])),
                 detail=f"{res.get('count')}× {res.get('tour')} "
                        f"· {res.get('total')} EUR")
    return res


@router.post("/bookings/{booking_id}/move")
def move(booking_id: int, payload: dict, db: Session = Depends(get_db),
         key=Depends(write_key)):
    from app.api.routes.bookings import move_booking
    return move_booking(booking_id, payload, db=db, _=key)


@router.post("/bookings/{booking_id}/cash")
def cash(booking_id: int, payload: dict, db: Session = Depends(get_db),
         key=Depends(write_key)):
    from app.api.routes.bookings import record_cash
    return record_cash(booking_id, payload, db=db, _=key)
