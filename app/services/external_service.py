"""External (partner) boat availability flow.

When a guest asks for an external asset, we DON'T confirm immediately. Instead:
  1. create an ExternalRequest (status=pending) with a short token
  2. email the owner asking DA/NE
  3. tell the guest we're checking

When the owner replies (matched by token or their email + open request):
  - "DA"  -> create the booking, notify guest + business owner
  - "NE"  -> mark declined, notify guest

A scheduled sweep escalates requests with no reply after a timeout.
"""
import secrets
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.external_request import ExternalRequest
from app.models.asset import Asset
from app.models.customer import Customer
from app.core.logging import get_logger
from app.core.config import settings

log = get_logger(__name__)

TIMEOUT_MINUTES = 180  # 3h before we escalate to the business owner


def _token() -> str:
    return secrets.token_hex(3).upper()  # e.g. "A1B2C3"


def commission_split(price: float, commission_percent: float) -> dict:
    your_cut = round(price * commission_percent / 100.0, 2)
    owner_gets = round(price - your_cut, 2)
    return {"guest_pays": round(price, 2), "your_commission": your_cut,
            "owner_gets": owner_gets, "commission_percent": commission_percent}


def settlement(price: float, commission_percent: float, payment_direction: str) -> dict:
    """Who owes whom, clearly, based on who collects the guest's money.
    Returns a dict with a human-readable summary and the amount.
    """
    s = commission_split(price, commission_percent)
    if payment_direction == "partner":
        # partner collected the full price; they owe you your commission
        return {
            "collected_by": "partner",
            "direction": "partner_owes_you",
            "amount": s["your_commission"],
            "summary": f"Partner naplaćuje gosta ({s['guest_pays']:.2f} EUR). "
                       f"Partner VAMA duguje proviziju: {s['your_commission']:.2f} EUR.",
            **s,
        }
    # default: you collected; you owe the owner their share
    return {
        "collected_by": "you",
        "direction": "you_owe_partner",
        "amount": s["owner_gets"],
        "summary": f"Vi naplaćujete gosta ({s['guest_pays']:.2f} EUR). "
                   f"VI partneru dugujete: {s['owner_gets']:.2f} EUR "
                   f"(vaša provizija {s['your_commission']:.2f} EUR).",
        **s,
    }


def create_request(db: Session, asset: Asset, customer: Customer, *,
                   start, end, passengers: int, price: float,
                   guest_mailbox: str = "") -> ExternalRequest:
    req = ExternalRequest(
        asset_id=asset.id, customer_id=customer.id,
        start_datetime=start, end_datetime=end, passengers=passengers,
        guest_email=customer.email or "", quoted_price=price,
        guest_mailbox=guest_mailbox,
        owner_email=asset.owner_email, owner_phone=asset.owner_phone,
        status="pending", token=_token(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    log.info("external_request_created", req_id=req.id, asset=asset.name,
             token=req.token)
    return req


def owner_email_body(req: ExternalRequest, asset: Asset) -> str:
    when = req.start_datetime.strftime("%d.%m.%Y %H:%M")
    split = commission_split(req.quoted_price, asset.commission_percent)
    return (
        f"Pozdrav{(' ' + asset.owner_name) if asset.owner_name else ''},\n\n"
        f"Imam upit gosta za tvoj brod \"{asset.name}\".\n\n"
        f"Termin: {when}\n"
        f"Broj osoba: {req.passengers}\n"
        f"Cijena gostu: {split['guest_pays']} EUR "
        f"(tebi ide {split['owner_gets']} EUR)\n\n"
        f"Je li brod slobodan? Odgovori na ovaj mail samo s DA ili NE.\n"
        f"(referenca: {req.token})\n\n"
        f"Hvala!"
    )


def parse_owner_reply(text: str) -> str | None:
    """Return 'yes', 'no', or None from an owner's reply body."""
    t = (text or "").strip().lower()
    # look at the first ~40 chars so quoted history below doesn't confuse us
    head = t[:40]
    yes = ["da", "yes", "slobodno", "slobodan", "moze", "može", "ok", "potvrdjujem", "potvrđujem"]
    no = ["ne", "no", "nije", "zauzeto", "zauzet", "ne moze", "ne može"]
    for w in no:
        if head.startswith(w) or f" {w} " in f" {head} ":
            return "no"
    for w in yes:
        if head.startswith(w) or f" {w} " in f" {head} ":
            return "yes"
    return None


def find_open_request_for_owner(db: Session, owner_email: str,
                                token: str = "") -> ExternalRequest | None:
    q = db.query(ExternalRequest).filter(ExternalRequest.status == "pending")
    if token:
        r = q.filter(ExternalRequest.token == token.upper()).first()
        if r:
            return r
    if owner_email:
        return q.filter(ExternalRequest.owner_email.ilike(owner_email))\
                .order_by(ExternalRequest.created_at.desc()).first()
    return None


def list_pending(db: Session) -> list:
    rows = db.query(ExternalRequest).filter(
        ExternalRequest.status == "pending").order_by(
        ExternalRequest.created_at.desc()).all()
    return rows


def overdue(db: Session, minutes: int = TIMEOUT_MINUTES) -> list:
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    return db.query(ExternalRequest).filter(
        ExternalRequest.status == "pending",
        ExternalRequest.created_at < cutoff).all()
