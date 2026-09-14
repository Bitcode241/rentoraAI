"""Local-time handling.

Bookings are stored in UTC; people think in local Dubrovnik time (Europe/Zagreb).
Two directions matter:

  to_local / fmt_local   – UTC out of the database  →  what a human should read
  parse_local_input      – what a human typed       →  UTC for storage

Getting the second one wrong is what makes a reminder say 20:00 for an 18:00 tour.
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


def parse_local_input(text: str) -> datetime:
    """Parse a date/time the operator typed, treating it as local wall-clock time
    and returning UTC for storage.

    `_parse` in the AI tools marks naive values as UTC, which is right for machine
    input but wrong for a human typing "18:00" — they mean 18:00 here.
    """
    from dateutil import parser as dtparser
    s = (text or "").strip()
    if not s:
        raise ValueError("empty datetime")
    try:
        out = datetime.fromisoformat(s)
    except ValueError:
        out = dtparser.parse(s, dayfirst=True, fuzzy=True)
    if out.tzinfo is not None:
        return out.astimezone(timezone.utc)
    return local_to_utc(out)
