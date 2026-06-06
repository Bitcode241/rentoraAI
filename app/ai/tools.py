"""AI-callable tools. Every tool reads from DB / Calendar — never guesses."""
from datetime import datetime
from dateutil import parser as dtparser
from sqlalchemy.orm import Session
from app.models.asset import Asset
from app.models.customer import Customer
from app.services import availability, pricing, booking_service, conversation_service
from app.integrations.gmail import gmail_service
from app.integrations.whatsapp import whatsapp_service


def _parse(dt: str) -> datetime:
    return dtparser.parse(dt)


def _resolve_asset(db, asset_id=None, asset_name=""):
    """Find an asset by id OR by (fuzzy) name. Returns the Asset or None.
    Lets the AI work with the boat NAME the guest used, never needing an id."""
    from app.models.asset import Asset
    if asset_id:
        a = db.get(Asset, asset_id)
        if a:
            return a
    if asset_name:
        name = asset_name.strip().lower()
        assets = db.query(Asset).filter(Asset.active.is_(True)).all()
        # exact (case-insensitive) first
        for a in assets:
            if a.name.lower() == name:
                return a
        # then "contains" either direction (handles "Atlantic 750" vs "Atlantic Marine 750")
        for a in assets:
            an = a.name.lower()
            if name in an or an in name:
                return a
        # then loose: all significant words of the query appear in the name
        words = [w for w in name.replace("-", " ").split() if len(w) > 1]
        for a in assets:
            an = a.name.lower()
            if words and all(w in an for w in words):
                return a
    return None


def update_customer_phone(db: Session, customer_id: int, phone: str):
    """Save the guest's phone number on their profile."""
    from app.models.customer import Customer
    c = db.get(Customer, customer_id)
    if not c:
        return {"error": "customer_not_found"}
    c.phone = phone.strip()
    db.commit()
    return {"ok": True, "phone": c.phone}


def find_asset_by_name(db: Session, name: str):
    """Look up one of our assets by name. Returns id/name/type or not_found."""
    a = _resolve_asset(db, asset_name=name)
    if not a:
        return {"found": False, "message": f"No asset matching '{name}'."}
    return {"found": True, "asset_id": a.id, "name": a.name,
            "asset_type": a.asset_type, "is_external": bool(getattr(a, "is_external", False))}


def _serialize_assets(results, dedupe=False):
    out = []
    for r in results:
        a = r["asset"]
        show_lic = getattr(a, "show_license_to_customer", True)
        out.append({
            "asset_id": a.id,
            "name": a.name,
            "type": a.asset_type,
            "capacity": a.capacity,
            # Only expose license info if the business wants customers to see it
            "requires_license": a.requires_license if show_lic else None,
            "location": a.location,
            "packages": pricing.list_packages(a),
            "quote": r.get("quote"),
            # internal flag: external boats need owner confirmation before booking.
            # The AI uses this to route, but must NOT reveal it to the guest.
            "is_external": bool(getattr(a, "is_external", False)),
        })
    if not dedupe:
        return out

    # Collapse identical units (same type, capacity, package set) into one
    # offering with a count + the list of underlying asset_ids, so the AI shows
    # the option once instead of listing 6 identical jet skis.
    groups = {}
    for item in out:
        pkg_key = tuple(sorted((p["name"], p["price"]) for p in item["packages"]))
        key = (item["type"], item["capacity"], pkg_key)
        if key not in groups:
            groups[key] = {
                "type": item["type"],
                "capacity": item["capacity"],
                "packages": item["packages"],
                "available_units": 0,
                "asset_ids": [],
                "example_name": item["name"],
            }
        groups[key]["available_units"] += 1
        groups[key]["asset_ids"].append(item["asset_id"])
    return list(groups.values())


def find_available_boats(db: Session, passengers: int, start: str, end: str):
    # Boats are individually named/different -> no dedupe.
    return _serialize_assets(availability.find_available(db, "boat", passengers, _parse(start), _parse(end)))


def find_available_jetskis(db: Session, passengers: int, start: str, end: str):
    # Jet skis are identical -> collapse to one offering with a unit count.
    return _serialize_assets(
        availability.find_available(db, "jetski", passengers, _parse(start), _parse(end)),
        dedupe=True)


def check_availability(db: Session, asset_id: int, start: str, end: str):
    asset = db.get(Asset, asset_id)
    if not asset:
        return {"error": "asset_not_found"}
    avail = availability.is_asset_available(db, asset, _parse(start), _parse(end))
    return {"asset_id": asset_id, "available": avail}


