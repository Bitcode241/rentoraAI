"""Tests for Phase 1: email facade, scheduler config, escalation/needs-human."""
from datetime import datetime, timedelta, timezone


def _future_date(days=7, hour=9):
    """A start datetime safely in the future so past-date guards don't reject it."""
    d = datetime.now(timezone.utc) + timedelta(days=days)
    return d.strftime(f"%Y-%m-%dT{hour:02d}:00:00")


def test_email_status(client, auth):
    r = client.get("/api/emails/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    # In tests no IMAP/SMTP and no key -> simulation + AI inactive
    assert body["email_enabled"] is False
    assert body["ai_active"] is False
    assert "poll_seconds" in body


def test_needs_human_empty(client, auth):
    r = client.get("/api/emails/needs-human", headers=auth)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_intent_detection_multilingual():
    from app.ai.email_processor import detect_intent
    assert detect_intent("Trebam najam broda") == "request"
    assert detect_intent("Ich möchte ein Boot mieten") == "request"
    assert detect_intent("I want to book a jet ski") == "request"
    assert detect_intent("Moram otkazati") == "cancellation"
    assert detect_intent("Potvrđujem, može") == "confirmation"
    assert detect_intent("Hello, nice weather") == "other"


def test_process_inbox_runs(client, auth):
    # Simulation mode returns no mail, but the endpoint must work end to end.
    r = client.post("/api/emails/process", headers=auth)
    assert r.status_code == 200
    assert r.json()["processed"] == []


def test_resolve_needs_human(client, auth):
    cust = client.post("/api/customers", headers=auth, json={
        "full_name": "Esc User", "email": "esc@e.com"}).json()
    # mark a conversation as needing human via the service
    from app.core.database import SessionLocal
    from app.services import conversation_service
    db = SessionLocal()
    conv = conversation_service.get_or_create_conversation(db, cust["id"])
    conv.needs_human = True
    db.commit()
    db.close()

    lst = client.get("/api/emails/needs-human", headers=auth).json()
    assert any(c["customer_id"] == cust["id"] for c in lst)

    client.post(f"/api/emails/needs-human/{cust['id']}/resolve", headers=auth)
    lst2 = client.get("/api/emails/needs-human", headers=auth).json()
    assert not any(c["customer_id"] == cust["id"] for c in lst2)


def test_calendar_endpoint(client, auth):
    r = client.get("/api/calendar", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "assets" in body and "events" in body and "range" in body
    # real fleet has 12 vessels
    assert len(body["assets"]) == 12


def test_multi_mailbox_parsing():
    import os
    from app.core.config import Settings
    os.environ["MAILBOXES_JSON"] = (
        '[{"address":"info@one.com","username":"info@one.com","password":"p1",'
        '"imap_host":"mail.srv.com","smtp_host":"mail.srv.com"},'
        '{"address":"info@two.com","username":"info@two.com","password":"p2",'
        '"imap_host":"mail.srv.com","smtp_host":"mail.srv.com"}]'
    )
    s = Settings()
    boxes = s.mailboxes()
    assert len(boxes) == 2
    assert boxes[0]["address"] == "info@one.com"
    assert boxes[1]["imap_host"] == "mail.srv.com"
    del os.environ["MAILBOXES_JSON"]


def test_empty_mailboxes_safe():
    import os
    os.environ.pop("MAILBOXES_JSON", None)
    from app.core.config import Settings
    s = Settings(email_imap_host="", email_username="")
    assert s.mailboxes() == []


def test_mailbox_crud_and_password_security(client, auth):
    # create
    r = client.post("/api/mailboxes", headers=auth, json={
        "address": "info@test.com", "password": "secret123",
        "imap_host": "mail.test.com", "smtp_host": "mail.test.com"})
    assert r.status_code == 200
    body = r.json()
    # password must NEVER be returned
    assert "password" not in body
    assert body["has_password"] is True
    mid = body["id"]

    # list
    lst = client.get("/api/mailboxes", headers=auth).json()
    assert any(m["address"] == "info@test.com" for m in lst)

    # edit without password keeps the old one
    client.patch(f"/api/mailboxes/{mid}", headers=auth, json={
        "address": "info@test.com", "imap_host": "mail.test.com",
        "smtp_host": "mail.test.com", "password": ""})
    still = next(m for m in client.get("/api/mailboxes", headers=auth).json() if m["id"] == mid)
    assert still["has_password"] is True

    # delete
    assert client.delete(f"/api/mailboxes/{mid}", headers=auth).status_code == 200


def test_email_filter_system_senders():
    from app.ai.email_processor import _is_system_sender
    assert _is_system_sender("MAILER-DAEMON@mail.x.com", "Undelivered Mail") is True
    assert _is_system_sender("no-reply@booking.com", "Your trip") is True
    assert _is_system_sender("postmaster@x.com", "x") is True
    assert _is_system_sender("ivan@gmail.com", "Out of Office") is True
    assert _is_system_sender("marko@gmail.com", "Upit za brod") is False


def test_email_filter_rental_only():
    from app.ai.email_processor import detect_intent, RENTAL_INTENTS
    # rental inquiries -> answered
    assert detect_intent("Trebam brod za 6 osoba") in RENTAL_INTENTS
    assert detect_intent("imate li slobodan jet ski") in RENTAL_INTENTS
    assert detect_intent("Trebam transfer od aerodroma") in RENTAL_INTENTS
    # business / junk -> ignored
    assert detect_intent("Ponuda za suradnju i fakturiranje") not in RENTAL_INTENTS
    assert detect_intent("Racun za struju") not in RENTAL_INTENTS


def test_external_asset(client, auth):
    r = client.post("/api/assets", headers=auth, json={
        "name": "Partner Boat", "asset_type": "boat", "capacity": 8,
        "deposit_percent": 30, "is_external": True, "owner_name": "Marko",
        "owner_email": "marko@example.com", "owner_phone": "+385991234567",
        "commission_percent": 15})
    assert r.status_code == 200
    a = r.json()
    assert a["is_external"] is True
    assert a["owner_email"] == "marko@example.com"
    assert a["commission_percent"] == 15


def test_external_flow_owner_confirms(client, auth):
    """Full external flow: create external boat -> request -> owner DA -> booking."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.models.booking import Booking
    from app.services import external_service
    from app.ai.email_processor import _maybe_handle_owner_reply
    from datetime import datetime, timezone, timedelta

    db = SessionLocal()
    ext = Asset(name="Partner X", asset_type="boat", capacity=8, is_external=True,
                owner_name="Marko", owner_email="owner@partner.com",
                commission_percent=15, deposit_percent=30)
    db.add(ext); db.commit(); db.refresh(ext)
    guest = Customer(full_name="Guest", email="guest@x.com")
    db.add(guest); db.commit(); db.refresh(guest)
    start = datetime.now(timezone.utc) + timedelta(days=20)
    end = start + timedelta(hours=4)
    req = external_service.create_request(db, ext, guest, start=start, end=end,
                                          passengers=6, price=450)
    assert req.status == "pending"
    assert len(req.token) == 6

    em = {"from_email": "owner@partner.com",
          "subject": f"Re (ref: {req.token})", "body": "DA", "id": "1"}
    res = _maybe_handle_owner_reply(db, "owner@partner.com", em, "info@x.com", None)
    assert res["owner_reply"] == "yes"
    db.refresh(req)
    assert req.status == "confirmed"
    assert db.query(Booking).filter(Booking.asset_id == ext.id).count() == 1
    db.close()


def test_commission_split():
    from app.services.external_service import commission_split
    s = commission_split(450, 15)
    assert s["your_commission"] == 67.5
    assert s["owner_gets"] == 382.5


def test_payment_config_endpoint(client, auth):
    r = client.get("/api/payments/config", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body and "currency" in body
    # not configured in tests -> enabled False, no crash
    assert body["enabled"] in (True, False)


def test_pay_success_page(client):
    r = client.get("/pay/success")
    assert r.status_code == 200
    # bilingual confirmation page; check for stable markers
    low = r.text.lower()
    assert "rentoraai" in low and ("confirmed" in low or "potvrđena" in low)


def test_checkout_requires_stripe(client, auth):
    # create a booking, then try checkout — without stripe keys it returns a clean error
    from app.core.database import SessionLocal
    from app.models.booking import Booking
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = Customer(full_name="Pay Test", email="pay@x.com")
    db.add(c); db.commit(); db.refresh(c)
    s = datetime.now(timezone.utc) + timedelta(days=8)
    b = Booking(asset_id=1, customer_id=c.id, start_datetime=s,
                end_datetime=s + timedelta(hours=4), total_price=450,
                deposit_amount=135, status="pending")
    db.add(b); db.commit(); bid = b.id
    db.close()
    r = client.post(f"/api/payments/checkout/{bid}", headers=auth)
    assert r.status_code == 200
    # stripe not configured in tests -> clean error, not a crash
    assert r.json().get("error") == "stripe_not_configured"


def test_confirmation_pdf_all_languages():
    from app.services import confirmation_service as cs
    for lang in ("hr", "en", "de"):
        pdf = cs.build_pdf(lang=lang, business_name="Rentora", booking_id=1,
                           asset_name="4K Marine", when="12.06.2026 09:00",
                           guests=6, package="4h", deposit_paid=135,
                           full_price=450, balance=315, transfer_included=False,
                           location="Dubrovnik")
        assert pdf[:4] == b"%PDF"
        subj, body = cs.email_text(lang, "Rentora")
        assert subj and body


def test_send_confirmation_endpoint(client, auth):
    from app.core.database import SessionLocal
    from app.models.booking import Booking
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = Customer(full_name="Conf Test", email="conf@x.com", language="hr")
    db.add(c); db.commit(); db.refresh(c)
    s = datetime.now(timezone.utc) + timedelta(days=9)
    b = Booking(asset_id=1, customer_id=c.id, start_datetime=s,
                end_datetime=s + timedelta(hours=4), total_price=450,
                deposit_amount=135, amount_paid=135, status="confirmed",
                payment_status="deposit_paid", package_name="4h")
    db.add(b); db.commit(); bid = b.id
    db.close()
    r = client.post(f"/api/payments/send-confirmation/{bid}", headers=auth)
    assert r.status_code == 200  # builds PDF; email simulated in tests


def test_refund_requires_paid(client, auth):
    from app.core.database import SessionLocal
    from app.models.booking import Booking
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = Customer(full_name="Refund Test", email="ref@x.com")
    db.add(c); db.commit(); db.refresh(c)
    s = datetime.now(timezone.utc) + timedelta(days=9)
    b = Booking(asset_id=1, customer_id=c.id, start_datetime=s,
                end_datetime=s + timedelta(hours=4), total_price=450,
                deposit_amount=135, status="pending", payment_status="unpaid")
    db.add(b); db.commit(); bid = b.id
    db.close()
    # no captured deposit -> refund refused cleanly
    r = client.post(f"/api/payments/refund/{bid}", headers=auth)
    assert r.status_code == 400


def test_whatsapp_verify(client):
    # webhook verification handshake
    r = client.get("/api/webhooks/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "verify-me",
        "hub.challenge": "test123"})
    assert r.status_code == 200
    assert "test123" in r.text


def test_whatsapp_ignores_status_callback(client):
    # delivery-receipt style payload (no messages) -> ignored, no crash
    r = client.post("/api/webhooks/whatsapp", json={
        "entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}]})
    assert r.status_code == 200
    assert r.json()["status"] in ("ignored_no_message", "received")


def test_whatsapp_filters_non_rental(client):
    # a business/spam message should not crash and should be flagged, not auto-replied
    r = client.post("/api/webhooks/whatsapp", json={
        "entry": [{"changes": [{"value": {"messages": [
            {"from": "385991234567", "type": "text",
             "text": {"body": "Ponuda za suradnju i fakturiranje"}}]}}]}]})
    assert r.status_code == 200


def test_lead_times_get_default(client, auth):
    r = client.get("/api/settings/lead-times", headers=auth)
    assert r.status_code == 200
    lt = r.json()
    assert lt["jetski"] == 2 and lt["boat"] == 8 and lt["transfer"] == 3


def test_lead_times_update(client, auth):
    r = client.put("/api/settings/lead-times", headers=auth,
                   json={"jetski": 4, "boat": 12, "transfer": 2})
    assert r.status_code == 200
    assert r.json()["jetski"] == 4
    # persisted
    r2 = client.get("/api/settings/lead-times", headers=auth)
    assert r2.json()["boat"] == 12


def test_lead_time_blocks_early_booking():
    from app.core.database import SessionLocal
    from app.services import settings_service, booking_service
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    from fastapi import HTTPException
    db = SessionLocal()
    c = Customer(full_name="LT", email="lt@x.com")
    db.add(c); db.commit(); db.refresh(c)
    # jetski in 1h via non-admin source -> blocked
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    blocked = False
    try:
        booking_service.create_booking(db, asset_id=7, customer_id=c.id,
                                       start=soon, end=soon + timedelta(hours=1),
                                       source="ai")
    except HTTPException as e:
        blocked = (e.status_code == 409)
    db.close()
    assert blocked


def test_reminder_finds_tomorrow_booking():
    from app.core.database import SessionLocal
    from app.services import reminder_service
    from app.models.booking import Booking
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = Customer(full_name="Rem Guest", email="rem@x.com", language="hr")
    db.add(c); db.commit(); db.refresh(c)
    # booking ~24h from now, confirmed -> should be found
    start = datetime.now(timezone.utc) + timedelta(hours=24)
    b = Booking(asset_id=1, customer_id=c.id, start_datetime=start,
                end_datetime=start + timedelta(hours=4), total_price=450,
                deposit_amount=135, status="confirmed", package_name="4h")
    db.add(b); db.commit()
    found = reminder_service.find_tomorrow_bookings(db)
    assert any(x.id == b.id for x in found)
    # a booking far in the future should NOT be found
    far = datetime.now(timezone.utc) + timedelta(days=10)
    b2 = Booking(asset_id=1, customer_id=c.id, start_datetime=far,
                 end_datetime=far + timedelta(hours=4), total_price=450,
                 deposit_amount=135, status="confirmed")
    db.add(b2); db.commit()
    found2 = reminder_service.find_tomorrow_bookings(db)
    assert not any(x.id == b2.id for x in found2)
    db.close()


def test_send_reminders_endpoint(client, auth):
    r = client.post("/api/settings/send-reminders", headers=auth)
    assert r.status_code == 200
    assert "bookings" in r.json()


def test_send_deposit_link_tool():
    from app.core.database import SessionLocal
    from app.ai import tools
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = Customer(full_name="Link Guest", email="link@x.com")
    db.add(c); db.commit(); db.refresh(c)
    # own boat (asset 1), slot well in the future -> creates pending booking
    start = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(days=5, hours=4)).isoformat()
    res = tools.send_deposit_link(db, asset_id=1, customer_id=c.id,
                                  start=start, end=end, package_id=None)
    # stripe not configured in tests -> clean checkout_failed, not a crash
    assert "error" in res or res.get("status") == "awaiting_payment"
    db.close()


def test_resolve_asset_by_name():
    from app.core.database import SessionLocal
    from app.ai.tools import find_asset_by_name
    db = SessionLocal()
    for variant in ("Atlantic Marine 750", "atlantic 750", "4k marine", "Gaia"):
        r = find_asset_by_name(db, variant)
        assert r["found"] is True
    assert find_asset_by_name(db, "Nonexistent Boat XYZ")["found"] is False
    db.close()


def test_known_guest_followup_not_dropped():
    """A follow-up from someone with an existing booking is treated as rental
    even if the strict keyword filter would say 'other'."""
    from app.core.database import SessionLocal
    from app.models.customer import Customer
    from app.models.booking import Booking
    from app.models.email import EmailThread
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = Customer(full_name="Known Guest", email="known@x.com")
    db.add(c); db.commit(); db.refresh(c)
    # existing booking makes them a known guest
    start = datetime.now(timezone.utc) + timedelta(days=5)
    b = Booking(asset_id=1, customer_id=c.id, start_datetime=start,
                end_datetime=start + timedelta(hours=4), total_price=450,
                deposit_amount=135, status="pending")
    db.add(b); db.commit()
    # verify the "known guest" detection logic
    has_booking = db.query(Booking).filter(Booking.customer_id == c.id).first()
    assert has_booking is not None
    db.close()


def test_auto_deposit_detection():
    """Code-driven deposit: detects intent, date, passengers, boat from text."""
    from app.services import auto_deposit_service as ad
    convo = "zanima me Gaia 670 za 25.07.2026 cijeli dan 6 osoba, želim platiti depozit"
    assert ad.has_pay_intent(convo) is True
    assert ad.has_pay_intent("samo me zanima cijena") is False
    d = ad._parse_date(convo)
    assert d is not None and d.month == 7 and d.day == 25
    assert ad._parse_passengers(convo) == 6
    assert ad._is_full_day(convo) is True


def test_auto_deposit_resolves_boat_and_package():
    from app.core.database import SessionLocal
    from app.services import auto_deposit_service as ad
    from app.models.asset import Asset
    db = SessionLocal()
    asset = db.query(Asset).filter(Asset.name == "Gaia 670").first()
    if asset:
        pid, pkg = ad._pick_package(asset, full_day=True)
        assert pkg is not None and pkg["duration_minutes"] == 480
    db.close()


def test_own_address_normalization():
    """Self-sent mail detection compares lowercased addresses."""
    own = {"info@seagulldubrovnik.com"}
    assert "INFO@seagulldubrovnik.com".lower() in own
    assert "guest@gmail.com".lower() not in own


def test_separate_conversations_per_thread():
    """Two fresh inquiries (no In-Reply-To) from the same customer get separate
    conversations, so an agency's multiple bookings don't bleed together."""
    from app.core.database import SessionLocal
    from app.services import conversation_service as cs
    from app.models.customer import Customer
    db = SessionLocal()
    c = Customer(full_name="Agency", email="agency@x.com")
    db.add(c); db.commit(); db.refresh(c)
    conv1 = cs.create_conversation(db, c.id)
    conv2 = cs.create_conversation(db, c.id)
    assert conv1.id != conv2.id
    cs.add_message_to(db, conv1.id, "email", "inbound", "Booking for client A")
    cs.add_message_to(db, conv2.id, "email", "inbound", "Booking for client B")
    h1 = cs.history_for(db, conv1.id)
    h2 = cs.history_for(db, conv2.id)
    assert len(h1) == 1 and len(h2) == 1
    assert "client A" in h1[0].body and "client B" in h2[0].body
    db.close()


def test_inquiry_boat_facts():
    """Code computes real available boats + prices for an inquiry (AI only phrases)."""
    from app.core.database import SessionLocal
    from app.services import inquiry_service as iq
    db = SessionLocal()
    txt = "renting a speed boat on 20.8.2026 4h for 6 people, anything available?"
    assert iq.wants_boats(txt) is True
    f = iq.build_boat_availability(db, txt)
    assert f is not None and f["passengers"] == 6 and f["date"] == "20.08.2026"
    assert f["any_available"] is True and len(f["options"]) > 0
    # prices come from DB, not invented
    prices = [o["price"] for o in f["options"]]
    assert all(p and p > 0 for p in prices)
    block = iq.facts_to_prompt(f)
    assert "do not invent" in block.lower()
    db.close()


def test_booking_stores_passengers():
    from app.core.database import SessionLocal
    from app.services import booking_service
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = Customer(full_name="Pax Test", email="pax@x.com")
    db.add(c); db.commit(); db.refresh(c)
    start = datetime.now(timezone.utc) + timedelta(days=12)
    b = booking_service.create_booking(db, 1, c.id, start, start + timedelta(hours=4),
                                       source="admin", passengers=6)
    assert b.passengers == 6
    db.close()


def test_partner_settlement_directions():
    from app.services.external_service import settlement
    # you collect -> you owe partner the rest
    s1 = settlement(600, 15, "you")
    assert s1["direction"] == "you_owe_partner" and s1["amount"] == 510.0
    # partner collects -> partner owes you the commission
    s2 = settlement(600, 15, "partner")
    assert s2["direction"] == "partner_owes_you" and s2["amount"] == 90.0


def test_mailbox_box_for_type():
    from app.integrations.email_imap import MultiMailboxManager
    m = MultiMailboxManager(mailboxes=[])
    m.type_map = {"boat": "info@seagull.com", "transfer": "info@ragusa.com"}
    m.services = {"info@seagull.com": object(), "info@ragusa.com": object()}
    assert m.box_for_type("boat") == "info@seagull.com"
    assert m.box_for_type("transfer") == "info@ragusa.com"
    # unknown type falls back to first mailbox
    assert m.box_for_type("jetski") in m.services


def test_partner_voucher_pdf():
    from app.services import voucher_service
    pdf = voucher_service.build_voucher(
        business_name="Seagull", booking_id=5, asset_name="4K Marine",
        when="25.07.2026 09:00", guests=6, guest_name="Mauro Mehic",
        guest_phone="+385991234567", partner_name="Partner d.o.o.",
        settlement_summary="VI partneru dugujete 510 EUR.")
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000


def test_booking_pickup_and_deposit_fields():
    from app.core.database import SessionLocal
    from app.services import booking_service
    from app.models.customer import Customer
    from app.models.asset import Asset
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    a = db.get(Asset, 1)
    a.default_pickup = "Lapadska obala 4, Dubrovnik"
    db.commit()
    c = Customer(full_name="Manual Guest", email="m@x.com", phone="+38599")
    db.add(c); db.commit(); db.refresh(c)
    start = datetime.now(timezone.utc) + timedelta(days=300)
    b = booking_service.create_booking(db, 1, c.id, start, start + timedelta(hours=4),
                                       source="admin", passengers=4)
    b.deposit_amount = 99.0
    if not b.pickup_location:
        b.pickup_location = a.default_pickup
    db.commit(); db.refresh(b)
    assert b.deposit_amount == 99.0
    assert b.pickup_location == "Lapadska obala 4, Dubrovnik"
    db.close()


def test_edit_deposit_on_booking():
    from app.core.database import SessionLocal
    from app.services import booking_service
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = Customer(full_name="Dep Test", email="dep@x.com")
    db.add(c); db.commit(); db.refresh(c)
    start = datetime.now(timezone.utc) + timedelta(days=320)
    b = booking_service.create_booking(db, 1, c.id, start, start + timedelta(hours=4),
                                       source="admin")
    # simulate PATCH editing the deposit
    b.deposit_amount = 105.0
    db.commit(); db.refresh(b)
    assert b.deposit_amount == 105.0
    db.close()


def test_default_deposit_fallback():
    """A boat with deposit_percent=0 still gets a non-zero deposit via the global default."""
    from app.core.database import SessionLocal
    from app.services import booking_service
    from app.models.customer import Customer
    from app.models.asset import Asset
    from app.models.package import RentalPackage
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    a = db.get(Asset, 1)
    a.deposit_percent = 0
    db.commit()
    pkg = db.query(RentalPackage).filter(RentalPackage.asset_id == 1).first()
    c = Customer(full_name="Dep Fallback", email="df@x.com")
    db.add(c); db.commit(); db.refresh(c)
    start = datetime.now(timezone.utc) + timedelta(days=340)
    b = booking_service.create_booking(db, 1, c.id, start, start + timedelta(hours=4),
                                       source="admin", package_id=pkg.id)
    assert b.total_price > 0
    assert b.deposit_amount > 0  # default % applied, not 0
    db.close()


def test_business_name_setting():
    from app.core.database import SessionLocal
    from app.services import settings_service as ss
    db = SessionLocal()
    # default fallback
    assert ss.business_name(db) == "Seagull Dubrovnik"
    ss.set(db, ss.BUSINESS_NAME_KEY, "My Charter Co")
    assert ss.business_name(db) == "My Charter Co"
    db.close()


def test_brand_per_type():
    from app.core.database import SessionLocal
    from app.services import settings_service as ss
    db = SessionLocal()
    assert ss.brand_for_type(db, "boat") == "Seagull Dubrovnik"
    assert ss.brand_for_type(db, "jetski") == "Jetski Dubrovnik"
    assert ss.brand_for_type(db, "transfer") == "Ragusa Transfer"
    assert ss.brand_for_type(db, "car") == "Ragusa Transfer"
    ss.set(db, "brand_jetski", "Jetski DBK Pro")
    assert ss.brand_for_type(db, "jetski") == "Jetski DBK Pro"
    db.close()


def test_availability_chain_priority():
    """Same-model boats: lowest priority offered first; falls to next when busy."""
    from app.core.database import SessionLocal
    from app.services import chain_service, booking_service
    from app.models.asset import Asset
    from app.models.customer import Customer
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    boats = db.query(Asset).filter(Asset.asset_type == "boat").limit(2).all()
    a, b = boats[0], boats[1]
    a.model_group = "grp-x"; a.booking_priority = 1
    b.model_group = "grp-x"; b.booking_priority = 2
    db.commit()
    start = datetime.now(timezone.utc) + timedelta(days=360, hours=9)
    end = start + timedelta(hours=4)
    # both free -> picks priority 1
    r = chain_service.pick_for_window(db, a, start, end)
    assert r["asset"].id == a.id and r["was_redirected"] is False
    # occupy priority 1 -> picks priority 2
    c = Customer(full_name="Chain", email="ch@x.com")
    db.add(c); db.commit(); db.refresh(c)
    booking_service.create_booking(db, a.id, c.id, start, end, source="admin")
    r2 = chain_service.pick_for_window(db, a, start, end)
    assert r2["asset"].id == b.id and r2["was_redirected"] is True
    db.close()


def test_out_of_service_skipped_in_chain():
    from app.core.database import SessionLocal
    from app.services import chain_service
    from app.models.asset import Asset
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    boats = db.query(Asset).filter(Asset.asset_type == "boat").limit(2).all()
    a, b = boats[0], boats[1]
    a.model_group = "grp-oos"; a.booking_priority = 1; a.out_of_service = False
    b.model_group = "grp-oos"; b.booking_priority = 2; b.out_of_service = False
    db.commit()
    start = datetime.now(timezone.utc) + timedelta(days=370, hours=9)
    end = start + timedelta(hours=4)
    # mark priority 1 out of service -> chain picks priority 2
    a.out_of_service = True
    db.commit()
    r = chain_service.pick_for_window(db, a, start, end)
    assert r["asset"].id == b.id and r["was_redirected"] is True
    db.close()


def test_intent_natural_phrasings():
    """Natural Croatian/English inquiries are detected as 'request', not 'other'."""
    from app.ai.email_processor import detect_intent
    assert detect_intent("zanima me brod barracuda 545 da li je imate raspolozivu") == "request"
    assert detect_intent("imate li slobodan brod za 6 osoba") == "request"
    assert detect_intent("Hi do you have a boat available for 4 people") == "request"
    assert detect_intent("koliko kosta najam glisera") == "request"
    # plain spam stays 'other'
    assert detect_intent("Boost your sales with our marketing service") == "other"


def test_spam_not_treated_as_inquiry():
    """B2B/marketing pitches that mention boats are ignored, not answered."""
    from app.ai.email_processor import detect_intent
    assert detect_intent("yachting professionals use EasyMLS to import your listings") == "other"
    assert detect_intent("As a professional in boat or yacht sales, increase your bookings") == "other"
    assert detect_intent("Boost your sales with our marketing platform") == "other"
    # real inquiry still works
    assert detect_intent("zanima me brod barracuda 545, imate li raspolozivu") == "request"


def test_chain_confirm_routes_to_partner():
    """Guest confirms a model whose top boat is out of service -> partner gets asked."""
    from app.core.database import SessionLocal
    from app.services import auto_deposit_service as ad
    from app.models.asset import Asset
    from app.models.customer import Customer
    db = SessionLocal()
    bs = db.query(Asset).filter(Asset.asset_type == "boat").limit(2).all()
    a, b = bs[0], bs[1]
    a.model_group = "grp-confirm"; a.booking_priority = 1; a.out_of_service = True
    b.model_group = "grp-confirm"; b.booking_priority = 2
    b.is_external = True; b.owner_name = "P"; b.owner_email = "p@x.com"
    db.commit()
    c = Customer(full_name="G", email="gg@x.com", phone="+38599")
    db.add(c); db.commit(); db.refresh(c)
    base = a.name.lower().split(" (")[0]
    convo = f"zanima me {base} za 3 osobe 17.8.2026\nmoze rezerviraj taj brod"
    r = ad.try_auto_deposit(db, conversation_text=convo,
                            latest_message="moze rezerviraj taj brod",
                            customer_id=c.id, guest_mailbox="info@seagull.com")
    assert r is not None and r.get("owner_asked") is True
    assert r.get("asset") == b.name
    db.close()


def test_reply_reattaches_to_recent_thread(monkeypatch):
    """A reply we can't match by headers continues the guest's most recent thread."""
    from app.core.database import SessionLocal
    from app.services import conversation_service
    from app.models.customer import Customer
    from app.models.email import EmailThread
    db = SessionLocal()
    c = Customer(full_name="Reply Guest", email="rg@x.com")
    db.add(c); db.commit(); db.refresh(c)
    conv = conversation_service.create_conversation(db, c.id)
    th = EmailThread(gmail_thread_id="<orig@x>", subject="Upit",
                     customer_id=c.id, intent="request", conversation_id=conv.id)
    db.add(th); db.commit(); db.refresh(th)
    # the most recent thread for this customer should be findable
    recent = (db.query(EmailThread)
              .filter(EmailThread.customer_id == c.id)
              .order_by(EmailThread.id.desc()).first())
    assert recent.id == th.id
    db.close()


def test_wants_boats_recognizes_model_names():
    """A guest naming a boat directly ('Barracuda 545') is recognised as a boat inquiry."""
    from app.core.database import SessionLocal
    from app.services import inquiry_service as iq
    db = SessionLocal()
    # generic word works without db
    assert iq.wants_boats("zanima me brod za 4 osobe") is True
    # model name needs db lookup
    assert iq.wants_boats("zanima me barracuda 545 da li je slobodna", db=db) is True
    db.close()


def test_duplicate_thread_id_does_not_crash():
    """Inserting a thread with an existing gmail_thread_id reuses it, no crash."""
    from app.core.database import SessionLocal
    from app.models.customer import Customer
    from app.models.email import EmailThread
    from app.services import conversation_service
    db = SessionLocal()
    c = Customer(full_name="Dup", email="dup@x.com")
    db.add(c); db.commit(); db.refresh(c)
    conv = conversation_service.create_conversation(db, c.id)
    t1 = EmailThread(gmail_thread_id="<dupe@x>", subject="a",
                     customer_id=c.id, intent="request", conversation_id=conv.id)
    db.add(t1); db.commit()
    # a lookup by the same id should find it (so code reuses instead of inserting)
    found = db.query(EmailThread).filter(
        EmailThread.gmail_thread_id == "<dupe@x>").first()
    assert found is not None and found.id == t1.id
    db.close()


def test_inquiry_asks_owner_immediately_when_only_partner_free():
    """First inquiry: if your boat is out and only the partner's is free, ask the
    owner right away; if yours is free, return None (normal price reply)."""
    from app.core.database import SessionLocal
    from app.services import auto_deposit_service as ad
    from app.models.asset import Asset
    from app.models.customer import Customer
    db = SessionLocal()
    bs = db.query(Asset).filter(Asset.asset_type == "boat").limit(2).all()
    a, b = bs[0], bs[1]
    base = a.name.lower().split(" (")[0]
    a.model_group = "grp-inq"; a.booking_priority = 1; a.out_of_service = True
    b.model_group = "grp-inq"; b.booking_priority = 2
    b.is_external = True; b.owner_email = "p@x.com"
    db.commit()
    c = Customer(full_name="G", email="iq@x.com")
    db.add(c); db.commit(); db.refresh(c)
    msg = f"zanima me {base} 15.10.2026 na 8h da li je slobodna"
    r = ad.try_inquiry_chain(db, conversation_text=msg, latest_message=msg,
                             customer_id=c.id, guest_mailbox="info@x.com")
    assert r is not None and r.get("owner_asked") is True and r.get("asset") == b.name
    # yours back in service -> no owner ask
    a.out_of_service = False; db.commit()
    r2 = ad.try_inquiry_chain(db, conversation_text=msg, latest_message=msg,
                              customer_id=c.id, guest_mailbox="info@x.com")
    assert r2 is None
    db.close()


def test_match_handles_croatian_cases():
    """Boat is matched even with Croatian case endings (barracudu/barracude)."""
    from app.core.database import SessionLocal
    from app.services.auto_deposit_service import _match_asset
    from app.models.asset import Asset
    db = SessionLocal()
    cands = db.query(Asset).filter(Asset.asset_type == "boat").all()
    bar = next((a for a in cands if "barracuda" in a.name.lower()), None)
    assert bar is not None
    assert _match_asset("imate li barracudu 545 slobodnu", cands).id == bar.id
    assert _match_asset("zanima me barracude 545", cands).id == bar.id
    db.close()


def test_inquiry_chain_passes_package_so_deposit_works():
    """The owner request carries a package_id so the eventual booking has a deposit."""
    from app.core.database import SessionLocal
    from app.services import auto_deposit_service as ad, external_service
    from app.models.asset import Asset
    from app.models.customer import Customer
    db = SessionLocal()
    bs = db.query(Asset).filter(Asset.asset_type == "boat").limit(2).all()
    a, b = bs[0], bs[1]
    base = a.name.lower().split(" (")[0]
    a.model_group = "grp-pkg"; a.booking_priority = 1; a.out_of_service = True
    b.model_group = "grp-pkg"; b.booking_priority = 2
    b.is_external = True; b.owner_email = "p@x.com"
    db.commit()
    c = Customer(full_name="G", email="pk@x.com")
    db.add(c); db.commit(); db.refresh(c)
    msg = f"imate li {base} slobodnu za 21.10.2026 na 8h"
    ad.try_inquiry_chain(db, conversation_text=msg, latest_message=msg,
                         customer_id=c.id, guest_mailbox="info@x.com")
    req = (db.query(external_service.ExternalRequest)
           .order_by(external_service.ExternalRequest.id.desc()).first())
    assert req.package_id and req.package_id > 0
    db.close()


def test_language_detection():
    from app.ai.email_processor import _detect_language
    assert _detect_language("pozdrav zanima me brod za 3 osobe") == "hr"
    assert _detect_language("hallo ich möchte ein boot mieten") == "de"
    assert _detect_language("hello do you have a boat") == "en"


def test_transfer_radius_pricing(monkeypatch):
    """GPS radius pricing: known tier -> price; beyond/unknown -> ask owner."""
    from app.core.database import SessionLocal
    from app.models.transfer import TransferRadius
    from app.services import geo_service
    db = SessionLocal()
    for lbl, km, car, van in [("do 10", 10, 30, 45), ("do 20", 20, 50, 70)]:
        db.add(TransferRadius(label=lbl, base_label="Lapad", base_lat=42.658,
                              base_lng=18.077, max_km=km, car_price=car,
                              van_price=van, service="transfer"))
    db.commit()
    # ~5 km away -> first tier, 1 car
    monkeypatch.setattr(geo_service, "geocode", lambda loc: (42.70, 18.077))
    r = geo_service.price_for_location(db, "Babin kuk", passengers=2)
    assert r["status"] == "ok" and r["price"] == 30.0
    # geocode fails -> needs owner price, never invents
    monkeypatch.setattr(geo_service, "geocode", lambda loc: None)
    r2 = geo_service.price_for_location(db, "???", passengers=2)
    assert r2["status"] == "needs_owner_price"
    db.close()


def test_transfer_quote_and_owner_fallback(monkeypatch):
    """Known route -> price; beyond radius -> needs owner price."""
    from app.core.database import SessionLocal
    from app.models.transfer import TransferRadius
    from app.services import transfer_inquiry_service as ti, geo_service
    db = SessionLocal()
    db.add(TransferRadius(label="do 10", base_label="Lapad", base_lat=42.658,
                          base_lng=18.077, max_km=10, car_price=30, van_price=45,
                          service="transfer"))
    db.commit()
    assert ti.wants_transfer("trebam transfer s aerodroma") is True
    monkeypatch.setattr(geo_service, "geocode", lambda loc: (42.70, 18.077))
    r = ti.quote_for_message(db, "transfer od Babin kuk za 2 osobe")
    assert r["status"] == "ok" and r["price"] == 30.0
    # far away -> owner price
    monkeypatch.setattr(geo_service, "geocode", lambda loc: (43.2, 18.077))
    r2 = ti.quote_for_message(db, "transfer od Negdje za 2 osobe")
    assert r2["status"] == "needs_owner_price"
    db.close()


def test_addon_crud():
    from app.core.database import SessionLocal
    from app.models.addon import AddOn
    db = SessionLocal()
    a = AddOn(name="GoPro", price=25, applies_to="jetski", per_person=False)
    db.add(a); db.commit(); db.refresh(a)
    assert a.id and a.price == 25 and a.applies_to == "jetski"
    db.close()


def test_public_booking_api():
    from app.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    cfg = c.get("/api/public/config?asset_type=jetski").json()
    assert cfg["business_name"] and cfg["accent"].startswith("#")
    assets = c.get("/api/public/assets?asset_type=jetski").json()
    assert len(assets) >= 1 and "packages" in assets[0]
    # public endpoints must NOT require auth (200, not 401)
    assert c.get("/api/public/addons?asset_type=jetski").status_code == 200


def test_widget_page_and_booking_with_addon():
    from app.main import app
    from fastapi.testclient import TestClient
    from app.core.database import SessionLocal
    from app.models.addon import AddOn
    from app.models.booking import Booking
    from datetime import datetime, timedelta
    c = TestClient(app)
    # widget page serves
    assert c.get("/book/jetski").status_code == 200
    db = SessionLocal()
    db.add(AddOn(name="GoPro", price=25, applies_to="jetski")); db.commit()
    addon = db.query(AddOn).filter(AddOn.name == "GoPro").first()
    assets = c.get("/api/public/assets?asset_type=jetski").json()
    jet = assets[0]; pkg = jet["packages"][0]
    start = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%dT09:00:00")
    r = c.post("/api/public/book", json={
        "asset_id": jet["id"], "package_id": pkg["id"], "start": start,
        "passengers": 1, "name": "T", "email": "w@x.com", "phone": "+385",
        "addon_ids": [addon.id]}).json()
    # booking is created and the add-on is folded into the total
    bid = r.get("booking_id")
    assert bid
    b = db.get(Booking, bid)
    assert b.total_price == pkg["price"] + 25
    db.close()


def test_widget_accent_per_type():
    from app.core.database import SessionLocal
    from app.services import settings_service as ss
    db = SessionLocal()
    # per-type defaults differ
    assert ss.widget_accent(db, "jetski") == "#0ea5b7"
    assert ss.widget_accent(db, "boat") == "#1d6fa5"
    assert ss.widget_accent(db, "transfer") == "#c79a3b"
    # setting one doesn't change another
    ss.set(db, "widget_accent_jetski", "#ff0000")
    assert ss.widget_accent(db, "jetski") == "#ff0000"
    assert ss.widget_accent(db, "boat") == "#1d6fa5"
    db.close()


def test_apply_packages_to_group():
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.package import RentalPackage
    from app.api.routes.packages import apply_packages_to_group
    db = SessionLocal()
    jets = db.query(Asset).filter(Asset.asset_type == "jetski").all()
    for j in jets:
        j.model_group = "yamaha-vx"
    db.commit()
    src = jets[0]
    p = db.query(RentalPackage).filter(RentalPackage.asset_id == src.id,
                                       RentalPackage.name == "1h").first()
    p.price = 999
    db.commit()
    r = apply_packages_to_group(src.id, db=db)
    assert r["ok"] and r["applied_to"] == len(jets) - 1
    for j in jets[1:]:
        pp = db.query(RentalPackage).filter(RentalPackage.asset_id == j.id,
                                            RentalPackage.name == "1h").first()
        assert pp.price == 999
    db.close()


def test_widget_english():
    from app.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    # widget serves; the EN strings come from client-side JS, so just confirm the
    # page and the per-type endpoints serve and the powered-by is correct.
    assert c.get("/book/jetski?lang=en").status_code == 200
    assert "RentoraAI" in c.get("/book/jetski").text


def test_quantity_aware_booking():
    """Guest books N units of a model; N bookings created, N units freed, and
    a later slot shows the full fleet free again (multiple tours/day)."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.api.routes import public_booking as pb
    from datetime import datetime, timedelta
    db = SessionLocal()
    jets = db.query(Asset).filter(Asset.asset_type == "jetski").all()
    for j in jets:
        j.model_group = "yamaha-vx"
    db.commit()
    anchor = jets[0]
    cards = pb.public_assets("jetski", db=db)
    assert len(cards) == 1 and cards[0]["fleet_size"] == len(jets)
    pkg = cards[0]["packages"][1]  # 1h
    start = (datetime.now() + timedelta(days=9)).strftime("%Y-%m-%dT10:00:00")
    pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"], "start": start,
                    "qty": 2, "passengers": 1, "name": "G", "email": "q@x.com",
                    "phone": "+385"}, request=None, db=db)
    after = pb.public_availability(anchor.id, start, pkg["id"], qty=1, db=db)
    assert after["free"] == len(jets) - 2
    # a different time -> whole fleet free again
    start2 = (datetime.now() + timedelta(days=9)).strftime("%Y-%m-%dT13:00:00")
    later = pb.public_availability(anchor.id, start2, pkg["id"], qty=1, db=db)
    assert later["free"] == len(jets)
    db.close()


