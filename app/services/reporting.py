"""Reporting: daily/weekly/monthly bookings, revenue, utilization."""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.booking import Booking
from app.models.asset import Asset

REVENUE_STATUSES = ("confirmed", "completed")


def _count_between(db: Session, start: datetime, end: datetime) -> int:
    return db.query(Booking).filter(
        Booking.created_at >= start, Booking.created_at < end).count()


def bookings_summary(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    day = now - timedelta(days=1)
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)
    return {
        "daily": _count_between(db, day, now),
        "weekly": _count_between(db, week, now),
        "monthly": _count_between(db, month, now),
        "total": db.query(Booking).count(),
    }


def revenue_report(db: Session) -> dict:
    total = db.query(func.coalesce(func.sum(Booking.total_price), 0.0)).filter(
        Booking.status.in_(REVENUE_STATUSES)).scalar()
    deposits = db.query(func.coalesce(func.sum(Booking.deposit_amount), 0.0)).filter(
        Booking.status.in_(REVENUE_STATUSES)).scalar()
    by_status = dict(
        db.query(Booking.status, func.count(Booking.id)).group_by(Booking.status).all())
    return {"revenue": round(total or 0, 2),
            "deposits_held": round(deposits or 0, 2),
            "bookings_by_status": by_status}


def asset_utilization(db: Session) -> list:
    rows = (db.query(Asset.id, Asset.name, Asset.asset_type,
                     func.count(Booking.id).label("bookings"),
                     func.coalesce(func.sum(Booking.total_price), 0.0).label("revenue"))
            .outerjoin(Booking, (Booking.asset_id == Asset.id) &
                       (Booking.status.in_(REVENUE_STATUSES)))
            .group_by(Asset.id).all())
    return [{"asset_id": r[0], "name": r[1], "type": r[2],
             "bookings": r[3], "revenue": round(r[4] or 0, 2)} for r in rows]


def upcoming_reservations(db: Session, limit: int = 20):
    now = datetime.now(timezone.utc)
    return (db.query(Booking).filter(Booking.start_datetime >= now,
            Booking.status.in_(("pending", "confirmed")))
            .order_by(Booking.start_datetime.asc()).limit(limit).all())


def todays_reservations(db: Session):
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return (db.query(Booking).filter(Booking.start_datetime >= start,
            Booking.start_datetime < end).order_by(Booking.start_datetime.asc()).all())
