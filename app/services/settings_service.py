"""Admin-editable settings (key-value), with lead-time rules.

Lead time = minimum hours before start that a booking is allowed.
Defaults: jetski 2h, boat 8h, transfer 3h. All editable in the admin panel.
"""
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.app_setting import AppSetting

LEAD_TIME_KEY = "lead_time_hours"
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
