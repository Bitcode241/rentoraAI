import os
import tempfile
import pytest
from fastapi.testclient import TestClient

# Use an isolated temp DB per test session BEFORE importing the app.
_tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["OPENAI_API_KEY"] = ""  # force deterministic AI fallback

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth(client):
    r = client.post("/api/auth/login",
                    data={"username": "admin", "password": "admin123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session", autouse=True)
def seed_fleet_fixture(client):
    """Load the real fleet once for the whole test session."""
    from scripts.seed_fleet import seed_fleet
    seed_fleet(reset=False)
    yield