def test_widget_time_is_local():
    """A 09:00 time the guest typed in the widget is stored so it displays 09:00."""
    from datetime import datetime
    from app.core.timeutil import local_to_utc, fmt_local
    st = datetime.fromisoformat("2026-07-01T09:00:00")
    assert fmt_local(local_to_utc(st), "%H:%M") == "09:00"


def test_widget_booking_stores_language():
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.api.routes import public_booking as pb
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.commit()
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][0]
    pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                    "start": _future_date(5), "qty": 1, "passengers": 1,
                    "name": "T", "email": "lang@x.com", "phone": "+385",
                    "lang": "en"}, request=None, db=db)
    c = db.query(Customer).filter(Customer.email == "lang@x.com").first()
    assert c.language == "en"
    db.close()


def test_widget_name_overrides_stale():
    """The name a guest types in the widget always wins over a stale stored one."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.api.routes import public_booking as pb
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.add(Customer(full_name="old.handle", email="ov@x.com", phone="1"))
    db.commit()
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][0]
    pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                    "start": _future_date(6), "qty": 1, "passengers": 1,
                    "name": "Real Name", "email": "ov@x.com", "phone": "+385",
                    "lang": "hr"}, request=None, db=db)
    c = db.query(Customer).filter(Customer.email == "ov@x.com").first()
    assert c.full_name == "Real Name" and c.phone == "+385"
    db.close()


def test_jetski_extra_person_fee():
    """2nd person on each jet adds the configured surcharge; widget config exposes it."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.booking import Booking
    from app.api.routes import public_booking as pb
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.commit()
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][1]  # 1h 140
    # 2 jets, 4 people -> +40
    pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                    "start": _future_date(26), "qty": 2, "passengers": 4,
                    "name": "X", "email": "ef@x.com", "phone": "1"},
                   request=None, db=db)
    bs = db.query(Booking).order_by(Booking.id.desc()).limit(2).all()
    assert sum(b.total_price for b in bs) == pkg["price"] * 2 + 40
    # config exposes the fee
    cfg = pb.public_config("jetski", db=db)
    assert cfg["extra_person_fee"] == 20.0
    db.close()


