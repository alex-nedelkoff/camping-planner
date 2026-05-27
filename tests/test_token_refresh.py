import time, jwt
from fastapi.testclient import TestClient
from app import config
from app.main import app
from app.services import auth, identity


def test_expired_access_refreshes(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    # a fresh valid token the refresh() will "return"
    good = jwt.encode({"sub": "uid-7", "email": "g@h.i", "aud": "authenticated",
                       "exp": int(time.time()) + 3600}, "secret", algorithm="HS256")
    monkeypatch.setattr(auth, "refresh",
                        lambda rt: {"access_token": good, "refresh_token": "RT2"})
    c = TestClient(app)
    # no access cookie, but a refresh cookie present
    c.cookies.set(identity.REFRESH_COOKIE, "RT1")
    r = c.get("/api/trips")
    assert r.status_code == 200   # refreshed instead of 401


def test_no_refresh_cookie_401(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    c = TestClient(app)
    assert c.get("/api/trips").status_code == 401
