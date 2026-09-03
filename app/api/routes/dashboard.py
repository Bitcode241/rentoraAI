from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from app.core.database import get_db
from app.core.security import get_current_user

router = APIRouter(tags=["dashboard"])


@router.get("/admin", include_in_schema=False)
def admin():
    return FileResponse("app/static/admin.html", media_type="text/html")


@router.get("/api/dashboard/log")
def dashboard_log(limit: int = 100, entity: str = "", q: str = "",
                  db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Audit trail — who changed what and when. The owner's safety net."""
    from app.models.audit import AuditLog
    qry = db.query(AuditLog)
    if entity:
        qry = qry.filter(AuditLog.entity == entity)
    if q:
        like = f"%{q}%"
        qry = qry.filter(AuditLog.detail.ilike(like) | AuditLog.action.ilike(like))
    rows = qry.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).all()
    out = []
    for r in rows:
        # detail holds "human summary\n{json}" — show only the summary line
        summary = (r.detail or "").split("\n")[0]
        out.append({
            "id": r.id,
            "at": r.created_at,
            "actor": r.actor or "system",
            "action": r.action or "",
            "entity": r.entity or "",
            "entity_id": r.entity_id or "",
            "summary": summary[:300],
        })
    return {"count": len(out), "items": out}


@router.get("/api/dashboard/free")
def dashboard_free(asset_type: str = "jetski", days: int = 10,
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Per-day availability for the next `days` days — how many units are free in
    each hour slot, so a WhatsApp question can be answered in seconds."""
    from datetime import datetime, timedelta
    from app.models.booking import Booking
    from app.models.asset import Asset
    from app.core.timeutil import to_local, local_to_utc
    from app.services import settings_service

    units = (db.query(Asset)
             .filter(Asset.asset_type == asset_type,
                     Asset.active == True,  # noqa: E712
                     Asset.out_of_service == False)  # noqa: E712
             .all())
    total_units = len(units)
    unit_ids = [u.id for u in units]
    if not unit_ids:
        return {"asset_type": asset_type, "units": 0, "days": []}

    try:
        open_h = int(settings_service.get(db, "open_hour", "8") or 8)
        close_h = int(settings_service.get(db, "close_hour", "20") or 20)
    except (TypeError, ValueError):
        open_h, close_h = 8, 20

    today_local = to_local(datetime.now(timezone.utc)).date()
    win_start = local_to_utc(datetime.combine(today_local, datetime.min.time()))
    win_end = win_start + timedelta(days=days)
    bookings = (db.query(Booking)
                .filter(Booking.asset_id.in_(unit_ids),
                        Booking.start_datetime < win_end,
                        Booking.end_datetime > win_start,
                        Booking.status != "cancelled")
                .all())

    def _aware(dt):
        """DB rows can come back naive; treat those as UTC so comparisons work."""
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    out = []
    for d in range(days):
        day = today_local + timedelta(days=d)
        slots = []
        busiest = 0
        for h in range(open_h, close_h):
            slot_start = local_to_utc(datetime.combine(day, datetime.min.time())
                                      + timedelta(hours=h))
            slot_end = slot_start + timedelta(hours=1)
            ss, se = _aware(slot_start), _aware(slot_end)
            used = sum(1 for b in bookings
                       if _aware(b.start_datetime) < se
                       and _aware(b.end_datetime) > ss)
            busiest = max(busiest, used)
            slots.append({"hour": h, "free": max(total_units - used, 0),
                          "used": used})
        out.append({
            "date": day.isoformat(),
            "weekday": day.strftime("%a"),
            "slots": slots,
            "fully_free": busiest == 0,
            "peak_used": busiest,
        })
    return {"asset_type": asset_type, "units": total_units, "days": out}


@router.get("/api/dashboard/day")
def dashboard_day(date: str = "", db: Session = Depends(get_db),
                  _=Depends(get_current_user)):
    """Everything for one day: who's coming, when, how much to collect, phone.
    Defaults to today (Croatian time)."""
    from datetime import datetime, timedelta
    from app.models.booking import Booking
    from app.models.customer import Customer
    from app.models.asset import Asset
    from app.core.timeutil import to_local, local_to_utc

    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "Neispravan datum (očekujem YYYY-MM-DD).")
    else:
        day = to_local(datetime.now(timezone.utc)).date()

    start = local_to_utc(datetime.combine(day, datetime.min.time()))
    end = start + timedelta(days=1)
    rows = (db.query(Booking)
            .filter(Booking.start_datetime >= start,
                    Booking.start_datetime < end,
                    Booking.status != "cancelled")
            .order_by(Booking.start_datetime)
            .all())
    cust_ids = {b.customer_id for b in rows if b.customer_id}
    asset_ids = {b.asset_id for b in rows if b.asset_id}
    customers = {c.id: c for c in db.query(Customer).filter(
        Customer.id.in_(cust_ids)).all()} if cust_ids else {}
    assets = {a.id: a for a in db.query(Asset).filter(
        Asset.id.in_(asset_ids)).all()} if asset_ids else {}

    items, to_collect, guests_total = [], 0.0, 0
    groups = {}
    for b in rows:
        c = customers.get(b.customer_id)
        a = assets.get(b.asset_id)
        settled = (b.amount_paid or 0) + (getattr(b, "cash_collected", 0) or 0)
        balance = round(max((b.total_price or 0) - settled, 0), 2)
        to_collect += balance
        guests_total += getattr(b, "passengers", 0) or 0
        name = (c.full_name or "").strip() if c else ""
        if name and "@" in name and name == (c.email or ""):
            name = ""
        # one guest taking several units at the same time is ONE line
        key = (b.customer_id, b.start_datetime, b.package_name)
        if key in groups:
            g = groups[key]
            g["units"] += 1
            g["passengers"] += getattr(b, "passengers", 0) or 0
            g["total"] += b.total_price or 0
            g["paid"] += settled
            g["balance"] += balance
            g["ids"].append(b.id)
            if balance > 0:
                g["payment_status"] = b.payment_status
            continue
        groups[key] = {
            "id": b.id,
            "ids": [b.id],
            "units": 1,
            "time": b.start_datetime,
            "guest": name or "Gost",
            "phone": (c.phone if c else "") or "",
            "email": (c.email if c else "") or "",
            "asset": (a.name if a else "") or f"#{b.asset_id}",
            "tour": b.package_name or "",
            "passengers": getattr(b, "passengers", 0) or 0,
            "total": round(b.total_price or 0, 2),
            "paid": round(settled, 2),
            "balance": balance,
            "pickup": getattr(b, "pickup_location", "") or "",
            "status": b.status,
            "payment_status": b.payment_status,
        }
    for g in groups.values():
        g["total"] = round(g["total"], 2)
        g["paid"] = round(g["paid"], 2)
        g["balance"] = round(g["balance"], 2)
        items.append(g)
    items.sort(key=lambda x: x["time"])
    return {
        "date": day.isoformat(),
        "count": len(items),
        "guests": guests_total,
        "to_collect": round(to_collect, 2),
        "items": items,
    }


@router.get("/api/dashboard/money")
def dashboard_money(days: int = 30, db: Session = Depends(get_db),
                    _=Depends(get_current_user)):
    """Revenue split (online vs cash) with VAT and card fees."""
    from app.services import money_service
    return money_service.money_overview(db, days)


@router.get("/api/dashboard/sources")
def dashboard_sources(db: Session = Depends(get_db),
                      _=Depends(get_current_user)):
    """Where paid bookings came from (Google Ads, WhatsApp, Instagram, direct...)."""
    from app.services import attribution_service
    return {"sources": attribution_service.source_report(db, only_paid=True)}


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
