"""Availability engine.

Authority order (per business rules):
 1. Database (active, capacity, no overlapping booking)
 2. Google Calendar (second gate)
The AI never guesses; it must call this.
"""
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.asset import Asset
from app.models.booking import Booking
from app.integrations.google_calendar import calendar_service
from app.services import pricing
from app.core.logging import get_logger

log = get_logger("availability")

ACTIVE_BOOKING_STATUSES = ("pending", "confirmed")


def _db_overlaps(db: Session, asset_id: int, start: datetime, end: datetime,
                 exclude_booking_id: int | None = None) -> bool:
    q = db.query(Booking).filter(
        Booking.asset_id == asset_id,
        Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        and_(Booking.start_datetime < end, Booking.end_datetime > start),
    )
    if exclude_booking_id is not None:
        q = q.filter(Booking.id != exclude_booking_id)
    return db.query(q.exists()).scalar()


def is_asset_available(db: Session, asset: Asset, start: datetime, end: datetime,
                       exclude_booking_id: int | None = None) -> bool:
    if not asset.active:
        return False
    if _db_overlaps(db, asset.id, start, end, exclude_booking_id):
        return False
    if not calendar_service.check_availability(asset.calendar_id, start, end):
        return False
    return True


def find_available(db: Session, asset_type: str, passengers: int,
                   start: datetime, end: datetime) -> List[dict]:
    candidates = db.query(Asset).filter(
        Asset.asset_type == asset_type,
        Asset.active.is_(True),
        Asset.capacity >= passengers,   # Rule 1
    ).all()

    results = []
    for asset in candidates:
        if is_asset_available(db, asset, start, end):
            entry = {"asset": asset, "packages": pricing.list_packages(asset)}
            # Legacy time-based quote only when the asset has no packages.
            if not entry["packages"]:
                entry["quote"] = pricing.quote(asset, start, end)
            results.append(entry)
    log.info("availability_query", asset_type=asset_type, passengers=passengers,
             candidates=len(candidates), available=len(results))
    return results
