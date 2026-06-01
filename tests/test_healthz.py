from fastapi.testclient import TestClient
from app import config
from app.main import app


def test_healthz_ok():
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_healthz_head_ok():
    # UptimeRobot (and many uptime monitors) probe with HEAD by default; the
    # route must answer HEAD with 200, not 405, or the monitor reports "down".
    c = TestClient(app)
    r = c.head("/healthz")
    assert r.status_code == 200


def test_healthz_public_even_with_auth_on(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    c = TestClient(app)
    r = c.get("/healthz", follow_redirects=False)
    assert r.status_code == 200 and r.json() == {"status": "ok"}
