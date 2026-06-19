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


@router.get("/business")
def get_business(db: Session = Depends(get_db), _=Depends(get_current_user)):
    from app.services import settings_service
    return {
        "business_name": settings_service.business_name(db),
        "business_oib": settings_service.get(db, "business_oib", "") or "",
        "default_deposit_percent": settings_service.default_deposit_percent(db),
        "jetski_extra_person_fee": settings_service.jetski_extra_person_fee(db),
        "brand_boat": settings_service.brand_for_type(db, "boat"),
        "brand_jetski": settings_service.brand_for_type(db, "jetski"),
        "brand_transfer": settings_service.brand_for_type(db, "transfer"),
        "widget_accent_jetski": settings_service.widget_accent(db, "jetski"),
        "widget_accent_boat": settings_service.widget_accent(db, "boat"),
        "widget_accent_transfer": settings_service.widget_accent(db, "transfer"),
    }


@router.put("/business", dependencies=[Depends(require_admin)])
def update_business(payload: dict, db: Session = Depends(get_db)):
    from app.services import settings_service
    if "business_name" in payload:
        settings_service.set(db, settings_service.BUSINESS_NAME_KEY,
                             str(payload["business_name"]).strip())
    if "business_oib" in payload:
        settings_service.set(db, "business_oib", str(payload["business_oib"]).strip())
    if "default_deposit_percent" in payload:
        settings_service.set(db, settings_service.DEFAULT_DEPOSIT_KEY,
                             str(payload["default_deposit_percent"]))
    if "jetski_extra_person_fee" in payload:
        settings_service.set(db, "jetski_extra_person_fee",
                             str(payload["jetski_extra_person_fee"]))
    for k in ("brand_boat", "brand_jetski", "brand_transfer"):
        if k in payload:
            settings_service.set(db, k, str(payload[k]).strip())
    if "widget_accent" in payload:
        settings_service.set(db, "widget_accent", str(payload["widget_accent"]).strip())
    for t in ("jetski", "boat", "transfer"):
        k = f"widget_accent_{t}"
        if k in payload:
            settings_service.set(db, k, str(payload[k]).strip())
    return {"ok": True}
