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
