"""Public booking API for the embeddable widget (no auth).

Serves only what a guest needs to book directly: business branding, bookable
assets with packages, add-ons, an availability check, and a deposit checkout.
Rate-limited to prevent abuse. Never exposes admin data.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
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
        "accent": settings_service.widget_accent(db, asset_type),
        "deposit_percent": settings_service.default_deposit_percent(db),
        "extra_person_fee": settings_service.jetski_extra_person_fee(db),
        "lead_time_hours": settings_service.lead_time_hours(db, asset_type),
        "open_hour": int(settings_service.get(db, "open_hour", "8") or 8),
        "close_hour": int(settings_service.get(db, "close_hour", "20") or 20),
        # When ON, the widget shows "meeting point arranged after booking" instead
        # of any public location — used for spots that can't be advertised online.
        "meeting_arranged": (settings_service.get(db, "meeting_arranged", "0") or "0") == "1",
        "meeting_note": settings_service.get(db, "meeting_note", "") or "",
        "currency": "EUR",
        "currency": "EUR",
    }


@router.get("/assets")
def public_assets(asset_type: str = "jetski", db: Session = Depends(get_db)):
    """One card PER MODEL GROUP (not per physical unit), with how many units exist.
    Guests pick a model + quantity; the system assigns free units behind the scenes.
    Partner boats aren't sold directly through the public widget."""
    rows = (db.query(Asset)
            .filter(Asset.asset_type == asset_type, Asset.active.is_(True),
                    Asset.out_of_service.is_(False),
                    Asset.is_external.is_(False))
            .order_by(Asset.booking_priority, Asset.id).all())
    groups = {}
    for a in rows:
        grp = (a.model_group or "").strip().lower() or f"id-{a.id}"
        if grp not in groups:
            # display name without the "(1)" suffix
            import re as _re
            disp = _re.sub(r"\s*\(\d+\)\s*$", "", a.name).strip()
            groups[grp] = {"group": grp, "id": a.id, "name": disp,
                           "capacity": a.capacity,
                           "description": a.description if a.description != a.name else "",
                           "fleet_size": 0,
                           "packages": [{"id": p["package_id"], "name": p["name"],
                                         "duration_minutes": p["duration_minutes"],
                                         "price": p["price"], "deposit": p["deposit_amount"]}
                                        for p in pricing.list_packages(a)]}
        groups[grp]["fleet_size"] += 1
    return list(groups.values())


@router.get("/addons")
def public_addons(asset_type: str = "jetski", db: Session = Depends(get_db)):
    rows = (db.query(AddOn)
            .filter(AddOn.active.is_(True))
            .filter((AddOn.applies_to == asset_type) | (AddOn.applies_to == ""))
            .order_by(AddOn.sort_order, AddOn.id).all())
    return [{"id": a.id, "name": a.name, "description": a.description,
             "price": a.price, "per_person": a.per_person} for a in rows]


def _free_units_in_group(db, anchor_asset, start, end):
    """All free, in-service, non-partner units in the same model group as
    anchor_asset for [start,end), ordered by booking priority."""
    import re as _re
    grp = (anchor_asset.model_group or "").strip().lower() or f"id-{anchor_asset.id}"
    units = (db.query(Asset)
             .filter(Asset.asset_type == anchor_asset.asset_type,
                     Asset.active.is_(True), Asset.out_of_service.is_(False),
                     Asset.is_external.is_(False))
             .order_by(Asset.booking_priority, Asset.id).all())
    same = [u for u in units
            if ((u.model_group or "").strip().lower() or f"id-{u.id}") == grp]
    free = [u for u in same if availability.is_asset_available(db, u, start, end)]
    return free


@router.get("/transfer-quote")
def public_transfer_quote(location: str, passengers: int = 1,
                          round_trip: bool = False, db: Session = Depends(get_db)):
    """Price a transfer to/from a guest-typed location via GPS radius pricing.
    Used by the widget so guests can add a transfer to a jet/boat booking.
    Returns {ok, price, distance_km, label} or {ok:false, reason}."""
    from app.services import geo_service
    loc = (location or "").strip()
    if len(loc) < 2:
        return {"ok": False, "reason": "need_location"}
    res = geo_service.price_for_location(db, loc, max(1, passengers),
                                         service="transfer", round_trip=round_trip)
    if res.get("status") == "ok":
        return {"ok": True, "price": res["price"],
                "distance_km": res.get("distance_km"),
                "label": loc, "round_trip": bool(round_trip)}
    # unknown route -> can't price automatically; guest can still ask by email
    return {"ok": False, "reason": res.get("reason", "no_price"),
            "distance_km": res.get("distance_km")}