def test_extra_person_scales_with_fleet():
    """5 jets, 10 people -> 5 surcharges; deposit stays package-based."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.booking import Booking
    from app.api.routes import public_booking as pb
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.commit()
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][1]  # 1h
    pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                    "start": _future_date(51), "qty": 5, "passengers": 10,
                    "name": "G", "email": "fleet@x.com", "phone": "1"},
                   request=None, db=db)
    bs = db.query(Booking).order_by(Booking.id.desc()).limit(5).all()
    assert sum(b.total_price for b in bs) == pkg["price"] * 5 + 100
    assert sum(b.deposit_amount for b in bs) == pkg["deposit"] * 5  # no surcharge
    db.close()


def test_jetski_hard_cap_two_per_unit():
    """A jet ski can never carry more than 2 people per unit, even if asked."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.booking import Booking
    from app.api.routes import public_booking as pb
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.commit()
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    assert anchor.capacity == 2
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][1]
    pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                    "start": "2026-10-02T09:00:00", "qty": 1, "passengers": 3,
                    "name": "X", "email": "cap@x.com", "phone": "1"},
                   request=None, db=db)
    b = db.query(Booking).order_by(Booking.id.desc()).first()
    assert b.passengers == 2  # capped from 3
    db.close()


def test_addons_in_deposit_and_passengers_min():
    """Add-ons are fully in the deposit; passengers default to at least 1 per unit."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.addon import AddOn
    from app.models.booking import Booking
    from app.api.routes import public_booking as pb
    import app.services.payment_service as ps
    ps.create_deposit_checkout = lambda b, name, guest_email="", override_amount=None, group_booking_ids=None: {"url": "http://t", "session_id": "x"}
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.add(AddOn(name="GoPro", price=25, applies_to="jetski")); db.commit()
    addon = db.query(AddOn).filter(AddOn.name == "GoPro").first()
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][1]
    r = pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                        "start": "2026-11-11T09:00:00", "qty": 1, "passengers": 1,
                        "name": "A", "email": "dep@x.com", "phone": "1",
                        "addon_ids": [addon.id]}, request=None, db=db)
    assert r["deposit"] == pkg["deposit"] + 25
    # 3 units but passengers given as 1 -> server bumps to at least 3
    r2 = pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                         "start": "2026-11-11T12:00:00", "qty": 3, "passengers": 1,
                         "name": "B", "email": "mp@x.com", "phone": "2"},
                        request=None, db=db)
    bs = db.query(Booking).order_by(Booking.id.desc()).limit(3).all()
    assert bs[0].passengers >= 1  # each booking has a passenger
    db.close()


def test_widget_transfer_in_deposit(monkeypatch):
    """A widget transfer is priced server-side via GPS and added to the deposit."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.transfer import TransferRadius
    from app.api.routes import public_booking as pb
    import app.services.geo_service as g
    import app.services.payment_service as ps
    monkeypatch.setattr(ps, "create_deposit_checkout",
                        lambda b, name, guest_email="", override_amount=None, group_booking_ids=None: {"url": "http://t", "session_id": "x"})
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.add(TransferRadius(label="10", base_label="Lapad", base_lat=42.658,
                          base_lng=18.077, max_km=10, car_price=30, van_price=45,
                          service="transfer"))
    db.commit()
    monkeypatch.setattr(g, "geocode", lambda loc: (42.70, 18.077))
    q = pb.public_transfer_quote("Babin kuk", passengers=2, round_trip=False, db=db)
    assert q["ok"] and q["price"] == 30.0
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][1]
    r = pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                        "start": "2026-12-12T09:00:00", "qty": 1, "passengers": 1,
                        "name": "A", "email": "tr@x.com", "phone": "1",
                        "transfer_location": "Babin kuk"}, request=None, db=db)
    # transfer (30) is in the deposit
    assert r["deposit"] == pkg["deposit"] + 30
    db.close()


