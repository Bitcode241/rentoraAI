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
        group_csv = metadata.get("group_booking_ids") or ""
        amount_total = session.get("amount_total") or 0
        payment_intent = session.get("payment_intent") or ""
        # this single payment may cover several units (e.g. 2 jet skis)
        group_ids = [int(x) for x in group_csv.split(",") if x.strip().isdigit()]
        if booking_id and int(booking_id) not in group_ids:
            group_ids.insert(0, int(booking_id))
        if group_ids:
            paid_total = amount_total / 100.0
            bookings = [db.get(Booking, i) for i in group_ids]
            bookings = [b for b in bookings if b]
            # split the paid deposit across the units by their own deposit share
            dep_sum = sum(b.deposit_amount or 0 for b in bookings) or paid_total
            for b in bookings:
                share = (b.deposit_amount or 0) / dep_sum if dep_sum else 1 / len(bookings)
                b.payment_status = "deposit_paid"
                b.amount_paid = round(paid_total * share, 2)
                b.stripe_payment_intent = payment_intent
                if b.status in ("pending",):
                    b.status = "confirmed"
            db.commit()
            log.info("deposit_paid_confirmed", booking_ids=group_ids,
                     amount=paid_total, units=len(bookings))
            lead = bookings[0]
            # ONE confirmation covering the whole group
            try:
                _send_confirmation(db, lead, group=bookings)
            except Exception as e:
                log.warning("confirmation_send_failed", booking_id=lead.id, error=str(e))
            try:
                _notify_owner_paid(db, lead, group=bookings)
            except Exception as e:
                log.warning("owner_notify_failed", booking_id=lead.id, error=str(e))
            # generate the correct voucher (partner vs own) and email it to the guest
            try:
                _send_voucher(db, lead, group=bookings)
            except Exception as e:
                log.warning("voucher_send_failed", booking_id=lead.id, error=str(e))
    return {"received": True}


def _send_voucher(db, booking, group=None):
    """Generate and email the right voucher after payment:
       - partner tour -> partner voucher (intermediary + provider + split payment)
       - own tour      -> standard confirmation already covers it (skip)
    Blocks the partner voucher if provider data is missing."""
    from app.services import provider_service, voucher_service, settings_service
    from app.integrations.email_imap import MultiMailboxManager
    asset = db.get(Asset, booking.asset_id)
    if not asset or not provider_service.is_partner(asset):
        return  # own tours use the standard confirmation PDF
    cust = db.get(Customer, booking.customer_id)
    if not cust or not cust.email:
        return
    group = group or [booking]
    qty = len(group)
    amt = provider_service.partner_amounts(asset)
    from app.core.timeutil import fmt_local
    business = settings_service.brand_for_type(db, asset.asset_type)
    business_oib = settings_service.get(db, "business_oib", "") or ""
    from app.services import voucher_qr_service
    vtoken = voucher_qr_service.get_or_create_token(db, booking)
    import os as _os
    base = settings_service.get(db, "public_base_url", "") or _os.getenv("PUBLIC_BASE_URL", "")
    qr_img = None
    if base:
        try:
            qr_img = voucher_qr_service.qr_png(voucher_qr_service.voucher_url(base, vtoken))
        except Exception:
            qr_img = None
    try:
        pdf = voucher_service.build_partner_voucher(
            business_name=business, business_oib=business_oib,
            booking_id=booking.id, asset_name=asset.name,
            when=fmt_local(booking.start_datetime),
            guests=getattr(booking, "passengers", None) or "—",
            tour_name=booking.package_name or "",
            guest_name=(cust.full_name or "") if cust.full_name != cust.email else "",
            guest_phone=cust.phone or "",
            provider_name=asset.provider_name, provider_oib=asset.provider_oib,
            my_commission=round(amt["commission"] * qty, 2),
            pay_on_site=round(amt["pay_on_site"] * qty, 2),
            total_price=round(amt["total"] * qty, 2),
            pickup_location=getattr(booking, "pickup_location", "") or "",
            qr_png=qr_img, currency="EUR")
    except voucher_service.PartnerVoucherError as e:
        log.warning("partner_voucher_blocked", booking_id=booking.id, reason=str(e))
        return
    # email the voucher to the guest
    mgr = MultiMailboxManager.from_db(db)
    if not mgr.enabled:
        return
    box = next(iter(mgr.services.keys()), "")
    subj = f"Vaš voucher za izlet — rezervacija #{booking.id}"
    body = ("U privitku je Vaš voucher. Molimo predočite ga izvođaču pri dolasku.\n\n"
            "Your tour voucher is attached. Please present it to the operator on arrival.")
    try:
        mgr.reply_from(box, cust.email, subj, body,
                       attachment=pdf, attachment_name=f"voucher_{booking.id}.pdf")
        log.info("partner_voucher_sent", booking_id=booking.id, to=cust.email)
    except Exception as e:
        log.warning("partner_voucher_email_failed", booking_id=booking.id, error=str(e))


def _notify_owner_paid(db, booking, group=None):
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
    group = group or [booking]
    qty = len(group)
    import re as _re
    base_name = _re.sub(r"\s*\(\d+\)\s*$", "", asset.name).strip() if asset else "—"
    asset_label = f"{qty}× {base_name}" if qty > 1 else (asset.name if asset else "—")
    g_paid = sum(b.amount_paid or 0 for b in group)
    g_total = sum(b.total_price or 0 for b in group)
    body = (f"Gost je platio depozit!\n\n"
            f"Plovilo: {asset_label}\n"
            f"Termin: {when}\n"
            f"Gost: {cust.full_name if cust else ''} ({cust.email if cust else ''})\n"
            f"Depozit: {g_paid:.2f} EUR\n"
            f"Ukupno: {g_total:.2f} EUR\n"
            f"Rezervacija #{booking.id} — POTVRĐENA")
    mgr.reply_from(box, box, f"[PLAĆENO] Depozit — {asset_label} #{booking.id}", body)


def _send_confirmation(db, booking, group=None):
    """Build a PDF receipt and email it to the guest in their language.
    If `group` is given (multi-unit booking), the totals cover all units and the
    asset line shows the quantity."""
    from app.services import confirmation_service
    from app.integrations.email_imap import MultiMailboxManager
    from app.core.config import settings as _s
    asset = db.get(Asset, booking.asset_id)
    cust = db.get(Customer, booking.customer_id)
    if not cust or not cust.email:
        return
    lang = cust.language or "en"
    group = group or [booking]
    qty = len(group)
    # group-wide money
    group_total = sum(b.total_price or 0 for b in group)
    group_paid = sum(b.amount_paid or 0 for b in group)
    balance = max(group_total - group_paid, 0)
    from app.core.timeutil import fmt_local
    when = fmt_local(booking.start_datetime)
    from app.services import settings_service
    business = settings_service.brand_for_type(db, asset.asset_type if asset else "")
    import re as _re
    base_name = _re.sub(r"\s*\(\d+\)\s*$", "", asset.name).strip() if asset else "—"
    asset_label = f"{qty}× {base_name}" if qty > 1 else (asset.name if asset else "—")
    pdf = confirmation_service.build_pdf(
        lang=lang, business_name=business, booking_id=booking.id,
        asset_name=asset_label, when=when,
        guests=getattr(booking, "passengers", None) or "—",
        package=booking.package_name or "",
        deposit_paid=group_paid, full_price=group_total,
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


