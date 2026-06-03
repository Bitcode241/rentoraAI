from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.services import reporting
from app.schemas import BookingOut

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/bookings")
def bookings(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return reporting.bookings_summary(db)


@router.get("/revenue")
def revenue(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return reporting.revenue_report(db)


@router.get("/utilization")
def utilization(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return reporting.asset_utilization(db)


@router.get("/upcoming", response_model=list[BookingOut])
def upcoming(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return reporting.upcoming_reservations(db)


@router.get("/today", response_model=list[BookingOut])
def today(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return reporting.todays_reservations(db)
