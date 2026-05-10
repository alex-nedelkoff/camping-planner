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
from app.routes import checklist as checklist_route
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
    monkeypatch.setattr(checklist_route, "TRIPS_DIR", tmp_trips)

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
    # SPA shell ships an empty main pane; sidebar header is in the markup.
    assert "Trips" in r.text
    assert 'id="main-pane"' in r.text


def test_trip_slug_url_serves_shell(client):
    r = client.get("/trips/killarney-2026-05")
    assert r.status_code == 200
    assert 'id="main-pane"' in r.text


def test_trips_list_endpoint(client):
    r = client.get("/api/trips")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    names = [t["name"] for t in body["trips"]]
    assert "killarney-2026-05" in names


# ---------------------------------------------------------------------------
# POST /api/new-trip
# ---------------------------------------------------------------------------


def test_new_trip_creates_directory(client, tmp_path):
    r = client.post(
        "/api/new-trip",
        json={
            "park": "killarney",
            "start": "2027-08-10",
            "end": "2027-08-12",
            "participants": ["Alex", "Jordan"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["trip_dir"] == "killarney-2027-08"
    new_dir = trips_svc.TRIPS_DIR / "killarney-2027-08"
    assert new_dir.is_dir()
    assert (new_dir / "trip.md").exists()


def test_new_trip_rejects_duplicate(client):
    payload = {
        "park": "killarney",
        "start": "2027-09-10",
        "end": "2027-09-12",
        "participants": [],
    }
    first = client.post("/api/new-trip", json=payload)
    assert first.status_code == 200
    second = client.post("/api/new-trip", json=payload)
    assert second.status_code == 409


def test_new_trip_validates_missing_fields(client):
    r = client.post("/api/new-trip", json={"park": "killarney"})
    assert r.status_code == 422


def test_new_trip_validates_bad_date(client):
    r = client.post(
        "/api/new-trip",
        json={
            "park": "killarney",
            "start": "not-a-date",
            "end": "2027-08-12",
            "participants": [],
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/trip/<slug>
# ---------------------------------------------------------------------------


def test_get_trip_returns_payload(client):
    from unittest.mock import patch

    fake_weather = {
        "source": "forecast",
        "days": [{
            "date": "2026-05-15", "high": 18.0, "low": 5.0,
            "precip_mm": 0.0, "precip_chance": 10, "code": 1,
            "description": "Mainly clear", "icon": "☀️",
        }],
    }
    with patch("build_trip._weather.get_weather", return_value=fake_weather), \
         patch("build_trip._osm_data.load_killarney_features",
               side_effect=FileNotFoundError("no cache")):
        r = client.get("/api/trip/killarney-2026-05")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "killarney-2026-05"
    assert body["park_name"]
    assert "<header" in body["header_html"]
    section_ids = [s["id"] for s in body["sections"]]
    for required in ("intro", "itinerary", "gear", "food", "packing", "costs"):
        assert required in section_ids


def test_get_trip_missing_returns_404(client):
    r = client.get("/api/trip/no-such-trip")
    assert r.status_code == 404


def test_get_trip_costs_section_includes_per_person_summary(client):
    """The costs section's HTML carries the auto-computed total + per-person split."""
    from unittest.mock import patch

    fake_weather = {"source": "unavailable", "days": []}
    with patch("build_trip.weather_provider", return_value=fake_weather), \
         patch("build_trip._osm_data.load_killarney_features",
               side_effect=FileNotFoundError("no cache")):
        r = client.get("/api/trip/killarney-2026-05")
    assert r.status_code == 200, r.text
    body = r.json()
    costs = next(s for s in body["sections"] if s["id"] == "costs")
    # killarney trip: 99 + 400 + 122 = 621; 2 participants → 310.50
    assert "costs-summary" in costs["html"]
    assert "$621.00" in costs["html"]
    assert "$310.50" in costs["html"]


# ---------------------------------------------------------------------------
# POST /api/save-gear
# ---------------------------------------------------------------------------


def test_save_gear_missing_trip_returns_404(client):
    r = client.post(
        "/api/save-gear",
        params={"trip": "no-such-trip"},
        json={"rows": [["Tent", "Alex", ""]]},
    )
    assert r.status_code == 404


def test_save_gear_rejects_malformed_rows(client):
    r = client.post(
        "/api/save-gear",
        params={"trip": "no-such-trip"},
        json={"rows": "not a list"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/save-section-table — generic version of /api/save-gear
# ---------------------------------------------------------------------------


def test_save_section_table_works_for_costs(client):
    slug = "killarney-2026-05"
    new_rows = [
        ["Permit / reservation", "Alex", "70"],
        ["Gas", "Jordan", "120"],
    ]
    r = client.post(
        "/api/save-section-table",
        params={"trip": slug, "section": "costs"},
        json={"rows": new_rows},
    )
    assert r.status_code == 200, r.text
    md = client.get(
        "/api/section", params={"trip": slug, "section": "costs"},
    ).json()["markdown"]
    assert "Alex" in md and "70" in md
    assert "Jordan" in md and "120" in md
    # Total per person is no longer a stored markdown placeholder — it's
    # computed at render time in load_trip_payload.
    assert "**Total per person:**" not in md


def test_save_section_table_rejects_non_table_section(client):
    r = client.post(
        "/api/save-section-table",
        params={"trip": "killarney-2026-05", "section": "packing"},
        json={"rows": [["x"]]},
    )
    assert r.status_code == 400


def test_save_section_table_404_on_unknown_trip(client):
    r = client.post(
        "/api/save-section-table",
        params={"trip": "nope", "section": "gear"},
        json={"rows": [["x"]]},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/section + POST /api/save-section
# ---------------------------------------------------------------------------


def test_get_section_returns_raw_markdown(client):
    r = client.get(
        "/api/section",
        params={"trip": "killarney-2026-05", "section": "gear"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["section"] == "gear"
    assert "Item" in body["markdown"]


def test_get_intro_returns_body_after_frontmatter(client):
    r = client.get(
        "/api/section",
        params={"trip": "killarney-2026-05", "section": "intro"},
    )
    assert r.status_code == 200, r.text
    md = r.json()["markdown"]
    assert "---" not in md.splitlines()[:3]


def test_get_section_rejects_unknown_name(client):
    r = client.get(
        "/api/section",
        params={"trip": "killarney-2026-05", "section": "secrets"},
    )
    assert r.status_code == 400


def test_get_section_404_on_unknown_trip(client):
    r = client.get(
        "/api/section",
        params={"trip": "no-such-trip", "section": "gear"},
    )
    assert r.status_code == 404


def test_save_section_round_trip(client):
    payload = {"markdown": "## Updated\n\nFresh content.\n"}
    r = client.post(
        "/api/save-section",
        params={"trip": "killarney-2026-05", "section": "costs"},
        json=payload,
    )
    assert r.status_code == 200, r.text
    after = client.get(
        "/api/section",
        params={"trip": "killarney-2026-05", "section": "costs"},
    ).json()["markdown"]
    assert after == payload["markdown"]


def test_save_intro_preserves_frontmatter(client):
    new_body = "# Renamed trip\n\nDifferent intro.\n"
    r = client.post(
        "/api/save-section",
        params={"trip": "killarney-2026-05", "section": "intro"},
        json={"markdown": new_body},
    )
    assert r.status_code == 200, r.text
    # Reading the trip.md directly: frontmatter must still be there
    from app.services import trips as trips_svc
    trip_md = (trips_svc.TRIPS_DIR / "killarney-2026-05" / "trip.md").read_text(encoding="utf-8")
    assert trip_md.startswith("---\n")
    assert "park:" in trip_md
    assert "Different intro." in trip_md


def test_save_section_rejects_unknown_section(client):
    r = client.post(
        "/api/save-section",
        params={"trip": "killarney-2026-05", "section": "private"},
        json={"markdown": "secret"},
    )
    assert r.status_code == 400


def test_save_section_404_on_unknown_trip(client):
    r = client.post(
        "/api/save-section",
        params={"trip": "no-such-trip", "section": "gear"},
        json={"markdown": "x"},
    )
    assert r.status_code == 404


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
