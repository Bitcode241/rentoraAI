from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.transfer import TransferZone
from app.services import transfer_service

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


class ZoneIn(BaseModel):
    name: str
    car_price: float = 0.0
    van_price: float = 0.0
    sort_order: int = 0
    active: bool = True


class ZoneOut(ZoneIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


@router.get("/zones", response_model=List[ZoneOut])
def list_zones(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(TransferZone).order_by(TransferZone.sort_order).all()


@router.post("/zones", response_model=ZoneOut, dependencies=[Depends(require_admin)])
def create_zone(payload: ZoneIn, db: Session = Depends(get_db)):
    if db.query(TransferZone).filter(TransferZone.name == payload.name).first():
        raise HTTPException(409, "Zone with that name already exists")
    z = TransferZone(**payload.model_dump())
    db.add(z)
    db.commit()
    db.refresh(z)
    return z


@router.patch("/zones/{zone_id}", response_model=ZoneOut,
              dependencies=[Depends(require_admin)])
def update_zone(zone_id: int, payload: ZoneIn, db: Session = Depends(get_db)):
    z = db.get(TransferZone, zone_id)
    if not z:
        raise HTTPException(404, "Zone not found")
    for k, v in payload.model_dump().items():
        setattr(z, k, v)
    db.commit()
    db.refresh(z)
    return z


@router.delete("/zones/{zone_id}", dependencies=[Depends(require_admin)])
def delete_zone(zone_id: int, db: Session = Depends(get_db)):
    z = db.get(TransferZone, zone_id)
    if not z:
        raise HTTPException(404, "Zone not found")
    db.delete(z)
    db.commit()
    return {"deleted": zone_id}


@router.get("/quote")
def quote(location: str, passengers: int, round_trip: bool = False,
          db: Session = Depends(get_db), _=Depends(get_current_user)):
    zone = transfer_service.find_zone(db, location)
    if not zone:
        return {"error": "unknown_location",
                "known_zones": [z["name"] for z in transfer_service.list_zones(db)]}
    return transfer_service.quote_transfer(zone, passengers, round_trip)