def get_prices(db: Session, asset_id: int, start: str = "", end: str = ""):
    asset = db.get(Asset, asset_id)
    if not asset:
        return {"error": "asset_not_found"}
    packages = pricing.list_packages(asset)
    base = {
        "asset_id": asset.id, "name": asset.name,
        "deposit_percent": getattr(asset, "deposit_percent", 0),
        "packages": packages,
    }
    if not packages:
        # legacy fallback
        base["price_hour"] = asset.price_hour
        base["price_half_day"] = asset.price_half_day
        base["price_full_day"] = asset.price_full_day
    return base


def create_booking(db: Session, asset_id: int, customer_id: int, start: str, end: str,
                   package_id: int = None):
    # External boats must NOT be booked directly — they need owner confirmation.
    from app.models.asset import Asset
    asset = db.get(Asset, asset_id)
    if asset and getattr(asset, "is_external", False):
        return {"error": "external_asset",
                "message": "This boat needs owner confirmation first. "
                           "Call request_external_availability instead of booking."}
    b = booking_service.create_booking(db, asset_id, customer_id,
                                        _parse(start), _parse(end),
                                        source="ai", actor="ai-agent",
                                        package_id=package_id)
    return {"booking_id": b.id, "status": b.status, "package": b.package_name,
            "total_price": b.total_price, "deposit": b.deposit_amount}


def send_deposit_link(db: Session, customer_id: int, start: str,
                      end: str, asset_id: int = None, asset_name: str = "",
                      package_id: int = None, guest_mailbox: str = ""):
    """Create a pending booking and email the guest a Stripe deposit link.
    Accepts either asset_id OR asset_name (the boat name the guest used).
    The booking is NOT confirmed until the deposit is actually paid."""
    from app.models.customer import Customer
    from app.services import payment_service
    from app.integrations.email_imap import MultiMailboxManager
    asset = _resolve_asset(db, asset_id=asset_id, asset_name=asset_name)
    if not asset:
        return {"error": "asset_not_found",
                "message": f"Could not find a boat matching '{asset_name or asset_id}'."}
    if getattr(asset, "is_external", False):
        return {"error": "external_asset",
                "message": "External boat — use request_external_availability."}
    # create the booking; it stays pending until paid
    b = booking_service.create_booking(db, asset.id, customer_id,
                                        _parse(start), _parse(end),
                                        source="ai", actor="ai-agent",
                                        package_id=package_id)
    cust = db.get(Customer, customer_id)
    res = payment_service.create_deposit_checkout(
        b, asset.name, cust.email if cust else "")
    if "url" not in res:
        return {"error": "checkout_failed", "message": res.get("message", "")}
    b.stripe_session_id = res["session_id"]
    b.payment_status = "awaiting_payment"
    db.commit()
    # email the guest the link, from the mailbox they wrote to
    mgr = MultiMailboxManager.from_db(db)
    if mgr.enabled and cust and cust.email:
        from_box = guest_mailbox or next(iter(mgr.services.keys()), "")
        deposit = b.deposit_amount or 0
        body = (f"Pozdrav,\n\nza potvrdu rezervacije ({asset.name}) molimo uplatu "
                f"depozita od {deposit:.2f} EUR putem sigurne poveznice:\n\n"
                f"{res['url']}\n\nRezervacija se potvrđuje nakon uplate. Hvala!")
        mgr.reply_from(from_box, cust.email, "Potvrda rezervacije — depozit", body)
    return {"booking_id": b.id, "status": "awaiting_payment", "asset": asset.name,
            "payment_url": res["url"],
            "message": "Deposit link created and emailed. ALSO include the payment_url "
                       "directly in your reply so the guest has it immediately. The "
                       "booking confirms after payment."}


