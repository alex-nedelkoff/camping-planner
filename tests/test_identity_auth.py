from app import config
from app.services import identity


def _req(cookies=None):
    class R:
        def __init__(self, c): self.cookies = c or {}
    return R(cookies)


def test_auth_disabled_returns_local_user(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    u = identity.current_user(_req())
    assert u is not None and u.id == "local"


def test_auth_enabled_no_cookie_is_none(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    assert identity.current_user(_req()) is None


def test_signed_cookie_round_trips(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SESSION_SECRET", "secret")
    token = identity.sign("Alex")
    u = identity.current_user(_req({identity.SESSION_COOKIE: token}))
    assert u.id == "Alex" and u.email == "Alex"


def test_tampered_username_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SESSION_SECRET", "secret")
    token = identity.sign("Alex")
    # swap the username half while keeping the old signature
    bad = identity._b64e(b"Mallory") + "." + token.split(".", 1)[1]
    assert identity.current_user(_req({identity.SESSION_COOKIE: bad})) is None


def test_wrong_secret_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SESSION_SECRET", "secret")
    token = identity.sign("Alex")
    monkeypatch.setattr(config, "SESSION_SECRET", "different")
    assert identity.current_user(_req({identity.SESSION_COOKIE: token})) is None


def test_garbage_cookie_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SESSION_SECRET", "secret")
    assert identity.current_user(_req({identity.SESSION_COOKIE: "garbage"})) is None
