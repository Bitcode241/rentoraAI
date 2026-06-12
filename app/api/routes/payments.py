from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.core.logging import get_logger
from app.models.booking import Booking
from app.models.asset import Asset
from app.models.customer import Customer
from app.services import payment_service

router = APIRouter(prefix="/api/payments", tags=["payments"])
log = get_logger(__name__)


@router.post("/checkout/{booking_id}")
def create_checkout(booking_id: int, db: Session = Depends(get_db),
                    _=Depends(get_current_user)):
    """Create a Stripe deposit payment link for a booking (admin/AI use)."""
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    asset = db.get(Asset, b.asset_id)
    cust = db.get(Customer, b.customer_id)
    res = payment_service.create_deposit_checkout(
        b, asset.name if asset else "Plovilo", cust.email if cust else "")
    if "url" in res:
        b.stripe_session_id = res["session_id"]
        b.payment_status = "awaiting_payment"
        db.commit()
    return res


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe calls this when a payment completes. Verifies signature, then
    confirms the booking ONLY when the deposit actually arrived."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    event = payment_service.verify_webhook(payload, sig)
    if event is None:
        # signature invalid or stripe not configured
        raise HTTPException(400, "Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        # Parse straight from the raw JSON payload — avoids Stripe object quirks.
        import json as _json
        try:
            raw = _json.loads(payload.decode("utf-8"))
            session = raw.get("data", {}).get("object", {})
        except Exception:
            session = {}
        metadata = session.get("metadata") or {}
        booking_id = metadata.get("booking_id")
        amount_total = session.get("amount_total") or 0
        payment_intent = session.get("payment_intent") or ""
        if booking_id:
            b = db.get(Booking, int(booking_id))
            if b:
                b.payment_status = "deposit_paid"
                b.amount_paid = amount_total / 100.0
                b.stripe_payment_intent = payment_intent
                # Confirm the booking now that money has actually arrived.
                if b.status in ("pending",):
                    b.status = "confirmed"
                db.commit()
                log.info("deposit_paid_confirmed", booking_id=b.id,
                         amount=b.amount_paid)
                # Send a professional confirmation (PDF + email) to the guest.
                try:
                    _send_confirmation(db, b)
                except Exception as e:
                    log.warning("confirmation_send_failed", booking_id=b.id, error=str(e))
                # Notify the owner that a guest just paid.
                try:
                    _notify_owner_paid(db, b)
                except Exception as e:
                    log.warning("owner_notify_failed", booking_id=b.id, error=str(e))
    return {"received": True}


def _notify_owner_paid(db, booking):
    """Email the business owner that a guest paid the deposit."""
    from app.integrations.email_imap import MultiMailboxManager
    asset = db.get(Asset, booking.asset_id)
    cust = db.get(Customer, booking.customer_id)
    mgr = MultiMailboxManager.from_db(db)
    if not mgr.enabled:
        return
    box = next(iter(mgr.services.keys()), "")
    from app.core.timeutil import fmt_local
    when = fmt_local(booking.start_datetime)
    body = (f"Gost je platio depozit!\n\n"
            f"Plovilo: {asset.name if asset else '—'}\n"
            f"Termin: {when}\n"
            f"Gost: {cust.full_name if cust else ''} ({cust.email if cust else ''})\n"
            f"Depozit: {booking.amount_paid:.2f} EUR\n"
            f"Ukupno: {booking.total_price:.2f} EUR\n"
            f"Rezervacija #{booking.id} — POTVRĐENA")
    mgr.reply_from(box, box, f"[PLAĆENO] Depozit — {asset.name if asset else 'rezervacija'} #{booking.id}", body)


def _send_confirmation(db, booking):
    """Build a PDF receipt and email it to the guest in their language."""
    from app.services import confirmation_service
    from app.integrations.email_imap import MultiMailboxManager
    from app.core.config import settings as _s
    asset = db.get(Asset, booking.asset_id)
    cust = db.get(Customer, booking.customer_id)
    if not cust or not cust.email:
        return
    lang = cust.language or "en"
    balance = max((booking.total_price or 0) - (booking.amount_paid or 0), 0)
    from app.core.timeutil import fmt_local
    when = fmt_local(booking.start_datetime)
    from app.services import settings_service
    business = settings_service.brand_for_type(db, asset.asset_type if asset else "")
    pdf = confirmation_service.build_pdf(
        lang=lang, business_name=business, booking_id=booking.id,
        asset_name=asset.name if asset else "—", when=when,
        guests=getattr(booking, "passengers", None) or "—",
        package=booking.package_name or "",
        deposit_paid=booking.amount_paid or 0, full_price=booking.total_price or 0,
        balance=balance, transfer_included=bool(getattr(booking, "transfer_note", "")),
        location=(getattr(booking, "pickup_location", "") or (asset.location if asset else "")),
        phone=cust.phone or "",
        guest_name=(cust.full_name or "") if (cust.full_name and cust.full_name != cust.email) else "",
        guest_email=cust.email or "",
        transfer_note=getattr(booking, "transfer_note", "") or "",
        currency="EUR")
    subject, body = confirmation_service.email_text(lang, business)
    mgr = MultiMailboxManager.from_db(db)
    if mgr.enabled:
        from_box = next(iter(mgr.services.keys()), "")
        mgr.reply_from(from_box, cust.email, subject, body,
                       attachment=pdf, attachment_name=f"potvrda-{booking.id}.pdf")
        log.info("confirmation_sent", booking_id=booking.id, to=cust.email, lang=lang)


@router.get("/config")
def payment_config(_=Depends(get_current_user)):
    """Non-secret info for the dashboard: is Stripe on, which currency."""
    return {"enabled": settings.stripe_enabled(),
            "currency": settings.stripe_currency,
            "publishable_key": settings.stripe_publishable_key}


@router.post("/send-confirmation/{booking_id}")
def send_confirmation_manual(booking_id: int, db: Session = Depends(get_db),
                             _=Depends(get_current_user)):
    """Manually (re)send the confirmation PDF — useful for testing or resending."""
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    try:
        _send_confirmation(db, b)
        return {"sent": True}
    except Exception as e:
        return {"sent": False, "error": str(e)}


@router.post("/refund/{booking_id}")
def refund_booking(booking_id: int, db: Session = Depends(get_db),
                   _=Depends(get_current_user)):
    """Refund the deposit paid for a booking via Stripe, and cancel it."""
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    if b.payment_status != "deposit_paid" or not b.stripe_payment_intent:
        raise HTTPException(400, "No captured deposit to refund.")
    stripe = payment_service._client()
    if not stripe:
        raise HTTPException(400, "Stripe not configured")
    try:
        refund = stripe.Refund.create(payment_intent=b.stripe_payment_intent)
        b.payment_status = "refunded"
        b.status = "cancelled"
        db.commit()
        log.info("refund_done", booking_id=b.id, refund=refund.id)
        return {"refunded": True, "amount": b.amount_paid}
    except Exception as e:
        log.warning("refund_failed", booking_id=b.id, error=str(e))
        raise HTTPException(400, f"Refund failed: {e}")