def request_external_availability(db: Session, customer_id: int,
                                  start: str, end: str, passengers: int,
                                  price: float, asset_id: int = None,
                                  asset_name: str = "", package_id: int = None,
                                  guest_mailbox: str = ""):
    """For an EXTERNAL (partner) boat: ask the owner if it's free. Does NOT book.
    Accepts asset_id OR asset_name. The owner is emailed; when they reply DA, the
    booking is created automatically. Tell the guest you're checking availability."""
    from app.services import external_service
    from app.integrations.email_imap import MultiMailboxManager
    from app.models.asset import Asset
    from app.models.customer import Customer
    asset = _resolve_asset(db, asset_id=asset_id, asset_name=asset_name)
    customer = db.get(Customer, customer_id)
    if not asset or not asset.is_external:
        return {"error": "not_external",
                "message": f"'{asset_name or asset_id}' is not a known external boat."}
    req = external_service.create_request(
        db, asset, customer, start=_parse(start), end=_parse(end),
        passengers=passengers, price=price, guest_mailbox=guest_mailbox)
    req.package_id = package_id or 0
    db.commit()
    # email the owner now
    mgr = MultiMailboxManager.from_db(db)
    if mgr.enabled and asset.owner_email:
        body = external_service.owner_email_body(req, asset)
        from_box = guest_mailbox or next(iter(mgr.services.keys()), "")
        mgr.reply_from(from_box, asset.owner_email,
                       f"Upit za plovilo {asset.name} (ref: {req.token})", body)
    return {"status": "owner_asked", "request_id": req.id,
            "message": "Owner has been asked. Tell the guest you're checking "
                       "availability and will confirm shortly."}


def cancel_booking(db: Session, booking_id: int):
    b = booking_service.cancel_booking(db, booking_id, actor="ai-agent")
    return {"booking_id": b.id, "status": b.status}


def get_customer_history(db: Session, customer_id: int):
    msgs = conversation_service.history(db, customer_id)
    return [{"channel": m.channel, "direction": m.direction, "body": m.body} for m in msgs]


def list_transfer_zones(db: Session):
    """All known transfer destinations with car/van one-way prices."""
    from app.services import transfer_service
    return transfer_service.list_zones(db)


def get_transfer_price(db: Session, location: str, passengers: int,
                       round_trip: bool = False):
    """Price a transfer to a known zone. If the location is unknown, ask the
    customer to clarify (do NOT invent a price)."""
    from app.services import transfer_service
    zone = transfer_service.find_zone(db, location)
    if not zone:
        known = [z["name"] for z in transfer_service.list_zones(db)]
        return {"error": "unknown_location", "ask_customer": True,
                "known_zones": known,
                "message": "Location not in price list — ask the customer which "
                           "exact location, or escalate to a human for a custom quote."}
    return transfer_service.quote_transfer(zone, passengers, round_trip)


def send_email(db: Session, customer_id: int, subject: str, body: str):
    cust = db.get(Customer, customer_id)
    if not cust or not cust.email:
        return {"error": "no_email"}
    mid = gmail_service.send(cust.email, subject, body)
    conversation_service.add_message(db, customer_id, "email", "outbound", body)
    return {"sent": True, "message_id": mid}


def send_whatsapp_message(db: Session, customer_id: int, body: str):
    cust = db.get(Customer, customer_id)
    if not cust or not cust.phone:
        return {"error": "no_phone"}
    mid = whatsapp_service.send(cust.phone, body)
    conversation_service.add_message(db, customer_id, "whatsapp", "outbound", body)
    return {"sent": True, "message_id": mid}


