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


# ---- GPS radius pricing ----
@router.get("/radii")
def list_radii(db: Session = Depends(get_db), _=Depends(get_current_user)):
    from app.models.transfer import TransferRadius
    rows = db.query(TransferRadius).order_by(TransferRadius.max_km).all()
    return [{"id": r.id, "label": r.label, "base_label": r.base_label,
             "base_lat": r.base_lat, "base_lng": r.base_lng, "max_km": r.max_km,
             "car_price": r.car_price, "van_price": r.van_price,
             "service": r.service, "active": r.active} for r in rows]


@router.post("/radii", dependencies=[Depends(require_admin)])
def create_radius(payload: dict, db: Session = Depends(get_db)):
    from app.models.transfer import TransferRadius
    # if the base address is given but no coords, geocode it once
    lat = float(payload.get("base_lat") or 0)
    lng = float(payload.get("base_lng") or 0)
    if (not lat or not lng) and payload.get("base_label"):
        from app.services.geo_service import geocode
        c = geocode(payload["base_label"])
        if c:
            lat, lng = c
    r = TransferRadius(
        label=payload.get("label", ""), base_label=payload.get("base_label", ""),
        base_lat=lat, base_lng=lng, max_km=float(payload.get("max_km") or 10),
        car_price=float(payload.get("car_price") or 0),
        van_price=float(payload.get("van_price") or 0),
        service=payload.get("service", "transfer"))
    db.add(r); db.commit(); db.refresh(r)
    return {"id": r.id, "base_lat": r.base_lat, "base_lng": r.base_lng}


@router.patch("/radii/{rid}", dependencies=[Depends(require_admin)])
def update_radius(rid: int, payload: dict, db: Session = Depends(get_db)):
    from app.models.transfer import TransferRadius
    r = db.get(TransferRadius, rid)
    if not r:
        return {"error": "not_found"}
    for k in ("label", "base_label", "service"):
        if k in payload:
            setattr(r, k, payload[k])
    for k in ("base_lat", "base_lng", "max_km", "car_price", "van_price"):
        if k in payload and payload[k] is not None:
            setattr(r, k, float(payload[k]))
    if "active" in payload:
        r.active = bool(payload["active"])
    # re-geocode if base address changed without explicit coords
    if payload.get("base_label") and not payload.get("base_lat"):
        from app.services.geo_service import geocode
        c = geocode(payload["base_label"])
        if c:
            r.base_lat, r.base_lng = c
    db.commit()
    return {"ok": True, "base_lat": r.base_lat, "base_lng": r.base_lng}


@router.delete("/radii/{rid}", dependencies=[Depends(require_admin)])
def delete_radius(rid: int, db: Session = Depends(get_db)):
    from app.models.transfer import TransferRadius
    r = db.get(TransferRadius, rid)
    if r:
        db.delete(r); db.commit()
    return {"ok": True}
