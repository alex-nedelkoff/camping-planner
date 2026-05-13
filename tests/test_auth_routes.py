"""End-to-end auth flow via TestClient + fake mailer."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import db, mailer


@pytest.fixture
def client(tmp_path, monkeypatch):
    dbp = tmp_path / "ax.sqlite3"
    monkeypatch.setattr("app.services.auth.db.DATABASE_PATH", dbp)
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    sent = []

    async def fake_send(*, to, subject, html):
        sent.append({"to": to, "html": html})

    # Reset any cached default transport so our fake wins.
    monkeypatch.setattr(mailer, "_DEFAULT", None)
    # staticmethod prevents Python's descriptor protocol from binding `self`
    # since fake_send is keyword-only.
    monkeypatch.setattr(
        mailer, "default_transport",
        lambda: type("FT", (), {"send": staticmethod(fake_send)})(),
    )
    c = TestClient(app)
    c._sent = sent  # type: ignore[attr-defined]
    return c


def test_login_post_issues_link_and_emails(client):
    r = client.post("/login", data={"email": "alex@example.com"})
    assert r.status_code == 200
    assert "check your email" in r.text.lower()
    assert len(client._sent) == 1  # type: ignore[attr-defined]
    assert "token=" in client._sent[0]["html"]  # type: ignore


def test_verify_with_valid_token_sets_session_cookie(client):
    client.post("/login", data={"email": "alex@example.com"})
    html = client._sent[0]["html"]  # type: ignore
    token = html.split("token=")[1].split('"')[0]
    r = client.get(f"/login/verify?token={token}", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "cp_session" in r.cookies


def test_verify_with_bad_token_returns_400(client):
    r = client.get("/login/verify?token=garbage", follow_redirects=False)
    assert r.status_code == 400


def test_logout_clears_session(client):
    client.post("/login", data={"email": "alex@example.com"})
    token = client._sent[0]["html"].split("token=")[1].split('"')[0]  # type: ignore
    client.get(f"/login/verify?token={token}", follow_redirects=False)
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code in (200, 302, 303)
    cookie_header = r.headers.get("set-cookie", "")
    assert "cp_session=" in cookie_header
