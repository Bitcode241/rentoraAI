"""Code-driven deposit handling.

The AI is great at conversation but unreliable at the precise multi-step payment
flow. So instead of trusting the model to call send_deposit_link and finish, the
CODE takes over the money step: it scans the conversation for (a) a clear payment
intent and (b) the booking details (boat, date, passengers), and if both are
present it creates the booking + Stripe deposit link deterministically.

This never depends on the model "remembering" to act — if the guest asked to pay
and we can resolve the boat and date, the link is generated and returned.
"""
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ai.tools import _resolve_asset
from app.services import pricing
from app.services.availability import find_available

log = get_logger("auto-deposit")

# Clear signals the guest wants to pay / book now (multi-language).
PAY_INTENT = [
    "platiti depozit", "platit depozit", "platim depozit", "želim platiti",
    "zelim platiti", "želim rezervirati", "zelim rezervirati", "rezervirati i platiti",
    "pošalji link", "posalji link", "link za uplatu", "link za placanje",
    "pay deposit", "pay the deposit", "want to book", "like to book", "book it",
    "make a reservation", "want to pay", "send me the link", "payment link",
    "please proceed", "proceed", "go ahead", "confirm it", "let's book",
    "change it to", "change to", "switch to", "instead",
    # Croatian confirmations (guest saying yes to a specific boat we offered)
    "može rezerv", "moze rezerv", "rezerviraj", "rezervirajte", "može taj",
    "moze taj", "uzimamo", "uzimam", "hoćemo", "hocemo", "hoću taj", "hocu taj",
    "može može", "moze moze", "u redu", "potvrđujem", "potvrdujem", "idemo s tim",
    "može, javi", "moze javi", "zanima nas ovaj", "zanima nas taj", "želimo taj",
    "zelimo taj", "bukiraj", "bukirajte", "može to", "moze to",
    "anzahlung", "buchen", "bezahlen", "reservieren",
]

MONTHS = {
    "siječnja": 1, "veljače": 2, "ožujka": 3, "travnja": 4, "svibnja": 5,
    "lipnja": 6, "srpnja": 7, "kolovoza": 8, "rujna": 9, "listopada": 10,
    "studenog": 11, "prosinca": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def has_pay_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in PAY_INTENT)


def _parse_date(text: str):
    """Find a date in the text. Supports DD.MM.YYYY, DD/MM/YYYY, DD.MM. and
    '15 July 2026' style. Returns a date or None."""
    t = (text or "").lower()
    # 25.07.2026 or 25/7/2026 or 25-07-2026
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except ValueError:
            return None
    # 25.07. (no year) -> assume current or next year
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})\.?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        now = datetime.now(timezone.utc)
        y = now.year
        try:
            cand = datetime(y, mo, d, tzinfo=timezone.utc)
            if cand.date() < now.date():
                cand = datetime(y + 1, mo, d, tzinfo=timezone.utc)
            return cand
        except ValueError:
            return None
    # "15 July 2026" / "15. srpnja 2026"
    m = re.search(r"\b(\d{1,2})\.?\s+([a-zšžčćđ]+)\s+(\d{4})\b", t)
    if m and m.group(2) in MONTHS:
        d, mo, y = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
        try:
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _parse_passengers(text: str) -> int:
    t = (text or "").lower()
    m = re.search(r"\b(\d{1,2})\s*(osob|ljud|guest|person|people|pax|pers)", t)
    if m:
        return int(m.group(1))
    return 0


def _is_full_day(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("cijeli dan", "cijeldan", "full day", "whole day",
                                "8h", "8 h", "8 sati", "8sati", "ganztags"))


def _pick_package(asset, full_day: bool):
    """Choose a package id for the asset: prefer 8h if full day, else 4h, else first."""
    pkgs = pricing.list_packages(asset)
    if not pkgs:
        return None, None
    target_min = 480 if full_day else 240  # 8h or 4h
    def find(minutes):
        for p in pkgs:
            if p.get("duration_minutes") == minutes:
                return p
        return None
    chosen = find(target_min) or pkgs[0]
    return chosen.get("package_id"), chosen


def _match_asset(text, candidates):
    """Find the boat a guest named in free text, tolerant of Croatian case endings
    (barracuda -> barracudu/barracude) and the '(1)/(2)' suffix. Returns asset or None."""
    import re as _re
    t = (text or "").lower()
    msg_words = _re.findall(r"[a-zšđčćž0-9]+", t)
    best = None
    for a in candidates:
        name = a.name.lower()
        base = _re.sub(r"\s*\(\d+\)\s*$", "", name).strip()
        group = (getattr(a, "model_group", "") or "").lower().replace("-", " ")
        keys = [k for k in (name, base, group) if k]
        matched_len = 0
        for k in keys:
            if k in t:
                matched_len = max(matched_len, len(k))
                continue
            kw = [w for w in _re.findall(r"[a-zšđčćž0-9]+", k) if len(w) > 2]
            if kw and all(
                any(mw == w or mw.startswith(w[:max(4, len(w) - 2)]) or
                    w.startswith(mw[:max(4, len(mw) - 2)]) for mw in msg_words)
                for w in kw):
                matched_len = max(matched_len, len(k))
        if matched_len and (best is None or matched_len > best[0]):
            best = (matched_len, a)
    return best[1] if best else None


