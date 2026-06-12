from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.booking import Booking
from app.schemas import BookingCreate, BookingUpdate, BookingOut
from app.services import booking_service

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


@router.get("", response_model=List[BookingOut])
def list_bookings(status: Optional[str] = None, db: Session = Depends(get_db),
                  _=Depends(get_current_user)):
    q = db.query(Booking)
    if status:
        q = q.filter(Booking.status == status)
    return q.order_by(Booking.start_datetime.desc()).all()


@router.post("", response_model=BookingOut)
def create_booking(payload: BookingCreate, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    b = booking_service.create_booking(
        db, payload.asset_id, payload.customer_id,
        payload.start_datetime, payload.end_datetime,
        source=payload.source, notes=payload.notes, actor=user.username,
        package_id=payload.package_id, passengers=payload.passengers or 0)
    # admin can mark "pays on boat" (partner collects, we invoice later)
    if payload.payment_status:
        b.payment_status = payload.payment_status
    # pickup: use what was entered, else fall back to the asset's default pickup
    pickup = (payload.pickup_location or "").strip()
    if not pickup:
        from app.models.asset import Asset
        a = db.get(Asset, payload.asset_id)
        pickup = (getattr(a, "default_pickup", "") or "") if a else ""
    if pickup:
        b.pickup_location = pickup
    # manual deposit override
    if payload.deposit_amount is not None:
        b.deposit_amount = payload.deposit_amount
    db.commit()
    db.refresh(b)
    return b


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    return b


@router.post("/{booking_id}/confirm", response_model=BookingOut)
def confirm_booking(booking_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return booking_service.confirm_booking(db, booking_id, actor=user.username)


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return booking_service.cancel_booking(db, booking_id, actor=user.username)


@router.patch("/{booking_id}", response_model=BookingOut)
def update_booking(booking_id: int, payload: BookingUpdate,
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(b, k, v)
    db.commit()
    db.refresh(b)
    return b


@router.get("/{booking_id}/voucher")
def partner_voucher(booking_id: int, token: str = "",
                    db: Session = Depends(get_db)):
    """Generate the partner voucher PDF for a booking (external/partner boats).
    Accepts the auth token as a query param so it can open in a new browser tab."""
    from fastapi import Response
    from app.core.security import decode_token
    from app.models.user import User
    # authenticate via query token (new-tab friendly)
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(401, "Unauthorized")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Unauthorized")
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.services import voucher_service
    from app.services.external_service import settlement
    from app.core.config import settings as cfg
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    asset = db.get(Asset, b.asset_id)
    cust = db.get(Customer, b.customer_id)
    from app.core.timeutil import fmt_local
    # show local time (Europe/Zagreb), with end time, so 18:30 reads 18:30
    when = fmt_local(b.start_datetime)
    if b.end_datetime:
        when += "–" + fmt_local(b.end_datetime, "%H:%M")
    tour = b.package_name or ""
    st_summary = ""
    if asset and getattr(asset, "is_external", False):
        st = settlement(b.total_price or 0, asset.commission_percent or 0,
                        getattr(asset, "payment_direction", "you"))
        st_summary = st["summary"]
    gname = (cust.full_name if cust and cust.full_name and
             cust.full_name != (cust.email or "") else "")
    # what the partner must collect from the guest in cash = total - already paid to us
    total = b.total_price or 0
    paid = b.amount_paid or 0
    balance = max(total - paid, 0) if paid > 0 else 0
    from app.services import settings_service
    biz = settings_service.brand_for_type(db, asset.asset_type if asset else "")
    pdf = voucher_service.build_voucher(
        business_name=biz,
        booking_id=b.id, asset_name=asset.name if asset else "—", when=when,
        tour_name=tour,
        guests=getattr(b, "passengers", 0) or "—",
        guest_name=gname, guest_phone=(cust.phone if cust else "") or "",
        partner_name=(asset.owner_name if asset else "") or "",
        settlement_summary=st_summary,
        balance_to_collect=balance, deposit_paid=paid, total_price=total,
        transfer_note=getattr(b, "transfer_note", "") or "",
        pickup_location=getattr(b, "pickup_location", "") or "")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'inline; filename="voucher-{b.id}.pdf"'})
