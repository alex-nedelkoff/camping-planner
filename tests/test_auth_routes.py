from fastapi.testclient import TestClient
from app import config
from app.main import app
from app.services import auth, identity


def test_login_page_renders():
    c = TestClient(app)
    r = c.get("/login")
    assert r.status_code == 200 and "email" in r.text.lower()


def test_post_login_sends_magic_link(monkeypatch):
    sent = {}
    monkeypatch.setattr(auth, "send_magic_link", lambda email, redirect: sent.update(email=email))
    c = TestClient(app)
    r = c.post("/login", data={"email": "a@b.c"})
    assert r.status_code == 200 and sent["email"] == "a@b.c"


def test_callback_sets_cookies(monkeypatch):
    monkeypatch.setattr(auth, "verify_token_hash",
                        lambda token_hash, type_: {"access_token": "AT", "refresh_token": "RT"})
    c = TestClient(app)
    r = c.get("/auth/callback?token_hash=h&type=magiclink", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert identity.ACCESS_COOKIE in r.headers.get("set-cookie", "")


def test_logout_clears(monkeypatch):
    c = TestClient(app)
    r = c.post("/logout", follow_redirects=False)
    assert r.status_code in (302, 303)
