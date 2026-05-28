import time

import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.main import app
from app.services import comments, db, identity
from app.services.identity import User

SLUG = "balsam-lake-2026-05"


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Isolated SQLite + filesystem trip so _ensure_trip passes."""
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "c.sqlite3")
    db.init_schema()
    from app.services import trips as trips_svc
    trips_svc.create_trip_v2("balsam-lake", "2026-05-30", "2026-05-31", [], owner_id="o")
    return comments


def _as(monkeypatch, name):
    monkeypatch.setattr(identity, "current_user",
                        lambda req, n=name: User(n, n) if n else None)


# ---- storage unit tests ----------------------------------------------------

def test_create_and_list_chronological(store):
    store.create(SLUG, "Alex", "first")
    time.sleep(0.01)
    store.create(SLUG, "Sam", "second")
    got = store.list_for(SLUG)
    assert [c.body for c in got] == ["first", "second"]
    assert got[0].author == "Alex"


def test_list_is_per_trip(store):
    store.create(SLUG, "Alex", "here")
    assert store.list_for("other-trip") == []


def test_empty_body_rejected(store):
    with pytest.raises(comments.CommentError):
        store.create(SLUG, "Alex", "   ")


def test_too_long_rejected(store):
    with pytest.raises(comments.CommentError):
        store.create(SLUG, "Alex", "x" * (comments.MAX_COMMENT_LEN + 1))


def test_get_and_delete(store):
    c = store.create(SLUG, "Alex", "bye")
    assert store.get(c.id).body == "bye"
    store.delete(c.id)
    assert store.get(c.id) is None


# ---- route / authz tests ---------------------------------------------------

def test_anonymous_401(store, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, None)
    c = TestClient(app)
    assert c.get(f"/api/trips/{SLUG}/comments").status_code == 401


def test_unknown_trip_404(store, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    assert c.get("/api/trips/nope-trip/comments").status_code == 404


def test_post_then_list_with_mine_flag(store, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    r = c.post(f"/api/trips/{SLUG}/comments", json={"body": "bring the tarp"})
    assert r.status_code == 200 and r.json()["comment"]["mine"] is True
    # Jeff sees Alex's comment but not as his own
    _as(monkeypatch, "Jeff")
    items = c.get(f"/api/trips/{SLUG}/comments").json()["comments"]
    assert len(items) == 1 and items[0]["author"] == "Alex" and items[0]["mine"] is False


def test_whitespace_body_400(store, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    assert c.post(f"/api/trips/{SLUG}/comments", json={"body": "   "}).status_code == 400


def test_delete_own_vs_others(store, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    cid = c.post(f"/api/trips/{SLUG}/comments", json={"body": "mine"}).json()["comment"]["id"]
    _as(monkeypatch, "Jeff")
    assert c.delete(f"/api/trips/{SLUG}/comments/{cid}").status_code == 403
    _as(monkeypatch, "Alex")
    assert c.delete(f"/api/trips/{SLUG}/comments/{cid}").status_code == 200
    assert comments.get(cid) is None
