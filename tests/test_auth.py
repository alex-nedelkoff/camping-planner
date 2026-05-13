"""Magic-link issue/verify + session lifecycle."""

import time

import pytest

from app.services import auth, db


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "auth.sqlite3"
    db.init_schema(p)
    return p


def test_issue_magic_link_creates_unconsumed_row(dbpath):
    token = auth.issue_magic_link("alex@example.com", path=dbpath)
    assert len(token) >= 32
    with db.connect(dbpath) as conn:
        row = conn.execute(
            "SELECT email, consumed_at FROM magic_links WHERE token = ?",
            (token,),
        ).fetchone()
    assert row["email"] == "alex@example.com"
    assert row["consumed_at"] is None


def test_consume_magic_link_creates_user_and_session(dbpath):
    token = auth.issue_magic_link("alex@example.com", path=dbpath)
    session_id = auth.consume_magic_link(token, path=dbpath)
    assert session_id
    user = auth.user_for_session(session_id, path=dbpath)
    assert user["email"] == "alex@example.com"


def test_consume_magic_link_marks_consumed(dbpath):
    token = auth.issue_magic_link("alex@example.com", path=dbpath)
    auth.consume_magic_link(token, path=dbpath)
    with pytest.raises(auth.MagicLinkInvalid):
        auth.consume_magic_link(token, path=dbpath)


def test_expired_magic_link_rejected(dbpath, monkeypatch):
    token = auth.issue_magic_link("alex@example.com", path=dbpath)
    # Fast-forward past the 15-min expiry
    real = time.time
    monkeypatch.setattr(auth, "_now", lambda: real() + 16 * 60)
    with pytest.raises(auth.MagicLinkInvalid):
        auth.consume_magic_link(token, path=dbpath)


def test_user_for_unknown_session_returns_none(dbpath):
    assert auth.user_for_session("nope", path=dbpath) is None


def test_is_trip_member_false_for_non_member(dbpath):
    auth.upsert_user("alex@example.com", path=dbpath)
    assert not auth.is_trip_member(
        "killarney-2026-05", "alex@example.com", path=dbpath,
    )


def test_add_trip_member_then_check(dbpath):
    auth.upsert_user("alex@example.com", path=dbpath)
    auth.add_trip_member(
        "killarney-2026-05", "alex@example.com", role="owner", path=dbpath,
    )
    assert auth.is_trip_member(
        "killarney-2026-05", "alex@example.com", path=dbpath,
    )