# OpenAI function-calling schema
TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "find_available_boats",
        "description": "Find available boats with capacity >= passengers for a time window.",
        "parameters": {"type": "object", "properties": {
            "passengers": {"type": "integer"},
            "start": {"type": "string", "description": "ISO datetime"},
            "end": {"type": "string", "description": "ISO datetime"}},
            "required": ["passengers", "start", "end"]}}},
    {"type": "function", "function": {
        "name": "find_available_jetskis",
        "description": "Find available jet skis.",
        "parameters": {"type": "object", "properties": {
            "passengers": {"type": "integer"}, "start": {"type": "string"}, "end": {"type": "string"}},
            "required": ["passengers", "start", "end"]}}},
    {"type": "function", "function": {
        "name": "check_availability",
        "description": "Check if a specific asset is available.",
        "parameters": {"type": "object", "properties": {
            "asset_id": {"type": "integer"}, "start": {"type": "string"}, "end": {"type": "string"}},
            "required": ["asset_id", "start", "end"]}}},
    {"type": "function", "function": {
        "name": "get_prices",
        "description": "Get authoritative prices for an asset, optionally with a quote.",
        "parameters": {"type": "object", "properties": {
            "asset_id": {"type": "integer"}, "start": {"type": "string"}, "end": {"type": "string"}},
            "required": ["asset_id"]}}},
    {"type": "function", "function": {
        "name": "create_booking",
        "description": "Create a booking. Only after confirming availability and the chosen package price. Pass the package_id the customer selected.",
        "parameters": {"type": "object", "properties": {
            "asset_id": {"type": "integer"}, "customer_id": {"type": "integer"},
            "start": {"type": "string"}, "end": {"type": "string"},
            "package_id": {"type": "integer", "description": "Chosen price package id"}},
            "required": ["asset_id", "customer_id", "start", "end"]}}},
    {"type": "function", "function": {
        "name": "send_deposit_link",
        "description": "For OUR OWN boats/jetskis: when a slot is free and the guest "
                       "wants to book, create a pending booking and email the guest a "
                       "Stripe deposit link. Pass asset_name (the boat name the guest "
                       "used) OR asset_id — you do NOT need to ask the guest for an ID, "
                       "the system resolves the boat by name. The booking confirms after "
                       "the deposit is paid. Tell the guest a payment link has been sent.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "integer"},
            "asset_name": {"type": "string", "description": "Boat name the guest used"},
            "asset_id": {"type": "integer"},
            "start": {"type": "string"}, "end": {"type": "string"},
            "package_id": {"type": "integer", "description": "Chosen price package id"},
            "guest_mailbox": {"type": "string", "description": "Address the guest wrote to"}},
            "required": ["customer_id", "start", "end"]}}},
    {"type": "function", "function": {
        "name": "find_asset_by_name",
        "description": "Resolve a boat/jetski NAME to its system id. Use when the guest "
                       "names a specific boat so you can act on it. Never ask the guest "
                       "for an asset ID — use this instead.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "update_customer_phone",
        "description": "Save the guest's phone number on their profile when they provide it.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "integer"}, "phone": {"type": "string"}},
            "required": ["phone"]}}},
    {"type": "function", "function": {
        "name": "request_external_availability",
        "description": "For an EXTERNAL/partner boat (is_external=true in availability "
                       "results): ask the owner if it's free instead of booking. "
                       "Does NOT create a booking. After calling, tell the guest you're "
                       "checking availability and will confirm shortly. Never reveal to "
                       "the guest that the boat belongs to someone else.",
        "parameters": {"type": "object", "properties": {
            "asset_name": {"type": "string", "description": "Boat name the guest used"},
            "asset_id": {"type": "integer"}, "customer_id": {"type": "integer"},
            "start": {"type": "string"}, "end": {"type": "string"},
            "passengers": {"type": "integer"},
            "price": {"type": "number", "description": "Quoted package price"},
            "package_id": {"type": "integer"},
            "guest_mailbox": {"type": "string", "description": "Address the guest wrote to"}},
            "required": ["customer_id", "start", "end", "passengers", "price"]}}},
    {"type": "function", "function": {
        "name": "cancel_booking",
        "description": "Cancel a booking by id.",
        "parameters": {"type": "object", "properties": {"booking_id": {"type": "integer"}},
            "required": ["booking_id"]}}},
    {"type": "function", "function": {
        "name": "get_customer_history",
        "description": "Retrieve unified conversation history for a customer.",
        "parameters": {"type": "object", "properties": {"customer_id": {"type": "integer"}},
            "required": ["customer_id"]}}},
    {"type": "function", "function": {
        "name": "send_email",
        "description": "Send an email to a customer.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "integer"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["customer_id", "subject", "body"]}}},
    {"type": "function", "function": {
        "name": "send_whatsapp_message",
        "description": "Send a WhatsApp message to a customer.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "integer"}, "body": {"type": "string"}},
            "required": ["customer_id", "body"]}}},
    {"type": "function", "function": {
        "name": "list_transfer_zones",
        "description": "List known transfer destinations and their car/van one-way prices.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_transfer_price",
        "description": "Price a pickup/drop-off transfer to a known location for a group. "
                       "Car for up to 3 people, van for 4-8, van+car for 9+. Prices are "
                       "one-way; set round_trip for both directions. If the location is "
                       "unknown, ask the customer which location instead of guessing.",
        "parameters": {"type": "object", "properties": {
            "location": {"type": "string"},
            "passengers": {"type": "integer"},
            "round_trip": {"type": "boolean"}},
            "required": ["location", "passengers"]}}},
]

TOOL_FUNCS = {
    "find_available_boats": find_available_boats,
    "find_available_jetskis": find_available_jetskis,
    "check_availability": check_availability,
    "get_prices": get_prices,
    "create_booking": create_booking,
    "request_external_availability": request_external_availability,
    "send_deposit_link": send_deposit_link,
    "find_asset_by_name": find_asset_by_name,
    "update_customer_phone": update_customer_phone,
    "cancel_booking": cancel_booking,
    "get_customer_history": get_customer_history,
    "list_transfer_zones": list_transfer_zones,
    "get_transfer_price": get_transfer_price,
    "send_email": send_email,
    "send_whatsapp_message": send_whatsapp_message,
}