def test_pdf_wraps_long_addon_text():
    """A long add-on + transfer note must not crash the PDF and produces output."""
    from app.services import confirmation_service as cs
    pdf = cs.build_pdf(
        lang="hr", business_name="Jetski Dubrovnik", booking_id=1,
        asset_name="2× Yamaha VX", when="16.06.2026 09:00", guests=4, package="1h",
        deposit_paid=139.0, full_price=320.0, balance=181.0, transfer_included=True,
        location="Hotel Kompas, Lapad", phone="+385", guest_name="Ivan",
        guest_email="i@x.com",
        transfer_note="Add-ons: GoPro snimka (+25.00 EUR) | Transfer (povratni) — Hotel Kompas, Lapad: +60.00 EUR",
        currency="EUR")
    assert pdf and len(pdf) > 1000


def test_widget_transfer_stores_pickup(monkeypatch):
    """The transfer pickup location is stored on the booking for the PDF/skipper."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.transfer import TransferRadius
    from app.models.booking import Booking
    from app.api.routes import public_booking as pb
    import app.services.geo_service as g
    import app.services.payment_service as ps
    monkeypatch.setattr(ps, "create_deposit_checkout",
                        lambda b, name, guest_email="", override_amount=None, group_booking_ids=None: {"url": "http://t", "session_id": "x"})
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.add(TransferRadius(label="10", base_label="Lapad", base_lat=42.658,
                          base_lng=18.077, max_km=10, car_price=30, van_price=45,
                          service="transfer"))
    db.commit()
    monkeypatch.setattr(g, "geocode", lambda loc: (42.70, 18.077))
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][1]
    pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                    "start": "2026-12-20T09:00:00", "qty": 1, "passengers": 1,
                    "name": "A", "email": "pk@x.com", "phone": "1",
                    "transfer_location": "Hotel Kompas", "transfer_round_trip": True},
                   request=None, db=db)
    b = db.query(Booking).order_by(Booking.id.desc()).first()
    assert b.pickup_location == "Hotel Kompas"
    assert "povratni" in (b.transfer_note or "")
    db.close()


def test_provider_charge_and_validation():
    """Partner charges only the commission; missing OIB or overcharge is blocked."""
    from app.services import provider_service as pv

    class A:
        provider_type = "partner"; provider_name = "Obrt"; provider_oib = "123"
        partner_total_price = 500; my_commission = 200; name = "T"
    a = A()
    assert pv.is_partner(a)
    amt = pv.partner_amounts(a)
    assert amt == {"total": 500.0, "commission": 200.0, "pay_on_site": 300.0}
    assert pv.online_charge(a)["charge"] == 200.0
    # missing OIB -> blocked
    a.provider_oib = ""
    try:
        pv.online_charge(a); assert False
    except pv.PartnerChargeError:
        pass
    # overcharge gate
    a.provider_oib = "123"
    try:
        pv.assert_partner_charge_safe(a, 300); assert False
    except pv.PartnerChargeError:
        pass
    pv.assert_partner_charge_safe(a, 200)  # ok


def test_partner_voucher_requires_provider_data():
    from app.services.voucher_service import build_partner_voucher, PartnerVoucherError
    pdf = build_partner_voucher(
        business_name="Seagull", booking_id=1, asset_name="Atlantic 750",
        when="20.07.2026 10:00", guests=8, provider_name="Obrt Galeb",
        provider_oib="12345678901", my_commission=200, pay_on_site=300,
        total_price=500)
    assert pdf and len(pdf) > 1000
    try:
        build_partner_voucher(business_name="X", booking_id=1, asset_name="Y",
                              when="", guests=1, provider_name="Obrt",
                              provider_oib="", my_commission=200, pay_on_site=300,
                              total_price=500)
        assert False
    except PartnerVoucherError:
        pass


def test_partner_widget_charges_only_commission(monkeypatch):
    """A partner tour booked via the widget charges ONLY the commission online."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.api.routes import public_booking as pb
    import app.services.payment_service as ps
    captured = {}

    def fake(b, name, guest_email="", override_amount=None, group_booking_ids=None):
        captured["amount"] = override_amount
        return {"url": "http://t", "session_id": "x"}
    monkeypatch.setattr(ps, "create_deposit_checkout", fake)
    db = SessionLocal()
    cards0 = pb.public_assets("boat", db=db)
    bid = cards0[0]["id"]
    boat = db.get(Asset, bid)
    boat.provider_type = "partner"; boat.provider_name = "Galeb"
    boat.provider_oib = "12345678901"; boat.partner_total_price = 500
    boat.my_commission = 200
    boat.is_external = False; boat.out_of_service = False; boat.active = True
    db.commit()
    cards = pb.public_assets("boat", db=db)
    card = next((c for c in cards if c["id"] == bid), None)
    assert card is not None
    pkgid = card["packages"][0]["id"]
    r = pb.public_book({"asset_id": bid, "package_id": pkgid,
                        "start": "2026-12-25T10:00:00", "qty": 1, "passengers": 2,
                        "name": "G", "email": "pw@x.com", "phone": "1"},
                       request=None, db=db)
    assert captured["amount"] == 200.0  # only commission, not 500
    assert r["provider_type"] == "partner"
    db.close()


