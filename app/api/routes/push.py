from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.push import PushSubscription
from app.services import push_service

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("/key")
def get_public_key(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Public VAPID key the browser needs to subscribe."""
    return {"key": push_service.public_key(db)}


@router.post("/subscribe")
def subscribe(payload: dict, db: Session = Depends(get_db),
              _=Depends(get_current_user)):
    """Register this device for booking notifications."""
    sub = payload.get("subscription") or payload
    label = (payload.get("label") or "").strip()
    try:
        row = push_service.save_subscription(db, sub, label)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "id": row.id, "label": row.label}


@router.post("/unsubscribe")
def unsubscribe(payload: dict, db: Session = Depends(get_db),
                _=Depends(get_current_user)):
    push_service.remove_subscription(db, payload.get("endpoint", ""))
    return {"ok": True}


@router.get("/devices")
def devices(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(PushSubscription).all()
    return {"devices": [{"id": r.id, "label": r.label or "Uređaj",
                         "created_at": r.created_at} for r in rows]}


@router.post("/test")
def send_test(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Send a test notification to all registered devices."""
    res = push_service.send_to_all(
        db, "Rentora — test", "Ovako će izgledati obavijest o novoj rezervaciji.")
    return {"ok": True, **res}
