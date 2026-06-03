def test_reports_endpoints(client, auth):
    assert client.get("/api/reports/bookings", headers=auth).status_code == 200
    assert client.get("/api/reports/revenue", headers=auth).status_code == 200
    assert client.get("/api/reports/utilization", headers=auth).status_code == 200
    assert client.get("/api/reports/today", headers=auth).status_code == 200
    assert client.get("/api/reports/upcoming", headers=auth).status_code == 200


def test_ai_reply_fallback(client, auth):
    r = client.post("/api/messages/ai-reply", headers=auth, json={
        "channel": "admin", "message": "Do you have a boat for 7 people?"})
    assert r.status_code == 200
    # No OpenAI key in tests -> deterministic fallback escalates to human
    assert r.json()["needs_human"] is True