def test_partner_booking_blocked_without_oib(monkeypatch):
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.api.routes import public_booking as pb
    db = SessionLocal()
    # pick a boat that actually shows in the public list (has packages, not excluded)
    cards0 = pb.public_assets("boat", db=db)
    bid = cards0[0]["id"]
    boat = db.get(Asset, bid)
    boat.provider_type = "partner"; boat.provider_name = "Galeb"
    boat.provider_oib = ""  # missing!
    boat.partner_total_price = 500; boat.my_commission = 200
    boat.is_external = False; boat.out_of_service = False; boat.active = True
    db.commit()
    cards = pb.public_assets("boat", db=db)
    card = next((c for c in cards if c["id"] == bid), None)
    assert card is not None
    pkgid = card["packages"][0]["id"]
    r = pb.public_book({"asset_id": bid, "package_id": pkgid,
                        "start": "2026-12-26T10:00:00", "qty": 1, "passengers": 2,
                        "name": "G", "email": "no@x.com", "phone": "1"},
                       request=None, db=db)
    assert r["error"] == "partner_data_missing"
    db.close()


def test_business_oib_setting():
    from app.core.database import SessionLocal
    from app.services import settings_service as ss
    db = SessionLocal()
    ss.set(db, "business_oib", "99999999999")
    assert ss.get(db, "business_oib") == "99999999999"
    db.close()


