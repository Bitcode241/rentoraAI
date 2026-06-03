def test_capacity_filter_rule1(client, auth):
    # Every returned boat must have capacity >= requested passengers.
    r = client.post("/api/availability", headers=auth, json={
        "asset_type": "boat", "passengers": 8,
        "start_datetime": "2030-07-01T09:00:00+00:00",
        "end_datetime": "2030-07-01T13:00:00+00:00"}).json()
    assert len(r) >= 1
    assert all(x["capacity"] >= 8 for x in r)


def test_high_capacity_request_narrows(client, auth):
    # Only the largest boats (capacity >= 11) qualify for 11 passengers.
    r = client.post("/api/availability", headers=auth, json={
        "asset_type": "boat", "passengers": 11,
        "start_datetime": "2030-07-01T09:00:00+00:00",
        "end_datetime": "2030-07-01T13:00:00+00:00"}).json()
    assert all(x["capacity"] >= 11 for x in r)


def test_packages_present(client, auth):
    r = client.post("/api/availability", headers=auth, json={
        "asset_type": "jetski", "passengers": 1,
        "start_datetime": "2030-08-01T09:00:00+00:00",
        "end_datetime": "2030-08-01T13:00:00+00:00"}).json()
    assert len(r) >= 1
    pkgs = r[0]["packages"]
    assert len(pkgs) == 5  # 30min, 1h, 2h, safari 90, safari 120
    assert all(p["price"] > 0 for p in pkgs)
    assert all(p["deposit_amount"] > 0 for p in pkgs)
