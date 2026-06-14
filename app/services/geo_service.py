"""Geocoding + distance for transfer pricing.

Turns a guest's free-text location ("Babin kuk", "Hotel Kompas Lapad") into
coordinates via OpenStreetMap Nominatim, measures the straight-line distance to a
base point (Haversine), and finds the matching radius price tier. If geocoding
fails or the distance is beyond all tiers, we DON'T guess — the caller asks the
owner to set a price.
"""
import math
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.transfer import TransferRadius

log = get_logger("geo")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Bias geocoding around Dubrovnik so "Babin kuk" resolves locally.
_DBV_VIEWBOX = "17.9,42.55,18.35,42.75"  # lon/lat box around Dubrovnik


def geocode(location: str) -> tuple | None:
    """Return (lat, lng) for a location string, or None if it can't be resolved.
    Network-tolerant: any failure returns None so the caller falls back to asking
    the owner instead of crashing."""
    q = (location or "").strip()
    if not q:
        return None
    try:
        import httpx
        params = {"q": q + ", Dubrovnik, Croatia", "format": "json", "limit": 1,
                  "viewbox": _DBV_VIEWBOX, "bounded": 0}
        headers = {"User-Agent": "RentoraAI/1.0 (booking assistant)"}
        with httpx.Client(timeout=8.0) as client:
            r = client.get(NOMINATIM_URL, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
        if not data:
            log.info("geocode_empty", query=q)
            return None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:  # network blocked, timeout, parse error...
        log.warning("geocode_failed", query=q, error=str(e))
        return None


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Straight-line distance in km between two GPS points."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def price_for_location(db: Session, location: str, passengers: int,
                       service: str = "transfer", round_trip: bool = False) -> dict:
    """Resolve a transfer price for a free-text guest location.

    Returns one of:
      {"status": "ok", "price": float, "distance_km": float, "tier": str, ...}
      {"status": "needs_owner_price", "reason": "...", "distance_km": float|None}
    Never invents a price.
    """
    tiers = (db.query(TransferRadius)
             .filter(TransferRadius.active.is_(True),
                     TransferRadius.service == service)
             .order_by(TransferRadius.max_km).all())
    if not tiers:
        return {"status": "needs_owner_price", "reason": "no_tiers_configured",
                "distance_km": None, "location": location}

    coords = geocode(location)
    if not coords:
        return {"status": "needs_owner_price", "reason": "geocode_failed",
                "distance_km": None, "location": location}

    base = tiers[0]
    dist = haversine_km(base.base_lat, base.base_lng, coords[0], coords[1])

    # vehicle plan (reuse transfer logic): <=3 car, 4-8 van, 9+ van+car
    from app.services.transfer_service import plan_vehicles
    plan = plan_vehicles(passengers)

    for t in tiers:  # sorted ascending by max_km
        if dist <= t.max_km:
            one_way = plan["vans"] * t.van_price + plan["cars"] * t.car_price
            total = one_way * (2 if round_trip else 1)
            return {"status": "ok", "price": round(total, 2),
                    "price_one_way": round(one_way, 2),
                    "distance_km": round(dist, 1), "tier": t.label,
                    "direction": "round_trip" if round_trip else "one_way",
                    "vehicles": plan, "location": location,
                    "base": base.base_label}

    # beyond the largest tier -> ask the owner
    return {"status": "needs_owner_price", "reason": "beyond_max_radius",
            "distance_km": round(dist, 1), "location": location}