def try_inquiry_chain(db: Session, conversation_text: str, latest_message: str,
                      customer_id: int, guest_mailbox: str = "") -> dict | None:
    """On the FIRST inquiry (no payment intent needed): if the guest named a
    specific boat model + date, and the chain resolves to a PARTNER boat (yours is
    out of service or busy), ask the owner immediately and tell the guest we're
    checking. If the chain lands on YOUR boat, return None so the normal
    availability/price reply is sent. Returns a result dict or None.
    """
    from app.models.asset import Asset
    from app.services import chain_service
    candidates = db.query(Asset).filter(Asset.active.is_(True)).all()

    asset = _match_asset(latest_message, candidates) or \
        _match_asset(conversation_text, candidates)
    if not asset:
        return None
    start = _parse_date(conversation_text)
    if not start:
        return None
    full_day = _is_full_day(conversation_text)
    start = start.replace(hour=9, minute=0)
    end = start + timedelta(hours=8 if full_day else 4)
    passengers = _parse_passengers(conversation_text) or asset.capacity

    pick = chain_service.pick_for_window(db, asset, start, end)
    chosen = pick["asset"]
    if not chosen:
        return None  # nothing free in the group → let normal reply handle it
    # Only act here if the chosen boat is a PARTNER boat. If it's yours, the normal
    # availability+price+deposit reply is the right (and faster) path.
    if not getattr(chosen, "is_external", False):
        return None

    from app.ai import tools
    pkg_id, pkg = _pick_package(chosen, full_day)
    price = pkg.get("price", 0) if pkg else 0
    res = tools.request_external_availability(
        db, customer_id=customer_id, start=start.isoformat(),
        end=end.isoformat(), passengers=passengers, price=price,
        asset_id=chosen.id, guest_mailbox=guest_mailbox)
    log.info("inquiry_chain_external_asked", asset=chosen.name,
             status=res.get("status", res.get("error", "")))
    return {"external_request": res.get("request_id"), "asset": chosen.name,
            "owner_asked": True, "needs_human": res.get("needs_human", False)}


def try_auto_deposit(db: Session, conversation_text: str, latest_message: str,
                     customer_id: int, guest_mailbox: str = "") -> dict | None:
    """If the guest expressed payment intent and we can resolve boat+date+pax from
    the conversation, create the deposit link in code. Returns the tool-style result
    dict (with payment_url) or None if we can't safely proceed.

    conversation_text: full conversation (to find the boat/date mentioned earlier)
    latest_message: the newest guest message (to detect the pay intent)
    """
    if not has_pay_intent(latest_message) and not has_pay_intent(conversation_text):
        return None

    # Resolve the boat. Prefer the boat named in the LATEST message (the guest may
    # have just changed their choice); otherwise fall back to the conversation.
    from app.models.asset import Asset
    candidates = db.query(Asset).filter(Asset.active.is_(True)).all()

    def _match(text):
        return _match_asset(text, candidates)

    asset = _match(latest_message) or _match(conversation_text)
    if not asset:
        return None  # can't safely pick a boat — let the AI keep talking

    start = _parse_date(conversation_text)
    if not start:
        return None
    full_day = _is_full_day(conversation_text)
    start = start.replace(hour=9, minute=0)
    end = start + timedelta(hours=8 if full_day else 4)
    passengers = _parse_passengers(conversation_text) or asset.capacity

    # AVAILABILITY CHAIN: the guest named a model; pick the actual bookable boat by
    # priority (your boat first, then partners), skipping out-of-service/busy ones.
    from app.services import chain_service
    pick = chain_service.pick_for_window(db, asset, start, end)
    chosen = pick["asset"]
    if not chosen:
        return {"error": "not_available", "asset": asset.name}
    asset = chosen  # the real boat we'll book (yours or a partner's)

    # If the chosen boat is a PARTNER boat, run the owner-ask flow instead of an
    # instant deposit link — we must confirm with the owner first.
    if getattr(asset, "is_external", False):
        from app.ai import tools
        from app.services import pricing
        pkg_id, pkg = _pick_package(asset, full_day)
        price = pkg.get("price", 0) if pkg else 0
        res = tools.request_external_availability(
            db, customer_id=customer_id, start=start.isoformat(),
            end=end.isoformat(), passengers=passengers, price=price,
            asset_id=asset.id, guest_mailbox=guest_mailbox)
        log.info("chain_external_asked", asset=asset.name,
                 status=res.get("status", res.get("error", "")))
        return {"external_request": res.get("request_id"), "asset": asset.name,
                "owner_asked": True, "needs_human": res.get("needs_human", False),
                "message": res.get("message", "")}

    package_id, pkg = _pick_package(asset, full_day)

    # Create booking + deposit link via the same reliable tool.
    from app.ai import tools
    result = tools.send_deposit_link(
        db, customer_id=customer_id, start=start.isoformat(), end=end.isoformat(),
        asset_id=asset.id, package_id=package_id, guest_mailbox=guest_mailbox,
        passengers=passengers)
    log.info("auto_deposit_attempt", asset=asset.name,
             ok=bool(result.get("payment_url")), error=result.get("error", ""))
    return result
