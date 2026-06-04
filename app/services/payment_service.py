"""Stripe deposit payments.

Flow (safest model):
  1. A booking is created with status='pending', payment_status='awaiting_payment'.
  2. We create a Stripe Checkout Session for the DEPOSIT (30%).
  3. Guest pays on Stripe's hosted page.
  4. Stripe calls our webhook -> we verify the signature -> mark deposit_paid
     and confirm the booking. The booking is ONLY confirmed once Stripe says the
     money actually arrived (never on the guest's word).

Keys come from settings (.env). If a Mailbox-style DB override exists later we can
add it, but the secret key is intentionally a system secret.
"""
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _client():
    """Return a configured stripe module, or None if not configured."""
    if not settings.stripe_enabled():
        return None
    import stripe
    stripe.api_key = settings.stripe_secret_key
    return stripe


def create_deposit_checkout(booking, asset_name: str, guest_email: str = "") -> dict:
    """Create a Stripe Checkout Session for the booking deposit.
    Returns {url, session_id} or {error}."""
    stripe = _client()
    if not stripe:
        return {"error": "stripe_not_configured",
                "message": "Stripe nije postavljen (nedostaje ključ)."}

    deposit = booking.deposit_amount or 0
    if deposit <= 0:
        return {"error": "no_deposit", "message": "Iznos depozita je 0."}

    amount_cents = int(round(deposit * 100))  # Stripe radi u centima
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": settings.stripe_currency,
                    "product_data": {
                        "name": f"Depozit — {asset_name}",
                        "description": f"Rezervacija #{booking.id}",
                    },
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            customer_email=guest_email or None,
            metadata={"booking_id": str(booking.id)},
            success_url=f"{settings.public_base_url}/pay/success?booking={booking.id}",
            cancel_url=f"{settings.public_base_url}/pay/cancel?booking={booking.id}",
        )
        log.info("stripe_checkout_created", booking_id=booking.id,
                 session=session.id, amount=deposit)
        return {"url": session.url, "session_id": session.id}
    except Exception as e:  # pragma: no cover
        log.warning("stripe_checkout_failed", booking_id=booking.id, error=str(e))
        return {"error": "stripe_error", "message": str(e)}


def verify_webhook(payload: bytes, sig_header: str):
    """Verify a Stripe webhook signature. Returns the event or None."""
    stripe = _client()
    if not stripe or not settings.stripe_webhook_secret:
        return None
    try:
        return stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret)
    except Exception as e:  # pragma: no cover
        log.warning("stripe_webhook_invalid", error=str(e))
        return None
