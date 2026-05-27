"""FastAPI route tests using TestClient.

Trip filesystem operations are redirected to a tmp dir via monkeypatch.
The Camis availability call is mocked — never hit Ontario Parks from tests.
"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import availability as availability_svc
from app.services import db
from app.services import trips as trips_svc

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with TRIPS_DIR and the SQLite DB redirected to tmp_path."""
    tmp_trips = tmp_path / "trips"
    if (REPO_ROOT / "trips").exists():
        shutil.copytree(REPO_ROOT / "trips", tmp_trips)
    else:
        tmp_trips.mkdir()
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)

    tmp_db = tmp_path / "test.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)

    yield TestClient(app)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Camping Trips" in r.text




# ---------------------------------------------------------------------------
# GET /api/availability  (mocked — no live Camis hits)
# ---------------------------------------------------------------------------


def test_availability_returns_shaped_payload(client, monkeypatch):
    def fake_check(park, start, end):
        return {
            "park_name": "Killarney Provincial Park",
            "total_available": 3,
            "campgrounds": {
                "George Lake": {"available": 2, "total": 50},
                "Bell Lake": {"available": 1, "total": 25},
            },
        }

    monkeypatch.setattr(availability_svc, "check", fake_check)
    r = client.get(
        "/api/availability",
        params={"park": "killarney", "start": "2027-07-10", "end": "2027-07-12"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["park_name"] == "Killarney Provincial Park"
    assert body["total_available"] == 3
    assert body["campgrounds"]["George Lake"]["available"] == 2


def test_availability_validates_missing_params(client):
    r = client.get("/api/availability", params={"park": "killarney"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Availability cache (TTL'd JSON-blob; backs /api/availability)
# ---------------------------------------------------------------------------


def test_availability_cache_skips_second_upstream_call(client, monkeypatch):
    """ontario_parks.check_park is called once; the second hit is served from SQLite."""
    import ontario_parks

    calls = {"n": 0}

    def fake_check_park(park, start, end):
        calls["n"] += 1
        return {
            "park_name": "Killarney",
            "total_available": 1,
            "campgrounds": {},
        }

    monkeypatch.setattr(ontario_parks, "check_park", fake_check_park)

    params = {"park": "killarney", "start": "2027-07-10", "end": "2027-07-12"}
    first = client.get("/api/availability", params=params)
    second = client.get("/api/availability", params=params)
    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["n"] == 1
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True


# ---------------------------------------------------------------------------
# Checklist sync
# ---------------------------------------------------------------------------


def test_checklist_get_starts_empty(client):
    r = client.get("/api/checklist", params={"trip": "killarney-2026-05"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "state": {}}


def test_checklist_post_then_get_round_trip(client):
    slug = "killarney-2026-05"
    r = client.post(
        "/api/checklist",
        params={"trip": slug},
        json={"key": "gear--canoe", "checked": True},
    )
    assert r.status_code == 200, r.text
    r2 = client.get("/api/checklist", params={"trip": slug})
    assert r2.json()["state"] == {"gear--canoe": True}


def test_checklist_post_overwrites(client):
    slug = "killarney-2026-05"
    client.post(
        "/api/checklist",
        params={"trip": slug},
        json={"key": "gear--tent", "checked": True},
    )
    client.post(
        "/api/checklist",
        params={"trip": slug},
        json={"key": "gear--tent", "checked": False},
    )
    state = client.get("/api/checklist", params={"trip": slug}).json()["state"]
    assert state == {"gear--tent": False}


def test_checklist_unknown_trip_returns_404(client):
    r = client.get("/api/checklist", params={"trip": "no-such-trip"})
    assert r.status_code == 404
    r2 = client.post(
        "/api/checklist",
        params={"trip": "no-such-trip"},
        json={"key": "k", "checked": True},
    )
    assert r2.status_code == 404


def test_checklist_validates_missing_key(client):
    r = client.post(
        "/api/checklist",
        params={"trip": "killarney-2026-05"},
        json={"checked": True},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Identity: cookie-based whoami (Phase 3)
# ---------------------------------------------------------------------------


def test_whoami_starts_empty(client):
    r = client.get("/api/whoami")
    assert r.status_code == 200
    assert r.json() == {"user": ""}


def test_whoami_post_sets_cookie_and_persists(client):
    r = client.post("/api/whoami", json={"user": "Alex"})
    assert r.status_code == 200, r.text
    assert r.json() == {"user": "Alex"}
    # Cookie persists on the same TestClient instance
    assert client.get("/api/whoami").json() == {"user": "Alex"}


def test_whoami_rejects_bad_chars(client):
    r = client.post("/api/whoami", json={"user": "<script>"})
    assert r.status_code == 400


def test_whoami_delete_clears(client):
    client.post("/api/whoami", json={"user": "Alex"})
    r = client.delete("/api/whoami")
    assert r.status_code == 200
    assert client.get("/api/whoami").json() == {"user": ""}


# ---------------------------------------------------------------------------
# Per-user checklist (cookie-driven)
# ---------------------------------------------------------------------------


def test_checklist_isolated_by_cookie(client):
    """Two TestClients = two cookie jars; their checklists must not collide."""
    from fastapi.testclient import TestClient
    alex = client                       # already-bound to fixture
    jordan = TestClient(app)            # fresh cookie jar, same app + DB

    slug = "killarney-2026-05"
    alex.post("/api/whoami", json={"user": "Alex"})
    jordan.post("/api/whoami", json={"user": "Jordan"})

    alex.post(
        "/api/checklist", params={"trip": slug},
        json={"key": "packing--tent", "checked": True},
    )
    jordan.post(
        "/api/checklist", params={"trip": slug},
        json={"key": "packing--tent", "checked": False},
    )

    assert alex.get("/api/checklist", params={"trip": slug}).json()["state"] == {
        "packing--tent": True,
    }
    assert jordan.get("/api/checklist", params={"trip": slug}).json()["state"] == {
        "packing--tent": False,
    }


def test_checklist_no_cookie_uses_shared_bucket(client):
    """A request with no whoami cookie reads/writes the shared (user='') row."""
    slug = "killarney-2026-05"
    client.post(
        "/api/checklist", params={"trip": slug},
        json={"key": "packing--tarp", "checked": True},
    )
    # After identifying as Alex, the shared write is no longer visible
    client.post("/api/whoami", json={"user": "Alex"})
    assert client.get("/api/checklist", params={"trip": slug}).json()["state"] == {}
