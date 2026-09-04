"""Blocked periods — weather, servicing, or the owner keeping a unit.

A block behaves exactly like a booking for availability purposes: nothing can be
reserved on top of it. Blocks with no asset_id close every unit of that type,
which is what you want when the sea is too rough to go out at all.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.block import Block

log = get_logger(__name__)

REASONS = {
    "weather": "Vrijeme (bura/jugo)",
    "service": "Servis / popravak",
    "personal": "Osobno korištenje",
    "other": "Ostalo",
}


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def blocks_for(db: Session, asset_id: int, asset_type: str,
               start: datetime, end: datetime) -> list:
    """Blocks that overlap [start, end) for this unit (or its whole type)."""
    rows = (db.query(Block)
            .filter((Block.asset_id == asset_id) |
                    ((Block.asset_id.is_(None)) & (Block.asset_type == asset_type)))
            .all())
    s, e = _aware(start), _aware(end)
    return [b for b in rows
            if _aware(b.start_datetime) < e and _aware(b.end_datetime) > s]


def is_blocked(db: Session, asset_id: int, asset_type: str,
               start: datetime, end: datetime) -> bool:
    return bool(blocks_for(db, asset_id, asset_type, start, end))


def blocked_asset_ids(db: Session, asset_type: str,
                      start: datetime, end: datetime, unit_ids: list) -> set:
    """Which of `unit_ids` are unavailable in this window."""
    rows = (db.query(Block)
            .filter((Block.asset_id.in_(unit_ids)) |
                    ((Block.asset_id.is_(None)) & (Block.asset_type == asset_type)))
            .all())
    s, e = _aware(start), _aware(end)
    out = set()
    for b in rows:
        if _aware(b.start_datetime) < e and _aware(b.end_datetime) > s:
            if b.asset_id is None:
                return set(unit_ids)      # whole fleet closed
            out.add(b.asset_id)
    return out


def create(db: Session, *, asset_id=None, asset_type="", start, end,
           reason="weather", note="", created_by="") -> Block:
    if _aware(end) <= _aware(start):
        raise ValueError("Kraj mora biti nakon početka.")
    b = Block(asset_id=asset_id, asset_type=asset_type or "",
              start_datetime=start, end_datetime=end,
              reason=reason if reason in REASONS else "other",
              note=(note or "")[:255], created_by=created_by or "")
    db.add(b)
    db.commit()
    db.refresh(b)
    log.info("block_created", block_id=b.id, asset_id=asset_id,
             asset_type=asset_type, reason=b.reason)
    return b


def affected_bookings(db: Session, block: Block) -> list:
    """Existing bookings that fall inside a block — the owner must be warned so
    they can call those guests instead of finding out on the day."""
    from app.models.booking import Booking
    q = db.query(Booking).filter(Booking.status != "cancelled")
    if block.asset_id:
        q = q.filter(Booking.asset_id == block.asset_id)
    else:
        from app.models.asset import Asset
        ids = [a.id for a in db.query(Asset).filter(
            Asset.asset_type == block.asset_type).all()]
        if not ids:
            return []
        q = q.filter(Booking.asset_id.in_(ids))
    s, e = _aware(block.start_datetime), _aware(block.end_datetime)
    return [b for b in q.all()
            if _aware(b.start_datetime) < e and _aware(b.end_datetime) > s]
