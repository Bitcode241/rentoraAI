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
        session = event["data"]["object"]
        # Stripe objects aren't plain dicts; access fields defensively.
        try:
            metadata = dict(session.get("metadata") or {}) if hasattr(session, "get") else {}
        except Exception:
            metadata = {}
        if not metadata:
            # fallback: Stripe object attribute access
            metadata = dict(getattr(session, "metadata", {}) or {})
        booking_id = metadata.get("booking_id")
        amount_total = (session.get("amount_total") if hasattr(session, "get")
                        else getattr(session, "amount_total", 0)) or 0
        payment_intent = (session.get("payment_intent") if hasattr(session, "get")
                          else getattr(session, "payment_intent", "")) or ""
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
    return {"received": True}


@router.get("/config")
def payment_config(_=Depends(get_current_user)):
    """Non-secret info for the dashboard: is Stripe on, which currency."""
    return {"enabled": settings.stripe_enabled(),
            "currency": settings.stripe_currency,
            "publishable_key": settings.stripe_publishable_key}

