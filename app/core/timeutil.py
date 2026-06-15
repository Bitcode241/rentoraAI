"""Local-time formatting. Bookings are stored in UTC; guests/partners think in
local Dubrovnik time (Europe/Zagreb). Always format for humans in local time.
"""
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _LOCAL = ZoneInfo("Europe/Zagreb")
except Exception:  # pragma: no cover
    _LOCAL = None


def to_local(dt: datetime) -> datetime:
    """Convert a (possibly naive UTC) datetime to local Europe/Zagreb time."""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if _LOCAL is not None:
        return dt.astimezone(_LOCAL)
    return dt


def fmt_local(dt: datetime, pattern: str = "%d.%m.%Y %H:%M") -> str:
    """Format a datetime in local time for display."""
    if dt is None:
        return ""
    return to_local(dt).strftime(pattern)


def local_to_utc(dt: datetime) -> datetime:
    """Interpret a NAIVE datetime as local Europe/Zagreb wall-clock time and return
    the equivalent UTC datetime for storage. Used for times the guest typed in the
    widget (they mean local time, e.g. 09:00 in Dubrovnik)."""
    if dt is None:
        return dt
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    if _LOCAL is not None:
        return dt.replace(tzinfo=_LOCAL).astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)
