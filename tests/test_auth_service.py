import pytest
from app import config
from app.services import auth


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status; self._p = payload
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=None)


def test_send_magic_link_posts_otp(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_ANON_KEY", "anon")
    calls = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        calls["url"] = url; calls["json"] = json; calls["headers"] = headers
        return _Resp(200, {})
    monkeypatch.setattr(auth.httpx, "post", fake_post)
    auth.send_magic_link("a@b.c", "https://app/auth/callback")
    assert calls["url"].endswith("/auth/v1/otp")
    assert calls["json"]["email"] == "a@b.c"
    assert calls["json"]["options"]["email_redirect_to"] == "https://app/auth/callback"
    assert calls["headers"]["apikey"] == "anon"


def test_verify_token_hash_returns_session(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(auth.httpx, "post",
        lambda url, json=None, headers=None, timeout=None:
            _Resp(200, {"access_token": "AT", "refresh_token": "RT"}))
    s = auth.verify_token_hash("hash", "magiclink")
    assert s["access_token"] == "AT" and s["refresh_token"] == "RT"