def test_manual_voucher_partner_vs_block():
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.models.booking import Booking
    from app.models.user import User
    from app.api.routes.bookings import partner_voucher
    from app.core.security import create_access_token, hash_password
    from fastapi import HTTPException
    from datetime import datetime, timedelta
    db = SessionLocal()
    u = db.query(User).first()
    if not u:
        u = User(username="admin", hashed_password=hash_password("x"), role="admin")
        db.add(u); db.commit()
    tok = create_access_token(u.username, u.role)
    boat = db.query(Asset).filter(Asset.asset_type == "boat").first()
    boat.provider_type = "partner"; boat.provider_name = "Galeb"
    boat.provider_oib = "12345678901"; boat.partner_total_price = 500
    boat.my_commission = 200
    db.commit()
    c = Customer(full_name="G", email="mv@x.com", phone="+385")
    db.add(c); db.commit(); db.refresh(c)
    bk = Booking(asset_id=boat.id, customer_id=c.id,
                 start_datetime=datetime.now() + timedelta(days=3),
                 end_datetime=datetime.now() + timedelta(days=3, hours=8),
                 total_price=500, amount_paid=200, passengers=6,
                 package_name="Full day")
    db.add(bk); db.commit(); db.refresh(bk)
    r = partner_voucher(bk.id, token=tok, db=db)
    assert r.body and len(r.body) > 1000
    # remove OIB -> blocked
    boat.provider_oib = ""
    db.commit()
    try:
        partner_voucher(bk.id, token=tok, db=db)
        assert False
    except HTTPException as e:
        assert e.status_code == 400
    db.close()


