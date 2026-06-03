def _setup(client, auth):
    """Create a customer and pick a boat + one of its packages."""
    cust = client.post("/api/customers", headers=auth, json={
        "full_name": "Booker", "email": "b@e.com", "phone": "+200"}).json()
    av = client.post("/api/availability", headers=auth, json={
        "asset_type": "boat", "passengers": 4,
        "start_datetime": "2031-01-01T09:00:00+00:00",
        "end_datetime": "2031-01-01T13:00:00+00:00"}).json()
    asset = av[0]
    # choose the "4h" package
    pkg = next(p for p in asset["packages"] if p["name"] == "4h")
    return cust, asset["asset_id"], pkg["package_id"]


def test_create_with_package_and_no_overlap(client, auth):
    cust, aid, pid = _setup(client, auth)
    b = client.post("/api/bookings", headers=auth, json={
        "asset_id": aid, "customer_id": cust["id"], "package_id": pid,
        "start_datetime": "2031-01-01T09:00:00+00:00",
        "end_datetime": "2031-01-01T13:00:00+00:00", "source": "admin"})
    assert b.status_code == 200
    body = b.json()
    assert body["status"] == "pending"
    assert body["total_price"] > 0
    # deposit must be 30% of total
    assert abs(body["deposit_amount"] - body["total_price"] * 0.30) < 0.01

    # overlapping booking must be rejected (Rule 2)
    b2 = client.post("/api/bookings", headers=auth, json={
        "asset_id": aid, "customer_id": cust["id"], "package_id": pid,
        "start_datetime": "2031-01-01T10:00:00+00:00",
        "end_datetime": "2031-01-01T12:00:00+00:00", "source": "admin"})
    assert b2.status_code == 409


def test_confirm_and_cancel(client, auth):
    cust, aid, pid = _setup(client, auth)
    b = client.post("/api/bookings", headers=auth, json={
        "asset_id": aid, "customer_id": cust["id"], "package_id": pid,
        "start_datetime": "2032-02-01T09:00:00+00:00",
        "end_datetime": "2032-02-01T13:00:00+00:00", "source": "admin"}).json()
    bid = b["id"]
    cf = client.post(f"/api/bookings/{bid}/confirm", headers=auth)
    assert cf.json()["status"] == "confirmed"
    cn = client.post(f"/api/bookings/{bid}/cancel", headers=auth)
    assert cn.json()["status"] == "cancelled"

    # after cancel, the slot frees up
    b3 = client.post("/api/bookings", headers=auth, json={
        "asset_id": aid, "customer_id": cust["id"], "package_id": pid,
        "start_datetime": "2032-02-01T09:00:00+00:00",
        "end_datetime": "2032-02-01T13:00:00+00:00", "source": "admin"})
    assert b3.status_code == 200


def test_invalid_time_range(client, auth):
    cust, aid, pid = _setup(client, auth)
    b = client.post("/api/bookings", headers=auth, json={
        "asset_id": aid, "customer_id": cust["id"], "package_id": pid,
        "start_datetime": "2033-01-01T17:00:00+00:00",
        "end_datetime": "2033-01-01T09:00:00+00:00", "source": "admin"})
    assert b.status_code == 400


def test_wrong_package_rejected(client, auth):
    """A package from another asset must not be accepted."""
    cust, aid, pid = _setup(client, auth)
    # find a package belonging to a different asset
    other = client.post("/api/availability", headers=auth, json={
        "asset_type": "jetski", "passengers": 1,
        "start_datetime": "2034-01-01T09:00:00+00:00",
        "end_datetime": "2034-01-01T10:00:00+00:00"}).json()
    wrong_pid = other[0]["packages"][0]["package_id"]
    b = client.post("/api/bookings", headers=auth, json={
        "asset_id": aid, "customer_id": cust["id"], "package_id": wrong_pid,
        "start_datetime": "2034-02-01T09:00:00+00:00",
        "end_datetime": "2034-02-01T13:00:00+00:00", "source": "admin"})
    assert b.status_code == 400
