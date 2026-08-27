"""Money overview: what came in, split by channel, with VAT and card fees shown.

The point is an honest picture of what actually lands in the owner's pocket:
gross revenue, the VAT portion that belongs to the state, the card processing
fee, and the remainder.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.services import settings_service

VAT_RATE_KEY = "vat_rate"          # e.g. "25" for 25%
STRIPE_FEE_PCT_KEY = "stripe_fee_pct"   # e.g. "3.6"
IN_VAT_SYSTEM_KEY = "in_vat_system"     # "1" / "0"


def vat_rate(db: Session) -> float:
    try:
        return float(settings_service.get(db, VAT_RATE_KEY, "25") or 25)
    except (TypeError, ValueError):
        return 25.0


def stripe_fee_pct(db: Session) -> float:
    try:
        return float(settings_service.get(db, STRIPE_FEE_PCT_KEY, "3.6") or 3.6)
    except (TypeError, ValueError):
        return 3.6


def in_vat_system(db: Session) -> bool:
    return (settings_service.get(db, IN_VAT_SYSTEM_KEY, "1") or "1") == "1"


def money_overview(db: Session, days: int = 30) -> dict:
    """Revenue for the last `days` days, split into online (card) and cash.

    VAT applies to turnover regardless of how the guest paid — it is shown on the
    total, not only on card payments.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (db.query(Booking)
            .filter(Booking.start_datetime >= since)
            .filter(Booking.status != "cancelled")
            .all())
    online = sum(b.amount_paid or 0 for b in rows)
    cash = sum(getattr(b, "cash_collected", 0) or 0 for b in rows)
    gross = online + cash
    fee_pct = stripe_fee_pct(db)
    card_fee = online * fee_pct / 100.0
    rate = vat_rate(db)
    # VAT is included in the price the guest paid, so back it out of the gross
    vat = (gross * rate / (100.0 + rate)) if in_vat_system(db) else 0.0
    net = gross - vat - card_fee
    outstanding = 0.0
    for b in rows:
        settled = (b.amount_paid or 0) + (getattr(b, "cash_collected", 0) or 0)
        outstanding += max((b.total_price or 0) - settled, 0)
    return {
        "days": days,
        "bookings": len(rows),
        "gross": round(gross, 2),
        "online": round(online, 2),
        "cash": round(cash, 2),
        "card_fee": round(card_fee, 2),
        "card_fee_pct": fee_pct,
        "vat": round(vat, 2),
        "vat_rate": rate,
        "in_vat_system": in_vat_system(db),
        "net": round(net, 2),
        "outstanding": round(outstanding, 2),
    }
