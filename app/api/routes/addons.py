from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.addon import AddOn

router = APIRouter(prefix="/api/addons", tags=["addons"])


def _ser(a: AddOn) -> dict:
    return {"id": a.id, "name": a.name, "description": a.description,
            "price": a.price, "per_person": a.per_person,
            "applies_to": a.applies_to, "active": a.active,
            "sort_order": a.sort_order}


@router.get("")
def list_addons(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(AddOn).order_by(AddOn.sort_order, AddOn.id).all()
    return [_ser(a) for a in rows]


@router.post("", dependencies=[Depends(require_admin)])
def create_addon(payload: dict, db: Session = Depends(get_db)):
    a = AddOn(name=payload.get("name", ""),
              description=payload.get("description", ""),
              price=float(payload.get("price") or 0),
              per_person=bool(payload.get("per_person")),
              applies_to=payload.get("applies_to", ""),
              sort_order=int(payload.get("sort_order") or 0))
    db.add(a); db.commit(); db.refresh(a)
    return _ser(a)


@router.patch("/{aid}", dependencies=[Depends(require_admin)])
def update_addon(aid: int, payload: dict, db: Session = Depends(get_db)):
    a = db.get(AddOn, aid)
    if not a:
        return {"error": "not_found"}
    for k in ("name", "description", "applies_to"):
        if k in payload:
            setattr(a, k, payload[k])
    if "price" in payload and payload["price"] is not None:
        a.price = float(payload["price"])
    if "per_person" in payload:
        a.per_person = bool(payload["per_person"])
    if "active" in payload:
        a.active = bool(payload["active"])
    if "sort_order" in payload and payload["sort_order"] is not None:
        a.sort_order = int(payload["sort_order"])
    db.commit()
    return _ser(a)


@router.delete("/{aid}", dependencies=[Depends(require_admin)])
def delete_addon(aid: int, db: Session = Depends(get_db)):
    a = db.get(AddOn, aid)
    if a:
        db.delete(a); db.commit()
    return {"ok": True}
