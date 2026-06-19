from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from app.core.database import get_db
from app.core.security import get_current_user

router = APIRouter(tags=["dashboard"])


@router.get("/admin", include_in_schema=False)
def admin():
    return FileResponse("app/static/admin.html", media_type="text/html")


@router.get("/api/dashboard/overview")
def dashboard_overview(days: int = 7, db: Session = Depends(get_db),
                       _=Depends(get_current_user)):
    """Tours grouped by day for the next `days` days, plus a summary.
    Everything a daily operations view needs: who, when, guests, paid, to-collect,
    provider type, and whether a partner voucher is needed."""
    from app.models.booking import Booking
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.core.timeutil import to_local, fmt_local
    from app.services import provider_service, settings_service

    now_local = to_local(datetime.now(timezone.utc))
    start_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_window = start_day + timedelta(days=max(1, days))

    # fetch bookings in window (compare in UTC)
    start_utc = start_day.astimezone(timezone.utc)
    end_utc = end_window.astimezone(timezone.utc)
    rows = (db.query(Booking)
            .filter(Booking.start_datetime >= start_utc,
                    Booking.start_datetime < end_utc,
                    Booking.status != "cancelled")
            .order_by(Booking.start_datetime).all())

    # cache assets/customers
    assets = {a.id: a for a in db.query(Asset).all()}
    custs = {c.id: c for c in db.query(Customer).all()}

    by_day = {}
    sum_count = 0
    sum_paid = 0.0
    sum_collect = 0.0
    sum_partner = 0
    for b in rows:
        a = assets.get(b.asset_id)
        c = custs.get(b.customer_id)
        is_partner = bool(a and provider_service.is_partner(a))
        paid = b.amount_paid or 0
        total = b.total_price or 0
        # to collect on site = total - already paid (for own), or pay_on_site (partner)
        if is_partner and a:
            amt = provider_service.partner_amounts(a)
            to_collect = amt["pay_on_site"]
            total = amt["total"]
        else:
            to_collect = max(total - paid, 0)
        local_dt = to_local(b.start_datetime)
        day_key = local_dt.strftime("%Y-%m-%d")
        voucher_needed = is_partner and bool(
            a and not provider_service.validate_partner_asset(a))
        item = {
            "booking_id": b.id,
            "time": fmt_local(b.start_datetime, "%H:%M"),
            "end_time": fmt_local(b.end_datetime, "%H:%M") if b.end_datetime else "",
            "asset": a.name if a else "—",
            "asset_type": a.asset_type if a else "",
            "tour": b.package_name or "",
            "guest": (c.full_name if c and c.full_name and c.full_name != (c.email or "")
                      else (c.email if c else "—")),
            "phone": (c.phone if c else "") or "",
            "guests": b.passengers or 0,
            "paid": round(paid, 2),
            "total": round(total, 2),
            "to_collect": round(to_collect, 2),
            "payment_status": b.payment_status,
            "provider_type": "partner" if is_partner else "own",
            "provider_name": (a.provider_name if is_partner and a else ""),
            "voucher_ready": voucher_needed,
            "pickup": getattr(b, "pickup_location", "") or "",
            "note": getattr(b, "transfer_note", "") or "",
            "source": b.source,
        }
        by_day.setdefault(day_key, []).append(item)
        sum_count += 1
        sum_paid += paid
        sum_collect += to_collect
        if is_partner:
            sum_partner += 1

    # build ordered day list with friendly labels
    labels_hr = ["Pon", "Uto", "Sri", "Čet", "Pet", "Sub", "Ned"]
    days_out = []
    for i in range(max(1, days)):
        d = start_day + timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        rel = "Danas" if i == 0 else ("Sutra" if i == 1 else labels_hr[d.weekday()])
        days_out.append({
            "date": key,
            "label": rel,
            "date_label": d.strftime("%d.%m."),
            "tours": by_day.get(key, []),
            "count": len(by_day.get(key, [])),
        })

    return {
        "summary": {
            "tours": sum_count,
            "paid_total": round(sum_paid, 2),
            "to_collect_total": round(sum_collect, 2),
            "partner_tours": sum_partner,
        },
        "days": days_out,
    }
