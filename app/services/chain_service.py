"""Availability chain.

When several boats are the same model (e.g. your Barracuda 545 + two partners'
Barracuda 545s), the system offers the FIRST available one by priority: your own
boat first (priority 1), then the partners in the order you set. This maximises your
own utilisation, then fills from partners only when your boat is busy.

The owner controls the order via each asset's `booking_priority` (lower = first) and
groups interchangeable boats via `model_group`.
"""
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.services.availability import is_asset_available


def _group_of(asset: Asset) -> str:
    """The grouping key for interchangeable boats. Falls back to the name so a
    boat with no explicit group only matches itself."""
    return (getattr(asset, "model_group", "") or "").strip().lower() or \
        (asset.name or "").strip().lower()


def boats_in_group(db: Session, asset: Asset):
    """All active boats interchangeable with this one, sorted by priority then id."""
    group = _group_of(asset)
    candidates = db.query(Asset).filter(
        Asset.active.is_(True), Asset.asset_type == asset.asset_type).all()
    same = [a for a in candidates if _group_of(a) == group]
    same.sort(key=lambda a: (getattr(a, "booking_priority", 100) or 100, a.id))
    return same


def pick_for_window(db: Session, asset: Asset, start: datetime, end: datetime):
    """Given a requested boat (or any boat of its model), return the first
    available boat in the group by priority, or None if all are busy.
    Returns a dict: {asset, was_redirected, tried}.
    """
    chain = boats_in_group(db, asset)
    tried = []
    for a in chain:
        tried.append(a.name)
        if is_asset_available(db, a, start, end):
            return {"asset": a, "was_redirected": a.id != asset.id, "tried": tried}
    return {"asset": None, "was_redirected": False, "tried": tried}
