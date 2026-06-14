"""Code-driven availability answers.

The AI is unreliable at producing exact facts (which boat is free, what it costs).
So the CODE computes the facts — available boats for the requested date/size, with
real prices from the DB — and returns them as a structured block. The AI's only job
is to wrap these facts in a warm, professional message. The AI never invents a boat,
a price, or availability.

Starts with BOATS. Jetski and transfer will reuse the same pattern.
"""
import re
from datetime import timedelta
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.services import pricing
from app.services.availability import find_available
from app.services.auto_deposit_service import _parse_date, _parse_passengers, _is_full_day

log = get_logger("inquiry")

# Words that signal the guest is asking about BOATS specifically.
BOAT_WORDS = ["boat", "brod", "speedboat", "speed boat", "yacht", "plovilo",
              "barca", "boot", "tour", "excursion", "izlet", "krstaren",
              "barracuda", "atlantic", "gaia", "marine"]
JETSKI_WORDS = ["jet ski", "jetski", "jet-ski", "skuter", "jet"]


def _db_boat_names(db) -> list:
    """Actual boat names + model groups from the DB, lowercased, so a guest who
    types a specific boat name (e.g. 'Barracuda 545') is recognised as wanting a boat."""
    from app.models.asset import Asset
    import re as _re
    out = set()
    for a in db.query(Asset).filter(Asset.asset_type == "boat",
                                     Asset.active.is_(True)).all():
        name = (a.name or "").lower()
        base = _re.sub(r"\s*\(\d+\)\s*$", "", name).strip()
        for k in (name, base):
            if k:
                out.add(k)
        grp = (getattr(a, "model_group", "") or "").lower().replace("-", " ")
        if grp:
            out.add(grp)
    return list(out)


def wants_boats(text: str, db=None) -> bool:
    t = (text or "").lower()
    if any(w in t for w in BOAT_WORDS) and not _is_jetski_only(t):
        return True
    # also match actual boat names from the DB (e.g. "Barracuda 545")
    if db is not None:
        if any(name in t for name in _db_boat_names(db)) and not _is_jetski_only(t):
            return True
    return False


def _is_jetski_only(t: str) -> bool:
    has_jet = any(w in t for w in JETSKI_WORDS)
    has_boat = any(w in t for w in ["boat", "brod", "speedboat", "yacht", "plovilo"])
    return has_jet and not has_boat


def build_boat_availability(db: Session, text: str) -> dict | None:
    """Compute available boats + prices for the requested date and party size.
    Returns a facts dict for the AI to phrase, or None if we can't parse enough.
    """
    start = _parse_date(text)
    if not start:
        return None
    passengers = _parse_passengers(text)
    if not passengers:
        # default to a sensible small group so we can still show options
        passengers = 2

    full_day = _is_full_day(text)
    # default daypart: 4h unless full day stated; start 09:00 (or 13:00 if afternoon)
    hour = 13 if ("afternoon" in text.lower() or "popodne" in text.lower()) else 9
    start = start.replace(hour=hour, minute=0, second=0, microsecond=0)
    dur_h = 8 if full_day else 4
    end = start + timedelta(hours=dur_h)

    results = find_available(db, "boat", passengers, start, end)
    # Collapse same-model boats to ONE option (the highest-priority available one),
    # so the guest sees "Barracuda 545" once, not your + partner's listed separately.
    from app.services.chain_service import _group_of
    best_by_group = {}
    for entry in results:
        a = entry["asset"]
        g = _group_of(a)
        prio = getattr(a, "booking_priority", 100) or 100
        if g not in best_by_group or prio < best_by_group[g][0]:
            best_by_group[g] = (prio, a)

    options = []
    for _prio, a in sorted(best_by_group.values(), key=lambda x: x[0]):
        pkgs = pricing.list_packages(a)
        # show the package matching the requested duration if present, else all
        target_min = 480 if full_day else 240
        match = [p for p in pkgs if p.get("duration_minutes") == target_min]
        show = match or pkgs
        for p in show:
            options.append({
                "boat": a.name,
                "capacity": a.capacity,
                "package": p.get("name", ""),
                "duration_minutes": p.get("duration_minutes"),
                "price": p.get("price"),
                "deposit": p.get("deposit_amount"),
                "is_external": bool(getattr(a, "is_external", False)),
                "page_url": getattr(a, "page_url", "") or "",
            })

    return {
        "type": "boat_availability",
        "date": start.strftime("%d.%m.%Y"),
        "time": f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}",
        "passengers": passengers,
        "full_day": full_day,
        "options": options,
        "any_available": len(options) > 0,
    }


def facts_to_prompt(facts: dict) -> str:
    """Turn the computed facts into a compact instruction block the AI must use
    verbatim (it may rephrase wording/tone, but NOT change boats, prices, dates)."""
    if not facts:
        return ""
    if facts["type"] == "boat_availability":
        if not facts["any_available"]:
            return (f"FACTS (use exactly, do not invent): For {facts['passengers']} "
                    f"people on {facts['date']} ({facts['time']}), NO boats are "
                    f"available. Apologise briefly and offer another date.")
        lines = [f"FACTS — available boats for {facts['passengers']} people on "
                 f"{facts['date']} ({facts['time']}). Use ONLY these; do not invent "
                 f"boats or prices:"]
        has_external = False
        for o in facts["options"]:
            tag = ""
            if o.get("is_external"):
                tag = " [ON REQUEST — confirm with partner before payment]"
                has_external = True
            link = f" — details & photos: {o['page_url']}" if o.get("page_url") else ""
            lines.append(f"- {o['boat']} (up to {o['capacity']} people) — "
                         f"{o['package']}: {o['price']:.0f} EUR "
                         f"(deposit {o['deposit']:.0f} EUR){tag}{link}")
        lines.append("Present these to the guest in their language, warmly and "
                     "professionally. When a boat has a details/photos link, include "
                     "that link next to the boat so they can see photos and what's "
                     "included. Invite them to confirm a boat to proceed.")
        if has_external:
            lines.append("For any boat marked [ON REQUEST], do NOT present it as "
                         "instantly bookable — mention it may need a quick "
                         "confirmation. If the guest picks an ON REQUEST boat, call "
                         "request_external_availability (do not send a deposit link "
                         "yet). For normal boats, proceed straight to the deposit link.")
        lines.append("If the guest later asks to switch to a different listed boat, "
                     "simply proceed with that one — do not stall.")
        return "\n".join(lines)
    return ""
