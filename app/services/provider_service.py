"""Provider-aware charge calculation for the booking widget.

Two kinds of tours:
  own     -> your boat. Charge a deposit (or full) through your gateway.
  partner -> a partner runs it. Charge ONLY your commission online; the rest is
             paid directly to the partner on the boat and must NEVER pass through
             your payment system.

This module is the single source of truth for "how much do we charge online",
and it HARD-VALIDATES that a partner charge can never exceed the commission.
"""
from app.core.logging import get_logger

log = get_logger("provider-charge")


class PartnerChargeError(Exception):
    """Raised when a partner charge would exceed the allowed commission, or when
    mandatory partner data is missing. Blocks the charge."""


def is_partner(asset) -> bool:
    return (getattr(asset, "provider_type", "own") or "own").lower() == "partner"


def partner_amounts(asset) -> dict:
    """Return the money split for a partner tour:
      {total, commission, pay_on_site}. Never invents numbers."""
    total = float(getattr(asset, "partner_total_price", 0) or 0)
    commission = float(getattr(asset, "my_commission", 0) or 0)
    pay_on_site = round(total - commission, 2)
    return {"total": total, "commission": commission, "pay_on_site": pay_on_site}


def validate_partner_asset(asset) -> list:
    """Return a list of problems that BLOCK a partner booking/voucher. Empty list
    means OK. Mandatory: provider_name, provider_oib, sane money split."""
    problems = []
    if not (getattr(asset, "provider_name", "") or "").strip():
        problems.append("provider_name_missing")
    if not (getattr(asset, "provider_oib", "") or "").strip():
        problems.append("provider_oib_missing")
    amt = partner_amounts(asset)
    if amt["total"] <= 0:
        problems.append("total_price_missing")
    if amt["commission"] <= 0:
        problems.append("commission_missing")
    if amt["commission"] > amt["total"]:
        problems.append("commission_exceeds_total")
    return problems


def online_charge(asset, deposit_amount: float = 0.0) -> dict:
    """How much to charge online for this asset.

    own     -> {mode:"own", charge: deposit_amount, ...}
    partner -> {mode:"partner", charge: commission, pay_on_site:..., total:...}

    For partner, HARD-VALIDATES that charge == commission and never more.
    Raises PartnerChargeError if partner data is invalid.
    """
    if is_partner(asset):
        problems = validate_partner_asset(asset)
        if problems:
            raise PartnerChargeError(",".join(problems))
        amt = partner_amounts(asset)
        charge = amt["commission"]
        # absolute safety: a partner charge can never exceed the commission
        if charge > amt["commission"]:
            raise PartnerChargeError("charge_exceeds_commission")
        return {"mode": "partner", "charge": round(charge, 2),
                "pay_on_site": amt["pay_on_site"], "total": amt["total"],
                "commission": amt["commission"]}
    return {"mode": "own", "charge": round(deposit_amount, 2)}


def assert_partner_charge_safe(asset, charge: float):
    """Final gate right before hitting the payment gateway. Raises if a partner
    charge exceeds the commission. Call this with the exact amount being charged."""
    if not is_partner(asset):
        return
    amt = partner_amounts(asset)
    # tiny epsilon for float rounding
    if charge > amt["commission"] + 0.01:
        log.warning("partner_overcharge_blocked", charge=charge,
                    commission=amt["commission"], asset=getattr(asset, "name", "?"))
        raise PartnerChargeError("charge_exceeds_commission")
