"""Public booking API for the embeddable widget (no auth).

Serves only what a guest needs to book directly: business branding, bookable
assets with packages, add-ons, an availability check, and a deposit checkout.
Rate-limited to prevent abuse. Never exposes admin data.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.models.asset import Asset
from app.models.addon import AddOn
from app.models.customer import Customer
from app.services import pricing, availability, settings_service, booking_service

log = get_logger("public-booking")
router = APIRouter(prefix="/api/public", tags=["public-booking"])


@router.get("/config")
def public_config(asset_type: str = "jetski", db: Session = Depends(get_db)):
    """Branding + accent for the widget header."""
    return {
        "business_name": settings_service.brand_for_type(db, asset_type),
        "accent": settings_service.widget_accent(db),
        "deposit_percent": settings_service.default_deposit_percent(db),
        "currency": "EUR",
    }


@router.get("/assets")
def public_assets(asset_type: str = "jetski", db: Session = Depends(get_db)):
    """Bookable, in-service, NON-partner assets of a type, with their packages.
    (Partner boats aren't sold directly through the public widget.)"""
    rows = (db.query(Asset)
            .filter(Asset.asset_type == asset_type, Asset.active.is_(True),
                    Asset.out_of_service.is_(False),
                    Asset.is_external.is_(False))
            .order_by(Asset.booking_priority, Asset.id).all())
    out = []
    seen_groups = set()
    for a in rows:
        # collapse interchangeable models to one card
        grp = (a.model_group or "").strip().lower() or f"id-{a.id}"
        if grp in seen_groups:
            continue
        seen_groups.add(grp)
        out.append({
            "id": a.id, "name": a.name, "capacity": a.capacity,
            "description": a.description or "",
            "packages": [{"id": p["package_id"], "name": p["name"],
                          "duration_minutes": p["duration_minutes"],
                          "price": p["price"], "deposit": p["deposit_amount"]}
                         for p in pricing.list_packages(a)],
        })
    return out


@router.get("/addons")
def public_addons(asset_type: str = "jetski", db: Session = Depends(get_db)):
    rows = (db.query(AddOn)
            .filter(AddOn.active.is_(True))
            .filter((AddOn.applies_to == asset_type) | (AddOn.applies_to == ""))
            .order_by(AddOn.sort_order, AddOn.id).all())
    return [{"id": a.id, "name": a.name, "description": a.description,
             "price": a.price, "per_person": a.per_person} for a in rows]


@router.get("/availability")
def public_availability(asset_id: int, start: str, package_id: int,
                        db: Session = Depends(get_db)):
    """Is this asset free at `start` for the package's duration?"""
    asset = db.get(Asset, asset_id)
    if not asset:
        return {"available": False, "error": "no_asset"}
    try:
        st = datetime.fromisoformat(start)
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
    except Exception:
        return {"available": False, "error": "bad_date"}
    pkgs = {p["package_id"]: p for p in pricing.list_packages(asset)}
    pkg = pkgs.get(package_id)
    if not pkg:
        return {"available": False, "error": "no_package"}
    end = st + timedelta(minutes=pkg["duration_minutes"])
    ok = availability.is_asset_available(db, asset, st, end)
    return {"available": bool(ok)}


@router.post("/book")
def public_book(payload: dict, request: Request, db: Session = Depends(get_db)):
    """Create a booking from the widget and return a Stripe deposit checkout URL.
    Expects: asset_id, package_id, start (ISO), passengers, name, email, phone,
    addon_ids[]. Guest pays the deposit online; balance on site.
    """
    from app.services import payment_service
    asset = db.get(Asset, int(payload.get("asset_id", 0)))
    if not asset or asset.is_external or not asset.active or asset.out_of_service:
        return {"error": "asset_unavailable"}

    try:
        st = datetime.fromisoformat(payload["start"])
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
    except Exception:
        return {"error": "bad_date"}

    pkgs = {p["package_id"]: p for p in pricing.list_packages(asset)}
    pkg = pkgs.get(int(payload.get("package_id", 0)))
    if not pkg:
        return {"error": "no_package"}
    end = st + timedelta(minutes=pkg["duration_minutes"])
    if not availability.is_asset_available(db, asset, st, end):
        return {"error": "not_available"}

    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    phone = (payload.get("phone") or "").strip()
    if not email:
        return {"error": "email_required"}
    passengers = int(payload.get("passengers") or 1)

    # add-ons total
    addon_ids = payload.get("addon_ids") or []
    addons = (db.query(AddOn).filter(AddOn.id.in_([int(x) for x in addon_ids]),
                                     AddOn.active.is_(True)).all()
              if addon_ids else [])
    addons_total = sum(
        (a.price * passengers if a.per_person else a.price) for a in addons)
    addon_names = ", ".join(a.name for a in addons)

    # find or create the customer
    cust = db.query(Customer).filter(Customer.email.ilike(email)).first()
    if not cust:
        cust = Customer(full_name=name or email, email=email, phone=phone)
        db.add(cust); db.commit(); db.refresh(cust)
    else:
        if name and (not cust.full_name or cust.full_name == cust.email):
            cust.full_name = name
        if phone:
            cust.phone = phone
        db.commit()

    booking = booking_service.create_booking(
        db, asset_id=asset.id, customer_id=cust.id, package_id=pkg["package_id"],
        start=st, end=end, source="widget", passengers=passengers)
    # fold add-ons into the booking total (deposit stays on the package amount)
    if addons_total:
        booking.total_price = (booking.total_price or 0) + addons_total
        note = f"Add-ons: {addon_names} (+{addons_total:.2f} EUR)"
        booking.transfer_note = (booking.transfer_note + " | " + note).strip(" |") \
            if booking.transfer_note else note
        db.commit()

    pay = payment_service.create_deposit_checkout(booking, asset.name,
                                                  guest_email=email)
    if not pay.get("url"):
        return {"error": "payment_failed", "booking_id": booking.id}
    log.info("public_booking_created", booking_id=booking.id, asset=asset.name,
             addons=addon_names, addons_total=addons_total)
    return {"ok": True, "booking_id": booking.id, "checkout_url": pay["url"],
            "deposit": booking.deposit_amount, "total": booking.total_price}
