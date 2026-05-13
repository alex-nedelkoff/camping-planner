"""HTTP tests for the waypoint editor endpoints."""

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
            (
                sid, user_id,
                datetime.now(timezone.utc).isoformat(),
                datetime.fromtimestamp(time.time() + 3600, tz=timezone.utc).isoformat(),
            ),
        )
    return sid


@pytest.fixture
def setup(tmp_path, monkeypatch):
    dbp = tmp_path / "x.sqlite3"
    trips = tmp_path / "trips"
    trips.mkdir()
    (trips / "t").mkdir()
    (trips / "t" / "trip.md").write_text(
        "---\npark: killarney\nstart_date: 2026-05-15\n---\n"
    )
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    monkeypatch.setattr("app.config.TRIPS_DIR", trips)
    monkeypatch.setattr("app.routes.route_editor.TRIPS_DIR", trips)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="editor", path=dbp)
    sid = _mint_session(dbp, user_id=1)
    client = TestClient(app, cookies={"cp_session": sid})
    return client, trips


def test_get_route_returns_empty_for_new_trip(setup):
    client, _ = setup
    r = client.get("/api/trips/t/route")
    assert r.status_code == 200
    assert r.json() == {"waypoints": [], "total_km": 0.0}


def test_post_route_persists_and_returns_distance(setup):
    client, trips = setup
    payload = {"waypoints": [
        {"lat": 46.0136, "lon": -81.4049, "name": "George Lake put-in"},
        {"lat": 46.0850, "lon": -81.4150, "name": "Killarney Lake centre"},
    ]}
    r = client.post("/api/trips/t/route", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["saved"] == 2
    assert 7.5 < body["total_km"] < 9.0

    gpx = (trips / "t" / "route.gpx").read_text()
    assert "George Lake put-in" in gpx
    assert "<trk>" in gpx and "<trkpt" in gpx


def test_get_route_after_post_round_trips(setup):
    client, _ = setup
    client.post("/api/trips/t/route", json={"waypoints": [
        {"lat": 46.0, "lon": -81.0, "name": "A"},
        {"lat": 46.05, "lon": -81.05, "name": "B"},
    ]})
    r = client.get("/api/trips/t/route")
    assert r.status_code == 200
    body = r.json()
    assert [w["name"] for w in body["waypoints"]] == ["A", "B"]


def test_post_with_empty_waypoints_writes_empty_gpx(setup):
    client, trips = setup
    r = client.post("/api/trips/t/route", json={"waypoints": []})
    assert r.status_code == 200
    assert r.json()["saved"] == 0
    assert (trips / "t" / "route.gpx").exists()
    # No <trk> when there are 0–1 points.
    assert "<trk>" not in (trips / "t" / "route.gpx").read_text()


def test_editor_page_renders_for_member(setup):
    client, _ = setup
    r = client.get("/trips/t/route-edit")
    assert r.status_code == 200, r.text
    html = r.text
    assert "Route editor" in html
    # Seed JSON is server-rendered.
    assert "const INITIAL = []" in html
    # Centre comes from killarney via park-key lookup.
    assert "46.01" in html and "-81.4" in html


def test_editor_page_seeds_existing_waypoints(setup):
    client, trips = setup
    # Pre-seed a route.gpx as if we had saved earlier.
    from app.services import route_gpx
    route_gpx.save_waypoints(trips / "t", [
        {"lat": 46.10, "lon": -81.30, "name": "Pre-existing"},
    ])
    r = client.get("/trips/t/route-edit")
    assert r.status_code == 200
    assert "Pre-existing" in r.text


def test_endpoints_404_for_unknown_trip(setup):
    client, _ = setup
    # Membership for "missing" needs to exist or we'd hit 403 first — add it.
    from app.services import auth as _auth
    import app.services.db as _db
    dbp = _db.DATABASE_PATH
    _auth.add_trip_member("missing", "alex@example.com", role="editor", path=dbp)
    r = client.get("/api/trips/missing/route")
    assert r.status_code == 404


def test_endpoints_403_for_non_member(setup, tmp_path, monkeypatch):
    client, trips = setup
    # New trip dir + a second user who is not a member.
    (trips / "u").mkdir()
    (trips / "u" / "trip.md").write_text("---\npark: killarney\n---\n")
    import app.services.db as _db
    auth.upsert_user("bob@example.com", path=_db.DATABASE_PATH)
    sid = _mint_session(_db.DATABASE_PATH, user_id=2)
    bob = TestClient(app, cookies={"cp_session": sid})
    r = bob.get("/api/trips/u/route")
    assert r.status_code == 403


def test_endpoints_401_when_anonymous(setup):
    _, _ = setup
    anon = TestClient(app)
    r = anon.get("/api/trips/t/route")
    assert r.status_code == 401
    r2 = anon.get("/trips/t/route-edit")
    assert r2.status_code == 401