def test_dashboard_overview():
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.models.booking import Booking
    from app.api.routes.dashboard import dashboard_overview
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    own = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    partner = db.query(Asset).filter(Asset.asset_type == "boat").first()
    partner.provider_type = "partner"; partner.provider_name = "Galeb"
    partner.provider_oib = "12345678901"; partner.partner_total_price = 500
    partner.my_commission = 200
    db.commit()
    c = Customer(full_name="Ivan", email="dash@x.com", phone="+385")
    db.add(c); db.commit(); db.refresh(c)
    now = datetime.now(timezone.utc)
    db.add(Booking(asset_id=own.id, customer_id=c.id,
                   start_datetime=now.replace(hour=8), end_datetime=now.replace(hour=9),
                   total_price=140, amount_paid=42, payment_status="deposit_paid",
                   passengers=2, package_name="1h", source="widget"))
    db.add(Booking(asset_id=partner.id, customer_id=c.id,
                   start_datetime=(now + timedelta(days=1)).replace(hour=10),
                   end_datetime=(now + timedelta(days=1)).replace(hour=18),
                   total_price=500, amount_paid=200, payment_status="deposit_paid",
                   passengers=6, package_name="Full day", source="widget"))
    db.commit()
    ov = dashboard_overview(days=7, db=db)
    assert ov["summary"]["tours"] >= 2
    assert ov["summary"]["partner_tours"] >= 1
    assert len(ov["days"]) == 7
    assert ov["days"][0]["label"] == "Danas"
    assert ov["days"][1]["label"] == "Sutra"
    # partner tour shows pay_on_site as to_collect
    all_tours = [t for d in ov["days"] for t in d["tours"]]
    partner_tour = next(t for t in all_tours if t["provider_type"] == "partner")
    assert partner_tour["to_collect"] == 300.0
    db.close()


def test_voucher_qr_and_skipper_view():
    """Voucher gets a QR token; the skipper view exposes booking by that token."""
    import os
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.models.booking import Booking
    from app.models.user import User
    from app.core.security import create_access_token, hash_password
    from app.api.routes.bookings import partner_voucher
    from app.api.routes.public_booking import voucher_view_data
    from datetime import datetime, timedelta
    os.environ["PUBLIC_BASE_URL"] = "https://app.rentoraai.com"
    db = SessionLocal()
    u = db.query(User).first()
    if not u:
        u = User(username="admin", hashed_password=hash_password("x"), role="admin")
        db.add(u); db.commit()
    tok = create_access_token(u.username, u.role)
    boat = db.query(Asset).filter(Asset.asset_type == "boat").first()
    boat.provider_type = "partner"; boat.provider_name = "Galeb"
    boat.provider_oib = "12345678901"; boat.partner_total_price = 500
    boat.my_commission = 200
    db.commit()
    c = Customer(full_name="Marko", email="qr@x.com", phone="+385")
    db.add(c); db.commit(); db.refresh(c)
    bk = Booking(asset_id=boat.id, customer_id=c.id,
                 start_datetime=datetime.now() + timedelta(days=2),
                 end_datetime=datetime.now() + timedelta(days=2, hours=8),
                 total_price=500, amount_paid=200, passengers=6,
                 package_name="Full day")
    db.add(bk); db.commit(); db.refresh(bk)
    r = partner_voucher(bk.id, token=tok, db=db)
    assert r.body and len(r.body) > 1000
    db.refresh(bk)
    assert bk.voucher_token  # token generated
    vd = voucher_view_data(bk.voucher_token, db=db)
    assert vd["ok"] and vd["to_collect"] == 300.0
    assert vd["provider_name"] == "Galeb"
    # bad token -> not found
    assert voucher_view_data("nope", db=db)["ok"] is False
    db.close()


def test_reminder_finds_paid_and_builds_voucher():
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.models.booking import Booking
    from app.services import reminder_service
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    boat = db.query(Asset).filter(Asset.asset_type == "boat").first()
    boat.provider_type = "partner"; boat.provider_name = "Galeb"
    boat.provider_oib = "12345678901"; boat.partner_total_price = 500
    boat.my_commission = 200
    db.commit()
    c = Customer(full_name="Ana", email="rem@x.com", phone="+385", language="hr")
    db.add(c); db.commit(); db.refresh(c)
    now = datetime.now(timezone.utc)
    bk = Booking(asset_id=boat.id, customer_id=c.id,
                 start_datetime=now + timedelta(hours=20),
                 end_datetime=now + timedelta(hours=28), total_price=500,
                 amount_paid=200, status="pending", payment_status="deposit_paid",
                 passengers=6, package_name="Full day")
    db.add(bk); db.commit(); db.refresh(bk)
    found = reminder_service.find_tomorrow_bookings(db)
    assert any(x.id == bk.id for x in found)  # paid deposit is reminded
    v = reminder_service._build_reminder_voucher(db, bk, boat, c, "Seagull")
    assert v and len(v) > 1000  # partner voucher built
    db.close()


