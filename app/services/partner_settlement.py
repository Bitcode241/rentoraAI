"""Partner settlements — the money side of brokering someone else's boats.

For every booking on a partner vessel the split is:

  guest pays TOTAL
  - your commission  → stays with you
  = partner's share  → owed to the partner

Some of that arrives on your account (the online deposit), some the guest hands
over on the spot. What you owe the partner is therefore whatever of their share
passed through your hands and has not been paid out yet.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.booking import Booking


def _partner_assets(db: Session) -> dict:
    return {a.id: a for a in db.query(Asset)
            .filter(Asset.provider_type == "partner").all()}


def settlement_report(db: Session, days: int = 90) -> dict:
    """Per-partner totals: turnover, your commission, their share, and how much
    of their share you are actually holding (already collected by you)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    assets = _partner_assets(db)
    if not assets:
        return {"days": days, "partners": [], "total_owed": 0.0}

    rows = (db.query(Booking)
            .filter(Booking.asset_id.in_(list(assets.keys())),
                    Booking.start_datetime >= since,
                    Booking.status != "cancelled")
            .order_by(Booking.start_datetime.desc())
            .all())

    partners = {}
    for b in rows:
        a = assets.get(b.asset_id)
        if not a:
            continue
        name = (a.provider_name or "").strip() or f"Partner (asset #{a.id})"
        p = partners.setdefault(name, {
            "partner": name,
            "oib": getattr(a, "provider_oib", "") or "",
            "bookings": 0,
            "turnover": 0.0,        # what guests pay in total
            "my_commission": 0.0,   # what stays with me
            "partner_share": 0.0,   # what belongs to the partner
            "collected_by_me": 0.0, # of that share, what I already hold
            "items": [],
        })
        total = b.total_price or 0
        # commission is configured per asset; fall back to 0 so we never
        # silently invent a number
        commission = a.my_commission or 0
        share = max(total - commission, 0)
        # what I physically received for this booking (online + cash I took)
        received = (b.amount_paid or 0) + (getattr(b, "cash_collected", 0) or 0)
        # of what I received, the part above my commission belongs to the partner
        holding = max(round(received - commission, 2), 0)

        p["bookings"] += 1
        p["turnover"] += total
        p["my_commission"] += commission
        p["partner_share"] += share
        p["collected_by_me"] += holding
        p["items"].append({
            "booking_id": b.id,
            "date": b.start_datetime,
            "tour": b.package_name or "",
            "total": round(total, 2),
            "commission": round(commission, 2),
            "partner_share": round(share, 2),
            "received": round(received, 2),
            "holding": holding,
            "settled": bool(getattr(b, "partner_settled", False)),
        })

    out = []
    total_owed = 0.0
    for p in partners.values():
        # only unsettled bookings count towards what is still owed
        owed = sum(i["holding"] for i in p["items"] if not i["settled"])
        p["owed"] = round(owed, 2)
        total_owed += owed
        for k in ("turnover", "my_commission", "partner_share", "collected_by_me"):
            p[k] = round(p[k], 2)
        p["items"].sort(key=lambda x: x["date"], reverse=True)
        out.append(p)
    out.sort(key=lambda x: x["owed"], reverse=True)
    return {"days": days, "partners": out, "total_owed": round(total_owed, 2)}


def mark_settled(db: Session, booking_ids: list, settled: bool = True) -> int:
    """Mark bookings as paid out to the partner."""
    n = 0
    for bid in booking_ids or []:
        b = db.get(Booking, int(bid))
        if b:
            b.partner_settled = settled
            n += 1
    db.commit()
    return n
