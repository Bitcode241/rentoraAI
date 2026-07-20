"""Admin API for the tour catalog: one tour = one id, applies to all units.
Create/edit/delete tours here; changes propagate to every physical unit's
packages so availability keeps working. Includes a per-tour sales report.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.tour_type import TourType
from app.services import tour_service

router = APIRouter(prefix="/api/tours", tags=["tours"])


def _out(t: TourType) -> dict:
    return {
        "id": t.id, "asset_type": t.asset_type, "name": t.name,
        "duration_minutes": t.duration_minutes, "price": t.price,
        "deposit_percent": t.deposit_percent, "guided": t.guided,
        "description": t.description, "sort_order": t.sort_order,
        "active": t.active,
    }


@router.get("")
def list_tours(asset_type: str = "", db: Session = Depends(get_db),
               _=Depends(get_current_user)):
    return [_out(t) for t in tour_service.list_tours(db, asset_type)]


@router.get("/report")
def tours_report(asset_type: str = "", db: Session = Depends(get_db),
                 _=Depends(get_current_user)):
    return tour_service.tour_report(db, asset_type)


@router.post("")
def create_tour(payload: dict, db: Session = Depends(get_db),
                _=Depends(get_current_user)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Naziv ture je obavezan.")
    dur = int(payload.get("duration_minutes") or 0)
    if dur <= 0:
        raise HTTPException(400, "Trajanje mora biti veće od 0.")
    t = TourType(
        asset_type=(payload.get("asset_type") or "jetski"),
        name=name, duration_minutes=dur,
        price=float(payload.get("price") or 0),
        deposit_percent=float(payload.get("deposit_percent") or 0),
        guided=bool(payload.get("guided")),
        description=(payload.get("description") or "").strip(),
        sort_order=int(payload.get("sort_order") or dur),
        active=bool(payload.get("active", True)))
    db.add(t)
    db.commit()
    db.refresh(t)
    # push this tour onto every unit of that type
    tour_service.sync_tour_to_units(db, t)
    return _out(t)


@router.put("/{tour_id}")
def update_tour(tour_id: int, payload: dict, db: Session = Depends(get_db),
                _=Depends(get_current_user)):
    t = db.get(TourType, tour_id)
    if not t:
        raise HTTPException(404, "Tura nije pronađena.")
    old_name = t.name
    for k in ("name", "asset_type", "description"):
        if k in payload and payload[k] is not None:
            setattr(t, k, str(payload[k]).strip())
    for k in ("duration_minutes", "sort_order"):
        if k in payload and payload[k] is not None:
            setattr(t, k, int(payload[k]))
    for k in ("price", "deposit_percent"):
        if k in payload and payload[k] is not None:
            setattr(t, k, float(payload[k]))
    if "guided" in payload:
        t.guided = bool(payload["guided"])
    if "active" in payload:
        t.active = bool(payload["active"])
    db.commit()
    db.refresh(t)
    # if the name changed, remove the old per-unit packages first
    if old_name != t.name:
        stale = TourType(asset_type=t.asset_type, name=old_name,
                         duration_minutes=t.duration_minutes)
        tour_service.remove_tour_from_units(db, stale)
    tour_service.sync_tour_to_units(db, t)
    return _out(t)


@router.delete("/{tour_id}")
def delete_tour(tour_id: int, db: Session = Depends(get_db),
                _=Depends(get_current_user)):
    t = db.get(TourType, tour_id)
    if not t:
        raise HTTPException(404, "Tura nije pronađena.")
    tour_service.remove_tour_from_units(db, t)
    db.delete(t)
    db.commit()
    return {"ok": True}
