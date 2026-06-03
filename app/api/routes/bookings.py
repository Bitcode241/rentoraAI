from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.booking import Booking
from app.schemas import BookingCreate, BookingUpdate, BookingOut
from app.services import booking_service

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


@router.get("", response_model=List[BookingOut])
def list_bookings(status: Optional[str] = None, db: Session = Depends(get_db),
                  _=Depends(get_current_user)):
    q = db.query(Booking)
    if status:
        q = q.filter(Booking.status == status)
    return q.order_by(Booking.start_datetime.desc()).all()


@router.post("", response_model=BookingOut)
def create_booking(payload: BookingCreate, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    return booking_service.create_booking(
        db, payload.asset_id, payload.customer_id,
        payload.start_datetime, payload.end_datetime,
        source=payload.source, notes=payload.notes, actor=user.username,
        package_id=payload.package_id)


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    return b


@router.post("/{booking_id}/confirm", response_model=BookingOut)
def confirm_booking(booking_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return booking_service.confirm_booking(db, booking_id, actor=user.username)


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return booking_service.cancel_booking(db, booking_id, actor=user.username)


@router.patch("/{booking_id}", response_model=BookingOut)
def update_booking(booking_id: int, payload: BookingUpdate,
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Booking not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(b, k, v)
    db.commit()
    db.refresh(b)
    return b
