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

    # Resolve the boat by scanning the conversation for a known asset name.
    from app.models.asset import Asset
    text_l = conversation_text.lower()
    asset = None
    # match the longest asset name that appears in the conversation
    candidates = db.query(Asset).filter(Asset.active.is_(True)).all()
    best = None
    for a in candidates:
        if a.name.lower() in text_l:
            if best is None or len(a.name) > len(best.name):
                best = a
    asset = best
    if not asset:
        return None  # can't safely pick a boat — let the AI keep talking

    if getattr(asset, "is_external", False):
        return {"error": "external_asset"}  # external goes through owner flow

    start = _parse_date(conversation_text)
    if not start:
        return None
    full_day = _is_full_day(conversation_text)
    start = start.replace(hour=9, minute=0)
    end = start + timedelta(hours=8 if full_day else 4)

    passengers = _parse_passengers(conversation_text) or asset.capacity

    # Verify the boat is actually free for that slot.
    avail = find_available(db, asset.asset_type, passengers, start, end)
    if not any(e["asset"].id == asset.id for e in avail):
        return {"error": "not_available", "asset": asset.name}

    package_id, pkg = _pick_package(asset, full_day)

    # Create booking + deposit link via the same reliable tool.
    from app.ai import tools
    result = tools.send_deposit_link(
        db, customer_id=customer_id, start=start.isoformat(), end=end.isoformat(),
        asset_id=asset.id, package_id=package_id, guest_mailbox=guest_mailbox)
    log.info("auto_deposit_attempt", asset=asset.name,
             ok=bool(result.get("payment_url")), error=result.get("error", ""))
    return result
