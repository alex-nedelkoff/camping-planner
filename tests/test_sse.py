"""SSE stream + presence broadcast."""

import json
import secrets
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth, db


@pytest.fixture
def authed_client(tmp_path, monkeypatch):
    dbp = tmp_path / "s.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="editor", path=dbp)
    sid = secrets.token_urlsafe(32)
    with db.connect(dbp) as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, 1, ?, ?)",
            (
                sid,
                datetime.now(timezone.utc).isoformat(),
                datetime.fromtimestamp(
                    time.time() + 3600, tz=timezone.utc
                ).isoformat(),
            ),
        )
    return TestClient(app, cookies={"cp_session": sid})


def test_sse_unauthenticated_returns_401(tmp_path, monkeypatch):
    dbp = tmp_path / "u.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    client = TestClient(app)
    r = client.get("/trips/t/events")
    assert r.status_code in (401, 403)


@pytest.mark.skip(reason="enabled by Task 11 broadcast wiring")
def test_sse_receives_a_published_event(authed_client):
    # Publish before connecting won't reach the stream — publish from a
    # background task after the stream is open.
    with authed_client.stream("GET", "/trips/t/events") as r:
        assert r.status_code == 200
        # Trigger an event by posting a food row in another request
        authed_client.post(
            "/api/trips/t/food",
            json={
                "day_index": 1,
                "meal": "dinner",
                "item": "Pasta",
                "assigned_to": "",
                "notes": "",
                "sort_order": 1.0,
            },
        )
        # Read one event line group from the stream (data: {...}\n\n)
        chunks = []
        for line in r.iter_lines():
            chunks.append(line)
            if len(chunks) > 10:
                break
            # Stop once we see a data: line
            if line.startswith("data:"):
                break
        data_line = next(c for c in chunks if c.startswith("data:"))
        payload = json.loads(data_line[len("data:") :].strip())
        assert payload["type"] == "food.upsert"
        assert payload["row"]["item"] == "Pasta"
