from fastapi.testclient import TestClient
from app import config
from app.main import app


def test_pages_redirect_to_login_when_anon(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    c = TestClient(app)
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (302, 303) and "/login" in r.headers.get("location", "")


def test_api_401_when_anon(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    c = TestClient(app)
    r = c.get("/api/trips")
    assert r.status_code == 401


def test_login_page_open_when_anon(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    c = TestClient(app)
    assert c.get("/login").status_code == 200


def test_all_open_when_auth_disabled():
    c = TestClient(app)  # AUTH_ENABLED default off
    assert c.get("/", follow_redirects=False).status_code == 200
