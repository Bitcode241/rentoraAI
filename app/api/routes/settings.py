from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.services import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/lead-times")
def get_lead_times(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return settings_service.get_lead_times(db)


@router.put("/lead-times", dependencies=[Depends(require_admin)])
def update_lead_times(payload: dict, db: Session = Depends(get_db)):
    """Body: {"jetski": 2, "boat": 8, "transfer": 3}. Values are hours."""
    clean = {}
    for k in ("jetski", "boat", "transfer"):
        if k in payload:
            try:
                clean[k] = max(0, int(payload[k]))
            except (ValueError, TypeError):
                pass
    return settings_service.set_lead_times(db, clean)


@router.post("/send-reminders", dependencies=[Depends(require_admin)])
def trigger_reminders(db: Session = Depends(get_db)):
    """Manually run the day-before reminder job now (for testing)."""
    from app.services.reminder_service import send_reminders
    return send_reminders(db)
