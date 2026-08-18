"""Attribution reporting: where paid bookings came from (Google Ads, WhatsApp,
Instagram, direct...). Groups bookings by utm_source/campaign for the admin."""
from sqlalchemy.orm import Session

from app.models.booking import Booking


def _label(source: str) -> str:
    """Human-friendly label for a raw utm_source (or 'Direct' when empty)."""
    s = (source or "").strip().lower()
    # generic/non-informative sources are treated as direct
    if s in ("", "web", "website", "direct", "referral", "(none)", "none"):
        return "Direct / bez izvora"
    mapping = {
        "google": "Google Ads", "google_ads": "Google Ads", "googleads": "Google Ads",
        "adwords": "Google Ads", "cpc": "Google Ads", "google-ads": "Google Ads",
        "whatsapp": "WhatsApp", "wa": "WhatsApp",
        "instagram": "Instagram", "ig": "Instagram",
        "facebook": "Facebook", "fb": "Facebook", "meta": "Facebook",
        "getyourguide": "GetYourGuide", "viator": "Viator",
        "tripadvisor": "TripAdvisor", "booking": "Booking.com",
        "email": "Email", "newsletter": "Email",
    }
    return mapping.get(s, source)


def source_report(db: Session, only_paid: bool = True) -> list:
    """Return per-source stats: bookings count, revenue, deposits collected.
    Sorted by revenue desc so the best channels are on top."""
    q = db.query(Booking)
    if only_paid:
        q = q.filter(Booking.payment_status.in_(["deposit_paid", "paid"]))
    rows = q.all()
    buckets = {}
    for b in rows:
        # group by the friendly label so "", "web", "referral" merge into one
        # "Direct" row instead of showing as separate confusing rows
        label = _label(b.utm_source)
        key = label.lower()
        if key not in buckets:
            buckets[key] = {
                "source": label,
                "raw_source": b.utm_source or "",
                "bookings": 0, "revenue": 0.0, "deposits": 0.0,
                "campaigns": set(),
            }
        bk = buckets[key]
        bk["bookings"] += 1
        bk["revenue"] += b.total_price or 0
        bk["deposits"] += b.amount_paid or 0
        if b.utm_campaign:
            bk["campaigns"].add(b.utm_campaign)
    out = []
    for bk in buckets.values():
        out.append({
            "source": bk["source"],
            "raw_source": bk["raw_source"],
            "bookings": bk["bookings"],
            "revenue": round(bk["revenue"], 2),
            "deposits": round(bk["deposits"], 2),
            "campaigns": sorted(bk["campaigns"]),
        })
    out.sort(key=lambda r: r["revenue"], reverse=True)
    return out
