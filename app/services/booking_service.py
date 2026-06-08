"""Booking service. Enforces no-overlap, calendar checks, event creation."""
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.asset import Asset
from app.models.customer import Customer
from app.models.booking import Booking
from app.services import pricing, availability, audit
from app.integrations.google_calendar import calendar_service
from app.core.logging import get_logger

log = get_logger("booking")


def create_booking(db: Session, asset_id: int, customer_id: int,
                   start: datetime, end: datetime, source: str = "admin",
                   notes: str = "", actor: str = "system",
                   auto_confirm: bool = False, package_id: int = None,
                   passengers: int = 0) -> Booking:
    if end <= start:
        raise HTTPException(400, "end_datetime must be after start_datetime")

    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")

    # Lead-time rule: can't book inside the minimum-advance window.
    # Admin bookings (source="admin") may override, since the owner knows best.
    if source != "admin":
        from app.services import settings_service
        lt = settings_service.check_lead_time(db, asset.asset_type, start)
        if not lt["ok"]:
            raise HTTPException(409, lt["message"])

    # Rule 2 + Rule 3: no overlap, check calendar
    if not availability.is_asset_available(db, asset, start, end):
        raise HTTPException(409, "Asset not available for the requested window")

    # Price: by chosen package if given, else legacy time-based.
    package_name = ""
    if package_id is not None:
        from app.models.package import RentalPackage
        pkg = db.get(RentalPackage, package_id)
        if not pkg or pkg.asset_id != asset_id:
            raise HTTPException(400, "Invalid package for this asset")
        q = pricing.quote_package(asset, pkg)
        package_name = pkg.name
    else:
        q = pricing.quote(asset, start, end)

    booking = Booking(
        asset_id=asset_id, customer_id=customer_id,
        start_datetime=start, end_datetime=end,
        total_price=q["total_price"], deposit_amount=q["deposit_amount"],
        package_id=package_id, package_name=package_name,
        status="confirmed" if auto_confirm else "pending",
        source=source, notes=notes, passengers=passengers or 0,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    if auto_confirm:
        _create_calendar_event(db, booking, asset, customer)

    audit.record(db, "booking_created", actor=actor, entity="booking",
                 entity_id=booking.id, detail=f"{asset.name} {start}->{end}")
    log.info("booking_created", booking_id=booking.id, status=booking.status)
    return booking


def confirm_booking(db: Session, booking_id: int, actor: str = "system") -> Booking:
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")
    asset = db.get(Asset, booking.asset_id)
    # Rule 3: re-check before confirmation
    if not availability.is_asset_available(db, asset, booking.start_datetime,
                                           booking.end_datetime,
                                           exclude_booking_id=booking.id):
        # allow if the only overlap is this same booking
        booking.status = "pending"
        db.commit()
        raise HTTPException(409, "No longer available; cannot confirm")
    booking.status = "confirmed"
    db.commit()
    customer = db.get(Customer, booking.customer_id)
    _create_calendar_event(db, booking, asset, customer)
    audit.record(db, "booking_confirmed", actor=actor, entity="booking", entity_id=booking.id)
    return booking


def cancel_booking(db: Session, booking_id: int, actor: str = "system") -> Booking:
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")
    asset = db.get(Asset, booking.asset_id)
    if booking.calendar_event_id and asset:
        calendar_service.cancel_event(asset.calendar_id, booking.calendar_event_id)
    booking.status = "cancelled"
    db.commit()
    audit.record(db, "booking_cancelled", actor=actor, entity="booking", entity_id=booking.id)
    log.info("booking_cancelled", booking_id=booking.id)
    return booking


def _create_calendar_event(db: Session, booking: Booking, asset: Asset, customer: Customer):
    # Rule 4: always create calendar events on confirmation
    event_id = calendar_service.create_event(
        asset.calendar_id,
        summary=f"{asset.name} - {customer.full_name}",
        start=booking.start_datetime, end=booking.end_datetime,
        description=f"Booking #{booking.id} | {customer.phone} {customer.email}",
    )
    if event_id:
        booking.calendar_event_id = event_id
        db.commit()