@router.get("/availability")
def public_availability(asset_id: int, start: str, package_id: int,
                        qty: int = 1, db: Session = Depends(get_db)):
    """How many units of this model are free at `start` for the package duration?
    Returns available count and whether the requested qty fits."""
    asset = db.get(Asset, asset_id)
    if not asset:
        return {"available": False, "free": 0, "error": "no_asset"}
    try:
        from app.core.timeutil import local_to_utc
        st = datetime.fromisoformat(start)
        st = local_to_utc(st)  # widget time is local Zagreb wall-clock
    except Exception:
        return {"available": False, "free": 0, "error": "bad_date"}
    pkgs = {p["package_id"]: p for p in pricing.list_packages(asset)}
    pkg = pkgs.get(package_id)
    if not pkg:
        return {"available": False, "free": 0, "error": "no_package"}
    end = st + timedelta(minutes=pkg["duration_minutes"])
    free = _free_units_in_group(db, asset, st, end)
    return {"available": len(free) >= max(1, qty), "free": len(free)}


@router.post("/book")
def public_book(payload: dict, request: Request, db: Session = Depends(get_db)):
    """Quantity-aware booking from the widget. The guest picks a MODEL + quantity;
    we assign that many free units for the slot, create a booking per unit, and
    return ONE Stripe checkout for the combined deposit. Balance on site.
    Expects: asset_id (any unit of the model), package_id, start (ISO), qty,
    passengers, name, email, phone, addon_ids[].
    """
    from app.services import payment_service
    anchor = db.get(Asset, int(payload.get("asset_id", 0)))
    if not anchor or anchor.is_external or not anchor.active or anchor.out_of_service:
        return {"error": "asset_unavailable"}
    try:
        from app.core.timeutil import local_to_utc
        st = datetime.fromisoformat(payload["start"])
        st = local_to_utc(st)  # widget time is local Zagreb wall-clock
    except Exception:
        return {"error": "bad_date"}
    # never allow booking in the past, or sooner than this asset's lead time
    from datetime import timezone as _tz
    now_utc = datetime.now(_tz.utc)
    if st.tzinfo is None:
        st = st.replace(tzinfo=_tz.utc)
    lead_h = settings_service.lead_time_hours(db, anchor.asset_type)
    earliest = now_utc + timedelta(hours=lead_h)
    if st < now_utc:
        return {"error": "past_date"}
    if st < earliest:
        return {"error": "too_soon", "lead_time_hours": lead_h}
    pkgs = {p["package_id"]: p for p in pricing.list_packages(anchor)}
    pkg = pkgs.get(int(payload.get("package_id", 0)))
    if not pkg:
        return {"error": "no_package"}
    end = st + timedelta(minutes=pkg["duration_minutes"])

    qty = max(1, int(payload.get("qty") or 1))
    free = _free_units_in_group(db, anchor, st, end)
    if len(free) < qty:
        return {"error": "not_available", "free": len(free)}
    chosen = free[:qty]

    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    phone = (payload.get("phone") or "").strip()
    if not email:
        return {"error": "email_required"}
    passengers = int(payload.get("passengers") or 1)
    # at least one person per unit; jet skis hold at most 2 per unit
    passengers = max(passengers, qty)
    if anchor.asset_type == "jetski":
        passengers = min(passengers, 2 * qty)

    addon_ids = payload.get("addon_ids") or []
    addons = (db.query(AddOn).filter(AddOn.id.in_([int(x) for x in addon_ids]),
                                     AddOn.active.is_(True)).all()
              if addon_ids else [])
    # add-ons apply once per booking group (not per unit)
    addons_total = sum(
        (a.price * passengers if a.per_person else a.price) for a in addons)
    addon_names = ", ".join(a.name for a in addons)

    # Optional transfer: the guest typed a location; price it server-side via GPS
    # (never trust a price sent from the browser). Transfer is paid up front.
    transfer_total = 0.0
    transfer_label = ""
    transfer_pickup = ""
    transfer_dir = ""
    t_loc = (payload.get("transfer_location") or "").strip()
    if t_loc:
        from app.services import geo_service
        t_round = bool(payload.get("transfer_round_trip"))
        tq = geo_service.price_for_location(db, t_loc, passengers,
                                            service="transfer", round_trip=t_round)
        if tq.get("status") == "ok":
            transfer_total = tq["price"]
            transfer_pickup = t_loc
            transfer_dir = "round" if t_round else "one_way"
            dir_txt = "povratni" if t_round else "jednosmjerni"
            transfer_label = (f"Transfer ({dir_txt}) — {t_loc}: "
                              f"+{transfer_total:.2f} EUR")

    # Jet ski 2nd-person surcharge: a jet holds up to 2 people; each jet's 2nd
    # person costs extra. With qty jets and `passengers` total people, the number
    # of "2nd people" = passengers - qty (first person on each jet is free).
    extra_person_total = 0.0
    if anchor.asset_type == "jetski" and passengers > qty:
        fee = settings_service.jetski_extra_person_fee(db)
        extra_people = passengers - qty
        extra_person_total = round(fee * extra_people, 2)

    cust = db.query(Customer).filter(Customer.email.ilike(email)).first()
    if not cust:
        cust = Customer(full_name=name or email, email=email, phone=phone)
        db.add(cust); db.commit(); db.refresh(cust)
    else:
        # the guest just typed these in the widget on purpose — trust them over
        # whatever stale name/phone we may have stored from an earlier email
        if name:
            cust.full_name = name
        if phone:
            cust.phone = phone
        db.commit()
    # remember the widget's language so the PDF/email go out in the same language
    wlang = (payload.get("lang") or "").strip().lower()[:2]
    if wlang in ("hr", "en", "de") and cust.language != wlang:
        cust.language = wlang
        db.commit()

    # create one booking per unit; combine deposits into a single checkout
    bookings = []
    for i, unit in enumerate(chosen):
        # each physical unit has its own package rows — match by name/duration
        upkgs = pricing.list_packages(unit)
        upkg = next((p for p in upkgs if p["name"] == pkg["name"]
                     and p["duration_minutes"] == pkg["duration_minutes"]), None)
        if not upkg:
            continue
        b = booking_service.create_booking(
            db, asset_id=unit.id, customer_id=cust.id,
            package_id=upkg["package_id"],
            start=st, end=end, source="widget", passengers=passengers)
        # link to the canonical tour for reporting (one id per tour)
        from app.services import tour_service
        b.tour_type_id = tour_service.match_tour_id(
            db, anchor.asset_type, pkg["name"], pkg["duration_minutes"])
        db.commit()
        if i == 0 and (addons_total or extra_person_total or transfer_total):
            b.total_price = (b.total_price or 0) + addons_total + extra_person_total + transfer_total
            notes = []
            if extra_person_total:
                notes.append(f"Dodatna osoba (2/jet): +{extra_person_total:.2f} EUR")
            if addons_total:
                notes.append(f"Add-ons: {addon_names} (+{addons_total:.2f} EUR)")
            if transfer_label:
                notes.append(transfer_label)
            b.transfer_note = " | ".join(notes)
        if i == 0:
            if transfer_pickup:
                b.pickup_location = transfer_pickup
            elif (settings_service.get(db, "meeting_arranged", "0") or "0") == "1":
                # spot can't be advertised; flag it so the owner knows to call
                b.pickup_location = "Dogovor s gostom"
            db.commit()
        bookings.append(b)
    if not bookings:
        return {"error": "no_package"}

    # Deposit = package deposit (per unit) + FULL add-ons + FULL transfer. Add-ons
    # and transfer are paid 100% up front (real cost/reserved); extra-person fee on
    # site. This protects the business if the guest no-shows.
    total_deposit = sum(b.deposit_amount or 0 for b in bookings) + addons_total + transfer_total
    total_price = sum(b.total_price or 0 for b in bookings)
    lead = bookings[0]

    # --- PARTNER tour: charge ONLY the commission online; the rest is paid to the
    # partner on the boat and must never pass through our gateway. ---
    from app.services import provider_service
    if provider_service.is_partner(anchor):
        problems = provider_service.validate_partner_asset(anchor)
        if problems:
            log.warning("partner_booking_blocked", asset=anchor.name, problems=problems)
            return {"error": "partner_data_missing", "problems": problems}
        amt = provider_service.partner_amounts(anchor)
        online = round(amt["commission"] * qty, 2)
        # hard safety gate before charging
        try:
            provider_service.assert_partner_charge_safe(anchor, amt["commission"])
        except provider_service.PartnerChargeError:
            return {"error": "partner_overcharge_blocked"}
        # store split on the lead booking for the voucher
        lead.total_price = round(amt["total"] * qty, 2)
        lead.transfer_note = ((lead.transfer_note + " | ") if lead.transfer_note else "") + \
            (f"PARTNER: {anchor.provider_name} (OIB {anchor.provider_oib}) · "
             f"provizija {online:.2f}€ online · na brodu {amt['pay_on_site']*qty:.2f}€")
        db.commit()
        charge_amount = online
        label = f"Provizija — {_re_strip(anchor.name)}"
    else:
        charge_amount = total_deposit
        label = f"{qty}× {pkg['name']} — {_re_strip(anchor.name)}" if qty > 1 else anchor.name

    pay = payment_service.create_deposit_checkout(
        lead, label, guest_email=email, override_amount=charge_amount,
        group_booking_ids=[b.id for b in bookings])
    if not pay.get("url"):
        return {"error": "payment_failed", "booking_id": lead.id}
    log.info("public_booking_created", booking_id=lead.id, asset=anchor.name,
             qty=qty, units=[u.name for u in chosen], provider=anchor.provider_type,
             charged_online=charge_amount, addons=addon_names)
    return {"ok": True, "booking_id": lead.id, "checkout_url": pay["url"],
            "deposit": charge_amount, "total": total_price, "qty": qty,
            "provider_type": anchor.provider_type}


