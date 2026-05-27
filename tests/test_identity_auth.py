import time
import jwt
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
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    assert identity.current_user(_req()) is None


def test_auth_enabled_valid_token(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    tok = jwt.encode({"sub": "uid-1", "email": "a@b.c", "aud": "authenticated",
                      "exp": int(time.time()) + 3600}, "secret", algorithm="HS256")
    u = identity.current_user(_req({"cp_at": tok}))
    assert u.id == "uid-1" and u.email == "a@b.c"


def test_auth_enabled_bad_token(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    assert identity.current_user(_req({"cp_at": "garbage"})) is None
