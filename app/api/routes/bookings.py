from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.booking import Booking
from app.schemas import BookingCreate, BookingUpdate, BookingOut
from app.services import booking_service
from app.core.logging import get_logger

log = get_logger(__name__)


def _actor(user) -> str:
    """Username for the audit trail (falls back gracefully)."""
    return getattr(user, "username", None) or str(user or "admin")

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


@router.get("")
def list_bookings(status: Optional[str] = None, db: Session = Depends(get_db),
                  _=Depends(get_current_user)):
    """Bookings enriched with guest name/email/phone and asset name, so the admin
    table shows who is coming — not just ids."""
    from app.models.customer import Customer
    from app.models.asset import Asset
    q = db.query(Booking)
    if status:
        q = q.filter(Booking.status == status)
    rows = q.order_by(Booking.start_datetime.desc()).all()
    # preload customers + assets in one go (avoid a query per row)
    cust_ids = {b.customer_id for b in rows if b.customer_id}
    asset_ids = {b.asset_id for b in rows if b.asset_id}
    customers = {c.id: c for c in db.query(Customer).filter(
        Customer.id.in_(cust_ids)).all()} if cust_ids else {}
    assets = {a.id: a for a in db.query(Asset).filter(
        Asset.id.in_(asset_ids)).all()} if asset_ids else {}
    out = []
    for b in rows:
        c = customers.get(b.customer_id)
        a = assets.get(b.asset_id)
        name = ""
        if c:
            name = (c.full_name or "").strip()
            # some records store the email as the name — show a clean blank instead
            if name and "@" in name and name == (c.email or ""):
                name = ""
        out.append({
            "id": b.id,
            "asset_id": b.asset_id,
            "asset_name": (a.name if a else "") or f"#{b.asset_id}",
            "package_name": b.package_name or "",
            "start_datetime": b.start_datetime,
            "end_datetime": b.end_datetime,
            "total_price": b.total_price,
            "deposit_amount": b.deposit_amount,
            "amount_paid": b.amount_paid,
            "status": b.status,
            "payment_status": b.payment_status,
            "source": b.source,
            "passengers": getattr(b, "passengers", 0) or 0,
            "pickup_location": getattr(b, "pickup_location", "") or "",
            "transfer_note": getattr(b, "transfer_note", "") or "",
            "guest_name": name,
            "guest_email": (c.email if c else "") or "",
            "guest_phone": (c.phone if c else "") or "",
            "utm_source": getattr(b, "utm_source", "") or "",
            "utm_campaign": getattr(b, "utm_campaign", "") or "",
        })
    return out


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


