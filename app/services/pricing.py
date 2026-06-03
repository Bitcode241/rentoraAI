"""Pricing engine. Prices come ONLY from the database (Rule 5).

Two modes:
  1. Package-based (preferred): the customer picks a named package
     (e.g. boat "4h", jetski "Safari 90min"). Price is the package price.
  2. Legacy time-based: hourly / half-day / full-day from the asset record,
     used when an asset has no packages (keeps older data working).

Deposit:
  - If asset.deposit_percent > 0, deposit = percent of total (e.g. 30%).
  - Else deposit = asset.deposit (fixed amount).
"""
from datetime import datetime
from app.models.asset import Asset


HALF_DAY_HOURS = 4
FULL_DAY_HOURS = 8


def _deposit_for(asset: Asset, total: float) -> float:
    if getattr(asset, "deposit_percent", 0):
        return round(total * asset.deposit_percent / 100.0, 2)
    return round(asset.deposit, 2)


def quote_package(asset: Asset, package) -> dict:
    """Quote for a specific chosen package."""
    total = round(package.price, 2)
    return {
        "asset_id": asset.id,
        "package_id": package.id,
        "package_name": package.name,
        "duration_minutes": package.duration_minutes,
        "guided": package.guided,
        "total_price": total,
        "deposit_amount": _deposit_for(asset, total),
        "deposit_percent": getattr(asset, "deposit_percent", 0),
        "currency": "EUR",
    }


def quote(asset: Asset, start: datetime, end: datetime) -> dict:
    """Legacy time-based quote (hour / half-day / full-day)."""
    seconds = (end - start).total_seconds()
    hours = max(seconds / 3600.0, 0)

    days = int(hours // 24)
    remainder = hours - days * 24

    total = days * asset.price_full_day
    if remainder <= 0:
        block = 0.0
    elif remainder <= HALF_DAY_HOURS:
        if asset.price_half_day and asset.price_hour:
            block = min(asset.price_half_day, remainder * asset.price_hour)
        elif asset.price_half_day:
            block = asset.price_half_day
        else:
            block = remainder * asset.price_hour
    elif remainder <= FULL_DAY_HOURS:
        block = asset.price_full_day or remainder * asset.price_hour
    else:
        block = asset.price_full_day

    total += block
    total = round(total, 2)
    return {
        "asset_id": asset.id,
        "hours": round(hours, 2),
        "total_price": total,
        "deposit_amount": _deposit_for(asset, total),
        "currency": "EUR",
        "breakdown": {
            "full_days": days,
            "remainder_hours": round(remainder, 2),
            "price_hour": asset.price_hour,
            "price_half_day": asset.price_half_day,
            "price_full_day": asset.price_full_day,
        },
    }


def list_packages(asset: Asset) -> list:
    """Return the asset's active packages as plain dicts (for AI tools / API)."""
    out = []
    for p in sorted(getattr(asset, "packages", []), key=lambda x: x.duration_minutes):
        if p.active:
            out.append({
                "package_id": p.id, "name": p.name,
                "duration_minutes": p.duration_minutes, "price": p.price,
                "guided": p.guided, "deposit_amount": _deposit_for(asset, p.price),
            })
    return out
