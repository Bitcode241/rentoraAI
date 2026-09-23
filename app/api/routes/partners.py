from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.roles import require
from app.models.partner import Partner
from app.services import partner_ledger

router = APIRouter(prefix="/api/partners", tags=["partners"])
require_money = require("money")


@router.get("")
def overview(db: Session = Depends(get_db), _=Depends(require_money)):
    """All partners with their current balance."""
    data = partner_ledger.overview(db)
    data["kinds"] = partner_ledger.KINDS
    return data


@router.post("")
def create_partner(payload: dict, db: Session = Depends(get_db),
                   _=Depends(require_money)):
    from app.services import audit
    name = (payload.get("name") or "").strip()
    if len(name) < 2:
        raise HTTPException(400, "Upiši naziv partnera.")
    p = Partner(name=name[:160],
                contact=(payload.get("contact") or "")[:160],
                phone=(payload.get("phone") or "")[:60],
                oib=(payload.get("oib") or "")[:20],
                note=(payload.get("note") or ""))
    db.add(p)
    db.commit()
    db.refresh(p)
    audit.record(db, "partner_created", actor=getattr(_, "username", "admin"),
                 entity="partner", entity_id=p.id, detail=name)
    return {"ok": True, "id": p.id, "name": p.name}


@router.get("/{partner_id}")
def statement(partner_id: int, db: Session = Depends(get_db),
              _=Depends(require_money)):
    data = partner_ledger.statement(db, partner_id)
    if not data:
        raise HTTPException(404, "Partner nije pronađen.")
    data["kinds"] = partner_ledger.KINDS
    return data


@router.post("/{partner_id}/referral")
def add_referral(partner_id: int, payload: dict, db: Session = Depends(get_db),
                 _=Depends(require_money)):
    """Log a guest sent to this partner."""
    from app.services import audit
    if not db.get(Partner, partner_id):
        raise HTTPException(404, "Partner nije pronađen.")
    try:
        e = partner_ledger.add_referral(
            db, partner_id=partner_id,
            tour_name=payload.get("tour_name") or "",
            guests=int(payload.get("guests") or 0),
            guest_paid=float(payload.get("guest_paid") or 0),
            partner_gets=float(payload.get("partner_gets") or 0),
            note=payload.get("note") or "",
            created_by=getattr(_, "username", "admin"))
    except (ValueError, TypeError) as ex:
        raise HTTPException(400, str(ex))
    audit.record(db, "partner_referral", actor=getattr(_, "username", "admin"),
                 entity="partner", entity_id=partner_id,
                 detail=f"{e.guests} gost(iju) · {e.tour_name} · "
                        f"gost platio {e.guest_paid:.2f}, partneru "
                        f"{e.partner_gets:.2f}, moja zarada {e.amount:.2f} EUR")
    return {"ok": True, "entry_id": e.id, "my_earning": e.amount,
            "balance": partner_ledger.balance(db, partner_id)}


@router.post("/{partner_id}/entry")
def add_entry(partner_id: int, payload: dict, db: Session = Depends(get_db),
              _=Depends(require_money)):
    """Add a manual line: old debt, payment made or received, correction."""
    from app.services import audit
    if not db.get(Partner, partner_id):
        raise HTTPException(404, "Partner nije pronađen.")
    try:
        e = partner_ledger.add_entry(
            db, partner_id=partner_id,
            kind=(payload.get("kind") or "adjust"),
            amount=float(payload.get("amount") or 0),
            note=payload.get("note") or "",
            created_by=getattr(_, "username", "admin"))
    except (ValueError, TypeError) as ex:
        raise HTTPException(400, str(ex))
    audit.record(db, "partner_entry", actor=getattr(_, "username", "admin"),
                 entity="partner", entity_id=partner_id,
                 detail=f"{partner_ledger.KINDS.get(e.kind, e.kind)}: "
                        f"{e.amount:+.2f} EUR — {e.note}")
    return {"ok": True, "entry_id": e.id,
            "balance": partner_ledger.balance(db, partner_id)}


@router.delete("/entry/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db),
                 _=Depends(require_money)):
    from app.models.partner import PartnerEntry
    from app.services import audit
    e = db.get(PartnerEntry, entry_id)
    if not e:
        raise HTTPException(404, "Stavka nije pronađena.")
    pid, amt = e.partner_id, e.amount
    db.delete(e)
    db.commit()
    audit.record(db, "partner_entry_deleted",
                 actor=getattr(_, "username", "admin"), entity="partner",
                 entity_id=pid, detail=f"Obrisana stavka {amt:+.2f} EUR")
    return {"ok": True, "balance": partner_ledger.balance(db, pid)}
