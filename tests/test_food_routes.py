"""Food row CRUD over HTTP, auth-gated."""

import secrets
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth, db


def _mint_session(dbp, *, user_id: int = 1) -> str:
    sid = secrets.token_urlsafe(32)
    with db.connect(dbp) as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (sid, user_id,
             datetime.now(timezone.utc).isoformat(),
             datetime.fromtimestamp(time.time() + 3600,
                                    tz=timezone.utc).isoformat()),
        )
    return sid


@pytest.fixture
def setup(tmp_path, monkeypatch):
    dbp = tmp_path / "x.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="editor", path=dbp)
    sid = _mint_session(dbp, user_id=1)
    client = TestClient(app, cookies={"cp_session": sid})
    return client


def test_get_food_empty(setup):
    r = setup.get("/api/trips/t/food")
    assert r.status_code == 200
    assert r.json() == {"rows": []}


def test_post_food_creates_row(setup):
    r = setup.post("/api/trips/t/food", json={
        "day_index": 1, "meal": "dinner", "item": "Pasta",
        "assigned_to": "Alex", "notes": "", "sort_order": 1.0,
    })
    assert r.status_code == 200
    assert r.json()["row"]["item"] == "Pasta"


def test_put_food_with_stale_timestamp_409(setup):
    r = setup.post("/api/trips/t/food", json={
        "day_index": 1, "meal": "dinner", "item": "Pasta",
        "assigned_to": "", "notes": "", "sort_order": 1.0,
    })
    row = r.json()["row"]
    # First update
    setup.put(f"/api/trips/t/food/{row['id']}", json={
        "expected_updated_at": row["updated_at"],
        "item": "Risotto",
    })
    # Stale update — reuses the original timestamp, must 409
    r2 = setup.put(f"/api/trips/t/food/{row['id']}", json={
        "expected_updated_at": row["updated_at"],
        "item": "Pizza",
    })
    assert r2.status_code == 409
    assert r2.json()["current"]["item"] == "Risotto"


def test_delete_food_removes_row(setup):
    r = setup.post("/api/trips/t/food", json={
        "day_index": 1, "meal": "dinner", "item": "Pasta",
        "assigned_to": "", "notes": "", "sort_order": 1.0,
    })
    rid = r.json()["row"]["id"]
    d = setup.delete(f"/api/trips/t/food/{rid}")
    assert d.status_code == 200
    assert d.json() == {"ok": True}
    assert setup.get("/api/trips/t/food").json() == {"rows": []}


def test_non_member_gets_403(tmp_path, monkeypatch):
    dbp = tmp_path / "y.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    auth.upsert_user("ghost@example.com", path=dbp)
    sid = _mint_session(dbp, user_id=1)
    client = TestClient(app, cookies={"cp_session": sid})
    assert client.get("/api/trips/t/food").status_code == 403


def test_no_session_gets_401(tmp_path, monkeypatch):
    dbp = tmp_path / "z.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    client = TestClient(app)
    assert client.get("/api/trips/t/food").status_code == 401
