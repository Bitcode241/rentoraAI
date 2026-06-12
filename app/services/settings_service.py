"""Admin-editable settings (key-value), with lead-time rules.

Lead time = minimum hours before start that a booking is allowed.
Defaults: jetski 2h, boat 8h, transfer 3h. All editable in the admin panel.
"""
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.app_setting import AppSetting

LEAD_TIME_KEY = "lead_time_hours"
DEFAULT_DEPOSIT_KEY = "default_deposit_percent"
BUSINESS_NAME_KEY = "business_name"
# Per-type brand names. Guests booking a boat see the boat brand, jetski guests
# the jetski brand, transfers the transfer brand. Falls back to the global name.
BRAND_KEYS = {
    "boat": "brand_boat",
    "jetski": "brand_jetski",
    "transfer": "brand_transfer",
    "car": "brand_transfer",
    "van": "brand_transfer",
}
_BRAND_FALLBACKS = {
    "boat": "Seagull Dubrovnik",
    "jetski": "Jetski Dubrovnik",
    "transfer": "Ragusa Transfer",
    "car": "Ragusa Transfer",
    "van": "Ragusa Transfer",
}


def business_name(db: Session, fallback: str = "Seagull Dubrovnik") -> str:
    """Global company name (used when no per-type brand applies)."""
    v = get(db, BUSINESS_NAME_KEY, None)
    return (v or "").strip() or fallback


def brand_for_type(db: Session, asset_type: str) -> str:
    """Brand shown to guests for a given asset type. Boats -> Seagull,
    jetski -> Jetski Dubrovnik, transfer -> Ragusa Transfer, etc. Each is
    editable in admin; falls back to a sensible default, then the global name."""
    t = (asset_type or "").lower()
    key = BRAND_KEYS.get(t)
    if key:
        v = (get(db, key, None) or "").strip()
        if v:
            return v
    # fall back to a type default, else the global business name
    return _BRAND_FALLBACKS.get(t) or business_name(db)


def default_deposit_percent(db: Session, fallback: float = 30.0) -> float:
    """Global default deposit %, used when an asset has none set (avoids 0 deposit)."""
    try:
        v = get(db, DEFAULT_DEPOSIT_KEY, None)
        return float(v) if v is not None else fallback
    except (TypeError, ValueError):
        return fallback
DEFAULT_LEAD_TIMES = {"jetski": 2, "boat": 8, "transfer": 3}


def get(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    return row.value if row else default


def set(db: Session, key: str, value: str):
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def get_lead_times(db: Session) -> dict:
    raw = get(db, LEAD_TIME_KEY)
    if raw:
        try:
            data = json.loads(raw)
            # merge over defaults so missing keys still work
            return {**DEFAULT_LEAD_TIMES, **data}
        except (ValueError, TypeError):
            pass
    return dict(DEFAULT_LEAD_TIMES)


def set_lead_times(db: Session, times: dict):
    merged = {**DEFAULT_LEAD_TIMES, **times}
    set(db, LEAD_TIME_KEY, json.dumps(merged))
    return merged


def lead_time_hours(db: Session, asset_type: str) -> int:
    return get_lead_times(db).get(asset_type, 0)


def check_lead_time(db: Session, asset_type: str, start: datetime) -> dict:
    """Return {'ok': bool, 'min_hours': int, 'message': str}.
    Booking is allowed only if start is at least min_hours from now."""
    hours = lead_time_hours(db, asset_type)
    if hours <= 0:
        return {"ok": True, "min_hours": 0, "message": ""}
    now = datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    earliest = now + timedelta(hours=hours)
    if start < earliest:
        return {
            "ok": False, "min_hours": hours,
            "message": f"This must be booked at least {hours}h in advance.",
        }
    return {"ok": True, "min_hours": hours, "message": ""}