def _re_strip(name):
    import re as _re
    return _re.sub(r"\s*\(\d+\)\s*$", "", name or "").strip()


# Serve the widget page itself. Embed on any site via link or iframe:
#   https://app.rentoraai.com/book/jetski
from fastapi import APIRouter as _AR
widget_router = _AR(tags=["widget"])


@widget_router.get("/book/{asset_type}")
def widget_page(asset_type: str):
    return FileResponse("app/static/widget.html", media_type="text/html")


@widget_router.get("/v/{token}")
def voucher_view_page(token: str):
    """Public skipper-facing page reached by scanning the voucher QR."""
    return FileResponse("app/static/voucher_view.html", media_type="text/html")


@widget_router.get("/api/v/{token}")
def voucher_view_data(token: str, db: Session = Depends(get_db)):
    """Booking details for the skipper view. Token is the booking's voucher_token
    (unguessable) — no login needed, but only this booking is exposed."""
    from app.models.booking import Booking
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.core.timeutil import fmt_local
    from app.services import provider_service, settings_service
    b = db.query(Booking).filter(Booking.voucher_token == token).first()
    if not token or not b:
        return {"ok": False}
    a = db.get(Asset, b.asset_id)
    c = db.get(Customer, b.customer_id)
    is_partner = bool(a and provider_service.is_partner(a))
    if is_partner and a:
        amt = provider_service.partner_amounts(a)
        to_collect = amt["pay_on_site"]
        total = amt["total"]
        commission = amt["commission"]
    else:
        total = b.total_price or 0
        to_collect = max(total - (b.amount_paid or 0), 0)
        commission = b.amount_paid or 0
    return {
        "ok": True,
        "booking_id": b.id,
        "business": settings_service.brand_for_type(db, a.asset_type if a else ""),
        "asset": a.name if a else "—",
        "tour": b.package_name or "",
        "when": fmt_local(b.start_datetime),
        "guests": b.passengers or 0,
        "guest": (c.full_name if c and c.full_name and c.full_name != (c.email or "")
                  else (c.email if c else "—")),
        "phone": (c.phone if c else "") or "",
        "provider_type": "partner" if is_partner else "own",
        "provider_name": (a.provider_name if is_partner and a else ""),
        "paid_online": round(commission, 2),
        "to_collect": round(to_collect, 2),
        "total": round(total, 2),
        "pickup": getattr(b, "pickup_location", "") or "",
        "note": getattr(b, "transfer_note", "") or "",
        "currency": "EUR",
    }