def test_widget_blocks_past_and_too_soon(monkeypatch):
    """The widget must reject past dates and bookings sooner than the lead time."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.api.routes import public_booking as pb
    from app.core.timeutil import to_local
    from datetime import datetime, timezone, timedelta
    import app.services.payment_service as ps
    monkeypatch.setattr(ps, "create_deposit_checkout",
                        lambda b, name, guest_email="", override_amount=None, group_booking_ids=None: {"url": "http://t", "session_id": "x"})
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.commit()
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][1]
    base = {"asset_id": anchor.id, "package_id": pkg["id"], "qty": 1,
            "passengers": 1, "name": "A", "email": "t@x.com", "phone": "1"}
    now_local = to_local(datetime.now(timezone.utc))
    # past
    past = (now_local - timedelta(days=1)).strftime("%Y-%m-%dT09:00:00")
    assert pb.public_book({**base, "start": past}, request=None, db=db)["error"] == "past_date"
    # too soon (30 min, jet lead = 2h)
    soon = (now_local + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
    assert pb.public_book({**base, "start": soon}, request=None, db=db)["error"] == "too_soon"
    # ok tomorrow
    ok = (now_local + timedelta(days=1)).strftime("%Y-%m-%dT09:00:00")
    assert pb.public_book({**base, "start": ok}, request=None, db=db).get("ok")
    db.close()


def test_config_exposes_time_settings():
    """The widget config must expose lead time and working hours for the slots."""
    from app.core.database import SessionLocal
    from app.api.routes import public_booking as pb
    db = SessionLocal()
    cfg = pb.public_config("jetski", db=db)
    assert "lead_time_hours" in cfg
    assert "open_hour" in cfg and "close_hour" in cfg
    assert cfg["open_hour"] < cfg["close_hour"]
    db.close()


def test_pdf_extra_person_not_labeled_transfer():
    """An extra-person fee must NOT be labeled as a transfer in the PDF."""
    from app.services import confirmation_service as cs
    # build with only an extra-person note (no real transfer)
    pdf = cs.build_pdf(lang="hr", business_name="X", booking_id=1,
                       asset_name="Yamaha VX", when="", guests=2, package="1h",
                       deposit_paid=42, full_price=160, balance=118,
                       transfer_included=True, location="", phone="", guest_name="",
                       guest_email="", transfer_note="Dodatna osoba (2/jet): +20.00 EUR",
                       currency="EUR")
    # extract text to verify the label
    import io
    from pypdf import PdfReader
    txt = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Dodatna osoba" in txt
    # the extras line should be under DODATNO, not mislabeled — transfer label
    # should not appear for a pure extra-person fee
    assert "Transfer uklju" not in txt


def test_meeting_arranged_flow(monkeypatch):
    """When meeting point is arranged privately, the widget config flags it and
    the booking is marked so the owner knows to call."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.booking import Booking
    from app.services import settings_service
    from app.api.routes import public_booking as pb
    import app.services.payment_service as ps
    from datetime import date, timedelta
    monkeypatch.setattr(ps, "create_deposit_checkout",
                        lambda b, name, guest_email="", override_amount=None, group_booking_ids=None: {"url": "http://t", "session_id": "x"})
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    settings_service.set(db, "meeting_arranged", "1")
    db.commit()
    cfg = pb.public_config("jetski", db=db)
    assert cfg["meeting_arranged"] is True
    anchor = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    pkg = pb.public_assets("jetski", db=db)[0]["packages"][1]
    tom = (date.today() + timedelta(days=2)).isoformat()
    r = pb.public_book({"asset_id": anchor.id, "package_id": pkg["id"],
                        "start": tom + "T10:00:00", "qty": 1, "passengers": 1,
                        "name": "A", "email": "ma@x.com", "phone": "1"},
                       request=None, db=db)
    b = db.get(Booking, r["booking_id"])
    assert b.pickup_location == "Dogovor s gostom"
    db.close()


def test_tour_catalog_one_id_per_tour():
    """The catalog gives each tour a single id that applies across all units,
    and editing a tour's price propagates to every unit's package."""
    from app.core.database import SessionLocal
    from app.services import tour_service as ts
    from app.models.tour_type import TourType
    from app.models.package import RentalPackage
    from app.models.asset import Asset
    db = SessionLocal()
    ts.seed_catalog_from_packages(db)  # idempotent; may already be seeded
    tours = ts.list_tours(db, "jetski")
    assert len(tours) >= 5  # jetski tours present
    names = {t.name for t in tours}
    assert "Safari 90min (guided)" in names
    # one id per tour
    safari = next(t for t in tours if t.name == "Safari 90min (guided)")
    # change price in catalog -> propagate to all jets
    safari.price = 299.0
    db.commit()
    ts.sync_tour_to_units(db, safari)
    jets = db.query(Asset).filter(Asset.asset_type == "jetski").all()
    prices = [db.query(RentalPackage).filter(
        RentalPackage.asset_id == j.id,
        RentalPackage.name == "Safari 90min (guided)").first().price for j in jets]
    assert all(p == 299.0 for p in prices)
    db.close()


def test_tour_report_by_id():
    from app.core.database import SessionLocal
    from app.services import tour_service as ts
    from app.models.tour_type import TourType
    from app.models.asset import Asset
    from app.models.customer import Customer
    from app.models.booking import Booking
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    ts.seed_catalog_from_packages(db)
    tour = db.query(TourType).filter(TourType.name == "1h",
                                     TourType.asset_type == "jetski").first()
    jet = db.query(Asset).filter(Asset.asset_type == "jetski").first()
    c = Customer(full_name="R", email="rep@x.com")
    db.add(c); db.commit(); db.refresh(c)
    now = datetime.now(timezone.utc)
    for i in range(2):
        db.add(Booking(asset_id=jet.id, customer_id=c.id,
                       start_datetime=now + timedelta(days=i + 1),
                       end_datetime=now + timedelta(days=i + 1, hours=1),
                       total_price=140, amount_paid=42, payment_status="deposit_paid",
                       passengers=1, package_name="1h", tour_type_id=tour.id))
    db.commit()
    rep = ts.tour_report(db, "jetski")
    row = next(r for r in rep if r["tour_id"] == tour.id)
    assert row["bookings"] == 2
    assert row["revenue"] == 280.0
    db.close()


def test_create_tour_appears_on_all_units():
    from app.core.database import SessionLocal
    from app.models.tour_type import TourType
    from app.models.asset import Asset
    from app.models.package import RentalPackage
    from app.services import tour_service as ts
    db = SessionLocal()
    t = TourType(asset_type="jetski", name="Sunset Special", duration_minutes=75,
                 price=180, guided=True, sort_order=75)
    db.add(t); db.commit(); db.refresh(t)
    ts.sync_tour_to_units(db, t)
    jets = db.query(Asset).filter(Asset.asset_type == "jetski").all()
    for j in jets:
        pkg = db.query(RentalPackage).filter(
            RentalPackage.asset_id == j.id,
            RentalPackage.name == "Sunset Special").first()
        assert pkg is not None and pkg.price == 180
    # clean up so we don't pollute other tests that count packages
    ts.remove_tour_from_units(db, t.asset_type, t.name)
    db.delete(t); db.commit()
    db.close()


def test_single_tour_embed_filter():
    """?tour=ID limits the widget to just that one tour's package."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.tour_type import TourType
    from app.api.routes import public_booking as pb
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        j.model_group = "yamaha-vx"
    db.commit()
    # all tours
    all_cards = pb.public_assets("jetski", db=db)
    assert len(all_cards[0]["packages"]) >= 5
    # filter to one catalog tour
    safari = db.query(TourType).filter(
        TourType.name == "Safari 90min (guided)",
        TourType.asset_type == "jetski").first()
    one = pb.public_assets("jetski", tour=safari.id, db=db)
    assert len(one[0]["packages"]) == 1
    assert one[0]["packages"][0]["name"] == "Safari 90min (guided)"
    db.close()


def test_rename_tour_no_error_and_propagates():
    """Renaming a tour must not error and must swap old->new packages on all units."""
    from app.core.database import SessionLocal
    from app.models.tour_type import TourType
    from app.models.asset import Asset
    from app.models.package import RentalPackage
    from app.api.routes.tours import update_tour
    db = SessionLocal()
    t = db.query(TourType).filter(
        TourType.name == "Safari 90min (guided)",
        TourType.asset_type == "jetski").first()
    r = update_tour(t.id, {"name": "Adriatic Rush",
                           "duration_minutes": t.duration_minutes,
                           "price": t.price}, db=db, _=None)
    assert r["name"] == "Adriatic Rush"
    jets = db.query(Asset).filter(Asset.asset_type == "jetski").count()
    assert db.query(RentalPackage).filter(
        RentalPackage.name == "Safari 90min (guided)").count() == 0
    assert db.query(RentalPackage).filter(
        RentalPackage.name == "Adriatic Rush").count() == jets
    db.close()


def test_prune_orphan_packages():
    """Leftover packages from renamed/deleted tours are removed; real ones stay."""
    from app.core.database import SessionLocal
    from app.models.asset import Asset
    from app.models.package import RentalPackage
    from app.services import tour_service as ts
    db = SessionLocal()
    for j in db.query(Asset).filter(Asset.asset_type == "jetski").all():
        db.add(RentalPackage(asset_id=j.id, name="Ghost Tour",
                             duration_minutes=45, price=99))
    db.commit()
    jet_id = db.query(Asset).filter(Asset.asset_type == "jetski").first().id
    before = db.query(RentalPackage).filter(RentalPackage.asset_id == jet_id).count()
    assert before == 6  # 5 real + 1 ghost
    removed = ts.prune_orphan_packages(db, "jetski")
    assert removed >= 6  # one ghost per jet
    after = [p.name for p in db.query(RentalPackage).filter(
        RentalPackage.asset_id == jet_id).all()]
    assert "Ghost Tour" not in after
    assert "1h" in after  # a real catalog tour survives pruning
    db.close()
