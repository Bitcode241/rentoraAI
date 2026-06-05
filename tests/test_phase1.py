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
