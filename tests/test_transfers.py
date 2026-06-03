from app.services import transfer_service as t


class FakeZone:
    def __init__(self, car, van, name="Test"):
        self.name = name
        self.car_price = car
        self.van_price = van


def test_vehicle_plan():
    assert t.plan_vehicles(1) == {"vans": 0, "cars": 1}
    assert t.plan_vehicles(3) == {"vans": 0, "cars": 1}
    assert t.plan_vehicles(4) == {"vans": 1, "cars": 0}
    assert t.plan_vehicles(8) == {"vans": 1, "cars": 0}
    assert t.plan_vehicles(10) == {"vans": 1, "cars": 1}
    assert t.plan_vehicles(12) == {"vans": 2, "cars": 0}
    assert t.plan_vehicles(17) == {"vans": 2, "cars": 1}


def test_one_way_and_round_trip():
    z = FakeZone(car=55, van=75, name="Airport")
    q1 = t.quote_transfer(z, 2, round_trip=False)
    assert q1["total_price"] == 55.0
    q2 = t.quote_transfer(z, 2, round_trip=True)
    assert q2["total_price"] == 110.0


def test_van_plus_car_for_large_group():
    z = FakeZone(car=55, van=75, name="Airport")
    q = t.quote_transfer(z, 10, round_trip=False)
    assert q["vehicles"] == {"vans": 1, "cars": 1}
    assert q["total_price"] == 130.0   # 75 + 55


def test_zone_api_and_quote(client, auth):
    zones = client.get("/api/transfers/zones", headers=auth).json()
    assert len(zones) >= 4
    names = {z["name"] for z in zones}
    assert any("Dubrovnik" in n for n in names)

    q = client.get("/api/transfers/quote", headers=auth,
                   params={"location": "Sheraton", "passengers": 5}).json()
    assert q["total_price"] == 45.0   # van price for Sheraton

    unknown = client.get("/api/transfers/quote", headers=auth,
                         params={"location": "random villa", "passengers": 2}).json()
    assert unknown.get("error") == "unknown_location"


def test_ai_tool_dedupes_jetskis(client, auth):
    """The jet ski AI tool must collapse identical units into one offering."""
    from app.core.database import SessionLocal
    from app.ai import tools
    db = SessionLocal()
    res = tools.find_available_jetskis(db, 1, "2035-07-01T09:00:00+00:00",
                                       "2035-07-01T10:00:00+00:00")
    db.close()
    # one offering, with several units, not 6 separate entries
    assert len(res) == 1
    assert res[0]["available_units"] == 6
    assert len(res[0]["packages"]) == 5
