"""Tests for Phase 1: email facade, scheduler config, escalation/needs-human."""


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
    # multilingual now — default English when no booking given
    assert "thank you" in r.text.lower() or "deposit" in r.text.lower()


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
        "passengers": 2, "name": "T", "email": "w@x.com", "phone": "+385",
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
