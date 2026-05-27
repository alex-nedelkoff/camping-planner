from fastapi.testclient import TestClient
from app import config
from app.main import app
from app.services import identity


def test_login_page_renders():
    c = TestClient(app)
    r = c.get("/login")
    assert r.status_code == 200
    assert "password" in r.text.lower() and "name" in r.text.lower()


def test_correct_password_sets_session(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SITE_PASSWORD", "letmein")
    monkeypatch.setattr(config, "SESSION_SECRET", "secret")
    c = TestClient(app)
    r = c.post("/login", data={"username": "Alex", "password": "letmein"},
               follow_redirects=False)
    assert r.status_code == 303
    cookie = r.headers.get("set-cookie", "")
    assert identity.SESSION_COOKIE in cookie
    assert identity.unsign(c.cookies.get(identity.SESSION_COOKIE)) == "Alex"


def test_wrong_password_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SITE_PASSWORD", "letmein")
    c = TestClient(app)
    r = c.post("/login", data={"username": "Alex", "password": "nope"},
               follow_redirects=False)
    assert r.status_code == 401
    assert identity.SESSION_COOKIE not in r.headers.get("set-cookie", "")


def test_blank_username_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SITE_PASSWORD", "letmein")
    c = TestClient(app)
    r = c.post("/login", data={"username": "   ", "password": "letmein"},
               follow_redirects=False)
    assert r.status_code == 400


def test_logout_clears(monkeypatch):
    c = TestClient(app)
    r = c.post("/logout", follow_redirects=False)
    assert r.status_code in (302, 303)
