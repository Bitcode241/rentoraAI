from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.block import Block
from app.services import block_service

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


def _actor(user) -> str:
    return getattr(user, "username", None) or "admin"


def _out(b: Block, db: Session) -> dict:
    from app.models.asset import Asset
    a = db.get(Asset, b.asset_id) if b.asset_id else None
    return {
        "id": b.id,
        "asset_id": b.asset_id,
        "asset_name": (a.name if a else ""),
        "asset_type": b.asset_type or (a.asset_type if a else ""),
        "scope": "unit" if b.asset_id else "fleet",
        "start": b.start_datetime,
        "end": b.end_datetime,
        "reason": b.reason,
        "reason_label": block_service.REASONS.get(b.reason, b.reason),
        "note": b.note or "",
        "created_by": b.created_by or "",
    }


@router.get("")
def list_blocks(upcoming: bool = True, db: Session = Depends(get_db),
                _=Depends(get_current_user)):
    """Current and future blocks (past ones are noise)."""
    from datetime import datetime, timezone
    rows = db.query(Block).order_by(Block.start_datetime).all()
    if upcoming:
        now = datetime.now(timezone.utc)
        rows = [b for b in rows
                if block_service._aware(b.end_datetime) >= now]
    return {"reasons": block_service.REASONS,
            "blocks": [_out(b, db) for b in rows]}


@router.post("")
def create_block(payload: dict, db: Session = Depends(get_db),
                 _=Depends(get_current_user)):
    """Block a unit, or the whole fleet of a type, for a period."""
    from app.ai.tools import _parse
    from app.services import audit
    try:
        start = _parse(str(payload.get("start") or ""))
        end = _parse(str(payload.get("end") or ""))
    except Exception:
        raise HTTPException(400, "Neispravan datum/vrijeme.")
    asset_id = payload.get("asset_id") or None
    asset_type = (payload.get("asset_type") or "").strip()
    if not asset_id and not asset_type:
        raise HTTPException(400, "Odaberi jedinicu ili tip flote.")
    try:
        b = block_service.create(
            db, asset_id=int(asset_id) if asset_id else None,
            asset_type=asset_type, start=start, end=end,
            reason=(payload.get("reason") or "weather"),
            note=payload.get("note") or "", created_by=_actor(_))
    except ValueError as e:
        raise HTTPException(400, str(e))
    # warn about guests who already booked inside this period
    hit = block_service.affected_bookings(db, b)
    audit.record(db, "block_created", actor=_actor(_), entity="block",
                 entity_id=b.id,
                 detail=f"{block_service.REASONS.get(b.reason, b.reason)} · "
                        f"{'cijela flota' if not b.asset_id else 'jedinica #' + str(b.asset_id)} · "
                        f"{start:%d.%m. %H:%M} – {end:%d.%m. %H:%M}"
                        + (f" · pogađa {len(hit)} rezervacija" if hit else ""))
    return {"ok": True, "block": _out(b, db),
            "affected": [{"id": x.id, "start": x.start_datetime,
                          "package": x.package_name or ""} for x in hit]}


@router.delete("/{block_id}")
def delete_block(block_id: int, db: Session = Depends(get_db),
                 _=Depends(get_current_user)):
    from app.services import audit
    b = db.get(Block, block_id)
    if not b:
        raise HTTPException(404, "Blokada nije pronađena.")
    db.delete(b)
    db.commit()
    audit.record(db, "block_removed", actor=_actor(_), entity="block",
                 entity_id=block_id, detail="Blokada uklonjena")
    return {"ok": True}
