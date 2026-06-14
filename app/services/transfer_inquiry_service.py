"""Transfer inquiry flow (code-driven, like the boat chain).

When a guest asks about a transfer, CODE figures out the price:
  1. parse the guest's pickup/drop-off location + passenger count + one-way/return
  2. price it via GPS radius tiers (geo_service); fall back to named zones
  3. if nothing matches -> signal that the OWNER must set a price (never invent)
The AI only phrases the result.
"""
import re
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.services import geo_service, transfer_service

log = get_logger("transfer-inquiry")

# phrases that signal a transfer request
TRANSFER_WORDS = ["transfer", "prijevoz", "pickup", "pick up", "pick-up",
                  "drop off", "drop-off", "dropoff", "shuttle", "ride",
                  "aerodrom", "zračna luka", "zracna luka", "airport",
                  "flughafen", "abholung"]
ROUND_TRIP_WORDS = ["povratn", "round trip", "round-trip", "return", "oba smjera",
                    "tamo i nazad", "hin und zurück", "both ways", "i natrag"]


def wants_transfer(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in TRANSFER_WORDS)


def _is_round_trip(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ROUND_TRIP_WORDS)


def _passengers(text: str) -> int:
    t = (text or "").lower()
    m = re.search(r"(\d+)\s*(osob|ljud|pax|person|people|putnik|guest)", t)
    if m:
        return int(m.group(1))
    return 0


def _extract_location(text: str) -> str:
    """Pull the pickup/destination phrase from the message. We look for text after
    'from/iz/od/do/to/sa' up to a delimiter. Falls back to the airport keyword."""
    t = (text or "")
    # common patterns: "transfer s aerodroma do hotela X", "pickup from Babin kuk"
    patterns = [
        r"(?:from|iz|od|sa|s)\s+([A-Za-zČĆŽŠĐčćžšđ0-9 ,.-]{3,40})",
        r"(?:do|to|za|nach|bis)\s+([A-Za-zČĆŽŠĐčćžšđ0-9 ,.-]{3,40})",
    ]
    for p in patterns:
        m = re.search(p, t, re.IGNORECASE)
        if m:
            loc = m.group(1).strip(" ,.")
            # trim trailing noise words and any passenger phrase
            loc = re.split(r"\b(za|na|u|do|i|and|with|für)\b", loc)[0].strip(" ,.")
            loc = re.sub(r"\b\d+\s*(osob\w*|ljud\w*|pax|persons?|people|putnik\w*|guests?)\b",
                         "", loc, flags=re.IGNORECASE).strip(" ,.")
            loc = re.sub(r"\s{2,}", " ", loc)
            if len(loc) >= 3:
                return loc
    low = t.lower()
    if "aerodrom" in low or "airport" in low or "zračna" in low or "zracna" in low:
        return "Zračna luka Dubrovnik"
    return ""


def quote_for_message(db: Session, text: str) -> dict:
    """Best-effort transfer quote from a free-text message.

    Returns:
      {"status":"ok", "price":..., "location":..., "distance_km":..., ...}
      {"status":"need_location"}                      # couldn't find a location
      {"status":"needs_owner_price", "location":..., "reason":...}
    """
    passengers = _passengers(text) or 1
    round_trip = _is_round_trip(text)
    location = _extract_location(text)
    if not location:
        return {"status": "need_location"}

    # 1) GPS radius pricing
    res = geo_service.price_for_location(db, location, passengers,
                                         service="transfer", round_trip=round_trip)
    if res.get("status") == "ok":
        res["passengers"] = passengers
        return res

    # 2) fall back to a named zone (e.g. "Aerodrom") if one matches the text
    zone = transfer_service.find_zone(db, location)
    if zone:
        q = transfer_service.quote_transfer(zone, passengers, round_trip)
        return {"status": "ok", "price": q["total"],
                "price_one_way": q.get("price_one_way"),
                "location": zone.name, "distance_km": None,
                "tier": zone.name, "passengers": passengers,
                "direction": q.get("direction")}

    # 3) unknown -> owner must price it
    return {"status": "needs_owner_price", "location": location,
            "reason": res.get("reason", "unknown"),
            "distance_km": res.get("distance_km"),
            "passengers": passengers, "round_trip": round_trip}
