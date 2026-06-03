def test_login_success(client):
    r = client.post("/api/auth/login",
                    data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_failure(client):
    r = client.post("/api/auth/login",
                    data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_protected_requires_token(client):
    assert client.get("/api/assets").status_code == 401


def test_staff_cannot_create_asset(client, auth):
    # create a staff user
    client.post("/api/auth/users", headers=auth, json={
        "username": "staff1", "password": "staffpass", "role": "staff"})
    tok = client.post("/api/auth/login",
                      data={"username": "staff1", "password": "staffpass"}).json()["access_token"]
    sh = {"Authorization": f"Bearer {tok}"}
    r = client.post("/api/assets", headers=sh, json={
        "name": "X", "asset_type": "boat", "capacity": 2})
    assert r.status_code == 403
