def test_fleet_seeded(client, auth):
    a = client.get("/api/assets", headers=auth).json()
    types = {x["asset_type"] for x in a}
    # Real fleet: boats + jet skis only (vehicles are transfer-only).
    assert {"boat", "jetski"}.issubset(types)
    assert len([x for x in a if x["asset_type"] == "boat"]) == 6
    assert len([x for x in a if x["asset_type"] == "jetski"]) == 6


def test_filter_by_type(client, auth):
    boats = client.get("/api/assets?asset_type=boat", headers=auth).json()
    assert all(b["asset_type"] == "boat" for b in boats)
    assert len(boats) == 6


def test_assets_have_packages(client, auth):
    a = client.get("/api/assets?asset_type=boat", headers=auth).json()
    # every boat has 3 packages: 4h, 8h, sunset
    for boat in a:
        names = {p["name"] for p in boat["packages"]}
        assert "4h" in names and "8h" in names
        assert any("Sunset" in n for n in names)


def test_deposit_is_percent(client, auth):
    a = client.get("/api/assets?asset_type=boat", headers=auth).json()
    assert all(x["deposit_percent"] == 30.0 for x in a)