from fastapi.responses import HTMLResponse


def _result_page(title, msg, ok=True):
    color = "#1a8a5a" if ok else "#c0392b"
    icon = "✓" if ok else "✕"
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#f6f9fb;color:#0f2230;display:grid;place-items:center;min-height:100vh;margin:0}}
.box{{background:#fff;border-radius:18px;box-shadow:0 8px 30px rgba(16,40,56,.1);
padding:40px 32px;max-width:420px;text-align:center;margin:16px}}
.ic{{width:68px;height:68px;border-radius:50%;background:{color};color:#fff;
display:grid;place-items:center;font-size:34px;margin:0 auto 18px}}
h1{{font-size:22px;margin:0 0 8px}}p{{color:#6a7e8c;line-height:1.5;margin:0}}
.pw{{margin-top:24px;font-size:11px;color:#9fb0bb}}</style></head>
<body><div class="box"><div class="ic">{icon}</div><h1>{title}</h1><p>{msg}</p>
<div class="pw">Powered by <b>RentoraAI</b></div></div></body></html>""")


@widget_router.get("/pay/success")
def pay_success():
    return _result_page(
        "Plaćanje uspješno!",
        "Hvala! Vaš depozit je primljen i rezervacija je potvrđena. "
        "Potvrdu ćete dobiti na email. Vidimo se! / Payment received — your "
        "booking is confirmed. A confirmation is on its way to your email.",
        ok=True)


@widget_router.get("/pay/cancel")
def pay_cancel():
    return _result_page(
        "Plaćanje otkazano",
        "Plaćanje nije dovršeno. Možete pokušati ponovno kad god želite. / "
        "Payment was not completed. You can try again any time.",
        ok=False)
