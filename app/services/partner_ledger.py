"""Running account per partner.

How the owner actually works: he sends guests to a partner, the guest pays the
partner directly, and the owner's margin stays with the partner as credit against
older debts. Nothing is settled per booking — a balance builds up and is offset
("prebijanje") now and then.

Sign convention, always from the owner's point of view:
    amount > 0  →  the partner owes me
    amount < 0  →  I owe the partner

So the balance is a plain sum, and offsetting needs no special case.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.partner import Partner, PartnerEntry

log = get_logger(__name__)

KINDS = {
    "referral": "Poslao gosta (moja zarada)",
    "owed": "Dugujem partneru",
    "payment_in": "Primio uplatu od partnera",
    "payment_out": "Platio partneru",
    "adjust": "Ispravak / prijenos starog duga",
}


def add_referral(db: Session, *, partner_id: int, tour_name: str, guests: int,
                 guest_paid: float, partner_gets: float, note: str = "",
                 booking_id: int = None, created_by: str = "",
                 entry_date: datetime = None) -> PartnerEntry:
    """Record a guest sent to a partner.

    guest_paid    – what the guest handed over in total
    partner_gets  – the partner's share of that
    The difference is my earning, which the partner now owes me.
    """
    if guest_paid < 0 or partner_gets < 0:
        raise ValueError("Iznosi ne mogu biti negativni.")
    if partner_gets > guest_paid:
        raise ValueError("Partnerov dio ne može biti veći od onog što je gost platio.")
    my_earning = round(guest_paid - partner_gets, 2)
    e = PartnerEntry(
        partner_id=partner_id, kind="referral",
        amount=my_earning,                 # partner holds my share → owes me
        tour_name=(tour_name or "")[:160], guests=max(0, int(guests or 0)),
        guest_paid=round(guest_paid, 2), partner_gets=round(partner_gets, 2),
        booking_id=booking_id, note=(note or "")[:255],
        created_by=created_by or "",
        entry_date=entry_date or datetime.now(timezone.utc))
    db.add(e)
    db.commit()
    db.refresh(e)
    log.info("partner_referral_added", partner_id=partner_id,
             earning=my_earning, guests=guests)
    return e


def add_entry(db: Session, *, partner_id: int, kind: str, amount: float,
              note: str = "", created_by: str = "",
              entry_date: datetime = None) -> PartnerEntry:
    """Add a manual line: an old debt, a payment made or received, a correction.

    `amount` is given as a positive number; the sign is derived from the kind so
    the operator never has to think about plus and minus.
    """
    if kind not in KINDS:
        raise ValueError("Nepoznata vrsta stavke.")
    amt = abs(float(amount or 0))
    if amt == 0:
        raise ValueError("Iznos ne može biti 0.")
    # Sign is derived from the kind so the operator always types a positive
    # number and never has to reason about plus/minus:
    #   owed        I owe them (their guest, old debt)   → balance down
    #   payment_in  they paid me                         → their debt down
    #   payment_out I paid them                          → my debt down
    #   adjust      manual correction in my favour
    signs = {"owed": -1, "payment_in": -1, "payment_out": +1, "adjust": +1,
             "referral": +1}
    signed = amt * signs[kind]
    e = PartnerEntry(partner_id=partner_id, kind=kind, amount=round(signed, 2),
                     note=(note or "")[:255], created_by=created_by or "",
                     entry_date=entry_date or datetime.now(timezone.utc))
    db.add(e)
    db.commit()
    db.refresh(e)
    log.info("partner_entry_added", partner_id=partner_id, kind=kind,
             amount=signed)
    return e


def balance(db: Session, partner_id: int) -> float:
    rows = (db.query(PartnerEntry)
            .filter(PartnerEntry.partner_id == partner_id).all())
    return round(sum(r.amount or 0 for r in rows), 2)


def statement(db: Session, partner_id: int, limit: int = 200) -> dict:
    """Entries newest first, with a running balance so any line can be traced."""
    p = db.get(Partner, partner_id)
    if not p:
        return {}
    rows = (db.query(PartnerEntry)
            .filter(PartnerEntry.partner_id == partner_id)
            .order_by(PartnerEntry.entry_date, PartnerEntry.id).all())
    running = 0.0
    items = []
    for r in rows:
        running = round(running + (r.amount or 0), 2)
        items.append({
            "id": r.id, "date": r.entry_date, "kind": r.kind,
            "kind_label": KINDS.get(r.kind, r.kind),
            "amount": round(r.amount or 0, 2),
            "tour_name": r.tour_name or "", "guests": r.guests or 0,
            "guest_paid": round(r.guest_paid or 0, 2),
            "partner_gets": round(r.partner_gets or 0, 2),
            "note": r.note or "", "running": running,
        })
    items.reverse()
    sent = sum(1 for r in rows if r.kind == "referral")
    guests = sum((r.guests or 0) for r in rows if r.kind == "referral")
    earned = round(sum((r.guest_paid or 0) - (r.partner_gets or 0)
                       for r in rows if r.kind == "referral"), 2)
    passed = round(sum(r.partner_gets or 0 for r in rows
                       if r.kind == "referral"), 2)
    return {
        "partner": {"id": p.id, "name": p.name, "phone": p.phone or "",
                    "contact": p.contact or "", "note": p.note or ""},
        "balance": round(running, 2),
        "referrals": sent, "guests_sent": guests,
        "earned_total": earned, "passed_to_partner": passed,
        "entries": items[:limit],
    }


def overview(db: Session) -> dict:
    """All partners with their current balance."""
    partners = db.query(Partner).filter(Partner.active == True).all()  # noqa: E712
    out = []
    owed_to_me = owed_by_me = 0.0
    for p in partners:
        bal = balance(db, p.id)
        if bal > 0:
            owed_to_me += bal
        else:
            owed_by_me += -bal
        rows = (db.query(PartnerEntry)
                .filter(PartnerEntry.partner_id == p.id,
                        PartnerEntry.kind == "referral").all())
        out.append({
            "id": p.id, "name": p.name, "phone": p.phone or "",
            "balance": bal,
            "guests_sent": sum((r.guests or 0) for r in rows),
            "referrals": len(rows),
        })
    out.sort(key=lambda x: abs(x["balance"]), reverse=True)
    return {"partners": out,
            "owed_to_me": round(owed_to_me, 2),
            "owed_by_me": round(owed_by_me, 2),
            "net": round(owed_to_me - owed_by_me, 2)}
