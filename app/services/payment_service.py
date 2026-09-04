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


def active_provider(db) -> str:
    """Which card provider to charge with: 'stripe' (default) or 'mypos'.

    Kept as a setting so the owner can flip it in the admin without a deploy —
    and flip straight back if anything looks wrong.
    """
    from app.services import settings_service
    choice = (settings_service.get(db, "payment_provider", "stripe") or "stripe").lower()
    if choice == "mypos":
        from app.services import mypos_service
        if mypos_service.enabled():
            return "mypos"
        log.warning("mypos_selected_but_not_configured_falling_back")
        return "stripe"
    return "stripe"


def create_deposit_checkout(booking, asset_name: str, guest_email: str = "",
                            override_amount: float = None,
                            group_booking_ids: list = None,
                            attribution: dict = None,
                            db=None, guest_name: str = "") -> dict:
    """Create a Stripe Checkout Session for the booking deposit.
    override_amount: charge this instead of booking.deposit_amount (for multi-unit
    bookings where several units share one checkout).
    group_booking_ids: all booking ids this single payment covers, so the webhook
    can mark them all paid.
    attribution: {source, medium, campaign, term, gclid} — marketing source, stored
    in Stripe metadata and later on the booking for reporting.
    Returns {url, session_id} or {error}."""
    # myPOS uses a form POST to a hosted page rather than a redirect URL, so we
    # hand back a link to our own bridge page which submits that form.
    if db is not None and active_provider(db) == "mypos":
        from app.services import mypos_service
        amount = (override_amount if override_amount is not None
                  else (booking.deposit_amount or 0))
        built = mypos_service.build_purchase(
            booking, asset_name, amount, guest_email=guest_email,
            guest_name=guest_name, group_booking_ids=group_booking_ids)
        if "error" in built:
            return built
        if group_booking_ids:
            booking.stripe_session_id = built["order_id"]
        base = (settings.public_base_url or "").rstrip("/")
        return {"url": f"{base}/pay/mypos/{built['order_id']}",
                "session_id": built["order_id"], "provider": "mypos"}
    stripe = _client()
    if not stripe:
        return {"error": "stripe_not_configured",
                "message": "Stripe nije postavljen (nedostaje ključ)."}

    deposit = override_amount if override_amount is not None else (booking.deposit_amount or 0)
    if deposit <= 0:
        return {"error": "no_deposit", "message": "Iznos depozita je 0."}

    amount_cents = int(round(deposit * 100))  # Stripe radi u centima
    attr = attribution or {}
    meta = {
        "booking_id": str(booking.id),
        "group_booking_ids": ",".join(
            str(x) for x in (group_booking_ids or [booking.id])),
        "utm_source": (attr.get("source") or "")[:400],
        "utm_medium": (attr.get("medium") or "")[:400],
        "utm_campaign": (attr.get("campaign") or "")[:400],
        "utm_term": (attr.get("term") or "")[:400],
        "gclid": (attr.get("gclid") or "")[:400],
    }
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
            metadata=meta,
            success_url=f"{settings.public_base_url}/pay/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.public_base_url}/pay/cancel?booking={booking.id}",
        )
        log.info("stripe_checkout_created", booking_id=booking.id,
                 session=session.id, amount=deposit,
                 source=meta["utm_source"] or "direct")
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
