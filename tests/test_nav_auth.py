from fastapi.testclient import TestClient
from app.main import app


def test_nav_shows_logout_when_logged_in():
    c = TestClient(app)  # AUTH off → synthetic local user present
    r = c.get("/")
    assert "Log out" in r.text or "logout" in r.text.lower()


def test_whoami_routes_removed():
    c = TestClient(app)
    assert c.get("/api/whoami").status_code == 404
