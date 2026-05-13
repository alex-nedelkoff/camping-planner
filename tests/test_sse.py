"""SSE stream + presence broadcast."""

import secrets
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth, broadcast, db


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


def test_sse_receives_a_published_event(authed_client, monkeypatch):
    # We can't drive end-to-end SSE through TestClient: httpx.ASGITransport
    # buffers every http.response.body chunk and only returns once the response
    # is complete (see httpx/_transports/asgi.py). EventSourceResponse never
    # completes, so client.stream(...) hangs at __enter__. Subscribing to the
    # bus from the test loop doesn't help either — asyncio.Queue waiters are
    # bound to the loop that called get(), and the publish runs on TestClient's
    # portal loop.
    #
    # So we capture publish() calls directly and verify the food route wires
    # the broadcast correctly. End-to-end SSE delivery is exercised by hand
    # against a running uvicorn process.
    captured: list[tuple[str, dict]] = []
    real_publish = broadcast.default_bus.publish

    async def capture(channel, event):
        captured.append((channel, event))
        await real_publish(channel, event)

    monkeypatch.setattr(broadcast.default_bus, "publish", capture)

    r = authed_client.post(
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
    assert r.status_code == 200
    food_events = [
        (ch, ev) for ch, ev in captured if ev.get("type") == "food.upsert"
    ]
    assert food_events, f"no food.upsert event published; saw {captured!r}"
    channel, event = food_events[0]
    assert channel == "t"
    assert event["row"]["item"] == "Pasta"