@router.post("/quick")
def quick_booking(payload: dict, db: Session = Depends(get_db),
                  _=Depends(get_current_user)):
    """Create a booking in seconds from the phone: tour + when + guest name/phone.
    Used for guests agreed on WhatsApp or walk-ins."""
    from datetime import timedelta
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.models.tour_type import TourType
    from app.ai.tools import _parse

    tour_id = payload.get("tour_id")
    asset_type = (payload.get("asset_type") or "jetski").strip()
    qty = max(1, int(payload.get("qty") or 1))
    passengers = max(1, int(payload.get("passengers") or 1))
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    email = (payload.get("email") or "").strip()
    if not name and not phone:
        raise HTTPException(400, "Upiši barem ime ili broj telefona.")
    if not payload.get("start"):
        raise HTTPException(400, "Upiši datum i vrijeme.")
    try:
        start = _parse(str(payload["start"]))
    except Exception:
        raise HTTPException(400, "Neispravan datum/vrijeme.")

    tour = db.get(TourType, int(tour_id)) if tour_id else None
    if not tour:
        raise HTTPException(400, "Odaberi turu.")
    end = start + timedelta(minutes=tour.duration_minutes or 60)

    # find free units of this type for the slot
    units = (db.query(Asset)
             .filter(Asset.asset_type == (tour.asset_type or asset_type),
                     Asset.active == True,  # noqa: E712
                     Asset.out_of_service == False)  # noqa: E712
             .all())
    free = []
    for u in units:
        clash = (db.query(Booking)
                 .filter(Booking.asset_id == u.id,
                         Booking.start_datetime < end,
                         Booking.end_datetime > start,
                         Booking.status != "cancelled")
                 .first())
        if not clash:
            free.append(u)
        if len(free) >= qty:
            break
    if len(free) < qty:
        raise HTTPException(409, f"Nema dovoljno slobodnih jedinica "
                                 f"({len(free)} od {qty}) u tom terminu.")

    cust = None
    if email:
        cust = db.query(Customer).filter(Customer.email == email).first()
    if not cust and phone:
        cust = db.query(Customer).filter(Customer.phone == phone).first()
    if not cust:
        cust = Customer(full_name=name or phone, email=email or "",
                        phone=phone or "")
        db.add(cust)
        db.commit()
        db.refresh(cust)
    else:
        if name:
            cust.full_name = name
        if phone:
            cust.phone = phone
        db.commit()

    created = []
    per_unit_pax = max(1, passengers // qty) if qty else passengers
    # the guest may already have paid something (cash on the spot, myPOS link…)
    try:
        prepaid = float(payload.get("paid") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Neispravan iznos uplate.")
    pay_method = (payload.get("pay_method") or "cash").strip().lower()
    total_all = (tour.price or 0) * qty
    if prepaid > total_all + 0.01:
        raise HTTPException(400, "Uplaćeno je veće od ukupne cijene.")
    per_unit_paid = round(prepaid / qty, 2) if qty else prepaid

    for u in free[:qty]:
        unit_total = tour.price or 0
        b = Booking(asset_id=u.id, customer_id=cust.id,
                    start_datetime=start, end_datetime=end,
                    total_price=unit_total,
                    deposit_amount=round(unit_total *
                                         (tour.deposit_percent or 30) / 100.0, 2),
                    payment_status="unpaid", status="confirmed",
                    passengers=per_unit_pax, package_name=tour.name,
                    source="admin", tour_type_id=tour.id)
        if per_unit_paid > 0:
            if pay_method == "cash":
                b.cash_collected = per_unit_paid
            else:
                b.amount_paid = per_unit_paid
            b.payment_status = ("paid" if per_unit_paid + 0.01 >= unit_total
                                else "deposit_paid")
        db.add(b)
        db.commit()
        created.append(b.id)
    from app.services import audit
    audit.record(db, "quick_booking", actor=_actor(_), entity="booking",
                 entity_id=",".join(str(i) for i in created),
                 detail=f"{len(created)}× {tour.name} · {cust.full_name or cust.phone} "
                        f"· {start:%Y-%m-%d %H:%M} · {(tour.price or 0) * qty:.2f} EUR")
    log.info("quick_booking_created", ids=created, tour=tour.name, qty=qty)
    return {"ok": True, "booking_ids": created, "count": len(created),
            "total": round(total_all, 2),
            "paid": round(prepaid, 2),
            "balance": round(max(total_all - prepaid, 0), 2),
            "tour": tour.name, "customer_id": cust.id}


@router.post("/{booking_id}/edit")
def edit_booking(booking_id: int, payload: dict, db: Session = Depends(get_db),
                 _=Depends(get_current_user)):
    """Correct a booking after the fact — the guest took a different tour, a
    shorter/longer one, or a different number of people than they booked."""
    from datetime import timedelta
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    from app.services import audit
    _fields = ["package_name", "passengers", "total_price", "payment_status"]
    _before = audit.snapshot(b, _fields)

    if "package_name" in payload:
        b.package_name = str(payload["package_name"] or "")[:120]
    if "passengers" in payload:
        try:
            b.passengers = max(1, int(payload["passengers"]))
        except (TypeError, ValueError):
            raise HTTPException(400, "Neispravan broj osoba.")
    if "duration_minutes" in payload and payload["duration_minutes"]:
        try:
            mins = int(payload["duration_minutes"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Neispravno trajanje.")
        if mins > 0 and b.start_datetime:
            b.end_datetime = b.start_datetime + timedelta(minutes=mins)
    if "start" in payload and payload["start"]:
        from app.ai.tools import _parse
        try:
            new_start = _parse(str(payload["start"]))
        except Exception:
            raise HTTPException(400, "Neispravan datum/vrijeme.")
        dur = None
        if b.start_datetime and b.end_datetime:
            dur = b.end_datetime - b.start_datetime
        b.start_datetime = new_start
        if dur:
            b.end_datetime = new_start + dur
    if "total_price" in payload:
        try:
            b.total_price = round(float(payload["total_price"]), 2)
        except (TypeError, ValueError):
            raise HTTPException(400, "Neispravna cijena.")
    if "notes" in payload:
        b.notes = str(payload["notes"] or "")[:2000]

    # keep the payment status honest after a price change
    settled = (b.amount_paid or 0) + (getattr(b, "cash_collected", 0) or 0)
    total = b.total_price or 0
    if settled <= 0:
        b.payment_status = "unpaid" if b.payment_status != "awaiting_payment" else b.payment_status
    elif settled + 0.01 >= total:
        b.payment_status = "paid"
    else:
        b.payment_status = "deposit_paid"
    db.commit()
    audit.record_change(db, "booking_edited", actor=_actor(_), entity="booking",
                        entity_id=b.id, before=_before,
                        after=audit.snapshot(b, _fields))
    log.info("booking_edited", booking_id=b.id, total=total, settled=settled)
    return {"ok": True, "id": b.id, "total_price": b.total_price,
            "payment_status": b.payment_status,
            "balance": round(max(total - settled, 0), 2)}


@router.post("/{booking_id}/cash")
def record_cash(booking_id: int, payload: dict, db: Session = Depends(get_db),
                _=Depends(get_current_user)):
    """Record cash collected on site. Marks the booking settled when the full
    amount is in."""
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    try:
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Neispravan iznos.")
    if amount < 0:
        raise HTTPException(400, "Iznos ne može biti negativan.")
    b.cash_collected = round(amount, 2)
    b.cash_note = str(payload.get("note") or "")[:255]
    # total settled = what came in online + what was collected in cash
    settled = (b.amount_paid or 0) + b.cash_collected
    if settled + 0.01 >= (b.total_price or 0):
        b.payment_status = "paid"
        if b.status == "pending":
            b.status = "confirmed"
    db.commit()
    from app.services import audit
    audit.record(db, "cash_recorded", actor=_actor(_), entity="booking",
                 entity_id=b.id,
                 detail=f"Naplaćeno u gotovini: {b.cash_collected:.2f} EUR "
                        f"(ukupno {b.total_price or 0:.2f}, "
                        f"status {b.payment_status})")
    log.info("cash_recorded", booking_id=b.id, amount=b.cash_collected)
    return {"ok": True, "cash_collected": b.cash_collected,
            "payment_status": b.payment_status,
            "balance": round(max((b.total_price or 0) - settled, 0), 2)}


@router.get("/{booking_id}/detail")
def booking_detail(booking_id: int, db: Session = Depends(get_db),
                   _=Depends(get_current_user)):
    """Everything about one booking in one place: guest, what they booked, what's
    paid, what's still to collect, add-ons, meeting point and marketing source."""
    from app.models.customer import Customer
    from app.models.asset import Asset
    from app.services import settings_service
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    c = db.get(Customer, b.customer_id) if b.customer_id else None
    a = db.get(Asset, b.asset_id) if b.asset_id else None
    total = b.total_price or 0
    paid = b.amount_paid or 0
    balance = round(max(total - paid, 0), 2)
    # extras were recorded as human-readable lines in notes at booking time
    extras = []
    for line in (b.notes or "").split("\n"):
        line = line.strip()
        if line and any(k in line.lower() for k in
                        ("add-on", "dodatna osoba", "transfer", "extra")):
            extras.append(line)
    name = ""
    if c:
        name = (c.full_name or "").strip()
        if name and "@" in name and name == (c.email or ""):
            name = ""
    # is this a partner asset (someone else's boat) — affects who collects cash
    is_partner = bool(a and getattr(a, "provider_type", "") == "partner")
    # prefer the canonical catalog tour name — package names can be stale after renames
    tour_name = b.package_name or ""
    tid = getattr(b, "tour_type_id", None)
    if tid:
        from app.models.tour_type import TourType
        t = db.get(TourType, tid)
        if t and t.name:
            tour_name = t.name
    return {
        "id": b.id,
        "status": b.status,
        "payment_status": b.payment_status,
        "guest": {
            "name": name,
            "email": (c.email if c else "") or "",
            "phone": (c.phone if c else "") or "",
        },
        "what": {
            "asset_name": (a.name if a else "") or f"#{b.asset_id}",
            "asset_type": (a.asset_type if a else "") or "",
            "package_name": tour_name,
            "passengers": getattr(b, "passengers", 0) or 0,
            "start": b.start_datetime,
            "end": b.end_datetime,
        },
        "money": {
            "total": round(total, 2),
            "paid": round(paid, 2),
            "balance": balance,
            "deposit_amount": round(b.deposit_amount or 0, 2),
            "currency": "EUR",
        },
        "extras": extras,
        "pickup_location": getattr(b, "pickup_location", "") or "",
        "transfer_note": getattr(b, "transfer_note", "") or "",
        "notes": b.notes or "",
        "source": {
            "channel": b.source or "",
            "utm_source": getattr(b, "utm_source", "") or "",
            "utm_campaign": getattr(b, "utm_campaign", "") or "",
        },
        "is_partner": is_partner,
        "partner_name": (getattr(a, "provider_name", "") or "") if is_partner else "",
        "meeting_note": settings_service.get(db, "meeting_note", "") or "",
        "created_at": b.created_at,
    }


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
    from app.services import settings_service, provider_service
    biz = settings_service.brand_for_type(db, asset.asset_type if asset else "")

    # Partner provider tour -> the legally-structured partner voucher (intermediary
    # + provider OIB + split payment). Blocks if provider data is missing.
    if asset and provider_service.is_partner(asset):
        problems = provider_service.validate_partner_asset(asset)
        if problems:
            raise HTTPException(
                400, "Voucher se ne može izdati — nedostaju podaci izvođača: "
                + ", ".join(problems))
        amt = provider_service.partner_amounts(asset)
        qty = 1  # this endpoint is per-booking; group vouchers go through payment flow
        biz_oib = settings_service.get(db, "business_oib", "") or ""
        # QR -> public skipper view
        from app.services import voucher_qr_service
        vtoken = voucher_qr_service.get_or_create_token(db, b)
        base = settings_service.get(db, "public_base_url", "") or \
            __import__("os").getenv("PUBLIC_BASE_URL", "")
        qr_img = None
        if base:
            try:
                qr_img = voucher_qr_service.qr_png(
                    voucher_qr_service.voucher_url(base, vtoken))
            except Exception:
                qr_img = None
        try:
            pdf = voucher_service.build_partner_voucher(
                business_name=biz, business_oib=biz_oib, booking_id=b.id,
                asset_name=asset.name, when=when, guests=getattr(b, "passengers", 0) or "—",
                tour_name=tour, guest_name=gname,
                guest_phone=(cust.phone if cust else "") or "",
                provider_name=asset.provider_name, provider_oib=asset.provider_oib,
                my_commission=amt["commission"], pay_on_site=amt["pay_on_site"],
                total_price=amt["total"],
                pickup_location=getattr(b, "pickup_location", "") or "",
                transfer_note=getattr(b, "transfer_note", "") or "",
                qr_png=qr_img, currency="EUR")
        except voucher_service.PartnerVoucherError as e:
            raise HTTPException(400, "Voucher blokiran: nedostaju podaci izvođača.")
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition":
                                 f'inline; filename="voucher-{b.id}.pdf"'})

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
