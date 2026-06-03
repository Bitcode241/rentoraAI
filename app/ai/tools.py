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
    b = booking_service.create_booking(db, asset_id, customer_id,
                                        _parse(start), _parse(end),
                                        source="ai", actor="ai-agent",
                                        package_id=package_id)
    return {"booking_id": b.id, "status": b.status, "package": b.package_name,
            "total_price": b.total_price, "deposit": b.deposit_amount}


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
    "cancel_booking": cancel_booking,
    "get_customer_history": get_customer_history,
    "list_transfer_zones": list_transfer_zones,
    "get_transfer_price": get_transfer_price,
    "send_email": send_email,
    "send_whatsapp_message": send_whatsapp_message,
}
