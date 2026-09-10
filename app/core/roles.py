"""Roles and permissions.

Three roles, defined by what someone actually needs to do their job:

  owner    – everything, including money, settings and platform terms
  manager  – day-to-day plus money, but not platform-level settings
  skipper  – today's schedule and guest contacts; no money, no settings

Enforcement is on the server. Hiding a button in the UI is a courtesy, not a
control — a skipper who knows the URL must still be refused.
"""
from fastapi import Depends, HTTPException

from app.core.security import get_current_user

OWNER = "owner"
MANAGER = "manager"
SKIPPER = "skipper"
# legacy values already in the database
_LEGACY = {"admin": OWNER, "staff": MANAGER}

ROLE_LABELS = {
    OWNER: "Vlasnik — sve",
    MANAGER: "Voditelj — sve osim postavki platforme",
    SKIPPER: "Skiper — samo raspored i kontakti",
}

# what each role may do
PERMISSIONS = {
    OWNER: {"money", "bookings", "schedule", "settings", "platform", "staff"},
    MANAGER: {"money", "bookings", "schedule", "settings", "staff"},
    SKIPPER: {"schedule"},
}


def role_of(user) -> str:
    r = (getattr(user, "role", "") or "").lower()
    return _LEGACY.get(r, r) if r in _LEGACY or r in PERMISSIONS else MANAGER


def can(user, permission: str) -> bool:
    return permission in PERMISSIONS.get(role_of(user), set())


def require(permission: str):
    """Dependency factory: refuse the request unless the role allows it."""
    def _dep(user=Depends(get_current_user)):
        if not can(user, permission):
            raise HTTPException(
                403, f"Nemaš ovlasti za ovo ({ROLE_LABELS.get(role_of(user), '')}).")
        return user
    return _dep


# convenience dependencies
require_money = require("money")
require_settings = require("settings")
require_platform = require("platform")
require_bookings = require("bookings")


def strip_money(payload):
    """Remove money fields from data going to someone who may not see it."""
    money_keys = {"total_price", "amount_paid", "cash_collected", "settled",
                  "balance", "deposit_amount", "total", "paid", "to_collect",
                  "revenue", "money", "price"}
    if isinstance(payload, dict):
        return {k: (strip_money(v) if isinstance(v, (dict, list)) else v)
                for k, v in payload.items() if k not in money_keys}
    if isinstance(payload, list):
        return [strip_money(x) for x in payload]
    return payload
