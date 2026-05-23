"""Tests for the new /api/trips endpoints (trip.json era)."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, trips as trips_svc

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    tmp_trips = tmp_path / "trips"
    tmp_trips.mkdir()
    # Two minimal JSON trips
    for slug, start in [("a-2026-04", "2026-04-01"),
                         ("b-2026-06", "2026-06-15")]:
        d = tmp_trips / slug
        d.mkdir()
        (d / "trip.json").write_text(json.dumps({
            "schema_version": 1, "name": slug,
            "park": "killarney" if slug.startswith("a") else "killbear",
            "dates": {"start": start,
                       "end": start[:8] + str(int(start[8:]) + 2).zfill(2)},
            "participants": ["Alex"], "access_point": "",
            "nights": [], "itinerary": [], "gear": {"shared": [], "personal": []},
            "food": [], "costs": [], "packing": [],
        }))
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    tmp_db = tmp_path / "test.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)
    yield TestClient(app)


def test_list_trips_returns_sorted_with_neighbours(client):
    r = client.get("/api/trips")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    slugs = [t["slug"] for t in body["trips"]]
    assert slugs == ["a-2026-04", "b-2026-06"]
    assert body["trips"][0]["prev_slug"] is None
    assert body["trips"][0]["next_slug"] == "b-2026-06"
    assert body["trips"][1]["prev_slug"] == "a-2026-04"
    assert body["trips"][1]["next_slug"] is None


def test_get_trip_returns_json(client):
    r = client.get("/api/trips/a-2026-04")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "a-2026-04"
    assert body["dates"]["start"] == "2026-04-01"


def test_get_trip_404(client):
    r = client.get("/api/trips/does-not-exist")
    assert r.status_code == 404


def test_refresh_weather_invalidates_cache(client, monkeypatch):
    from app.services import weather_cache
    calls = []
    def fake(park_key, start_date, end_date):
        calls.append((park_key, start_date, end_date))
        return {"days": []}
    monkeypatch.setattr(weather_cache, "get_weather", fake)
    r = client.post("/api/trips/a-2026-04/refresh-weather")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_refresh_route_invalidates_cache(client):
    r = client.post("/api/trips/a-2026-04/refresh-route")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_refresh_404_for_missing_trip(client):
    r = client.post("/api/trips/nope/refresh-weather")
    assert r.status_code == 404


def test_patch_meta_updates_fields(client):
    r = client.patch("/api/trips/a-2026-04/meta",
                      json={"access_point": "George Lake"})
    assert r.status_code == 200
    r2 = client.get("/api/trips/a-2026-04")
    assert r2.json()["access_point"] == "George Lake"


def test_put_section_replaces_gear(client):
    r = client.put("/api/trips/a-2026-04/section/gear",
                    json={"shared": [{"item": "Canoe", "who": "Alex", "notes": ""}],
                          "personal": []})
    assert r.status_code == 200
    body = client.get("/api/trips/a-2026-04").json()
    assert body["gear"]["shared"][0]["item"] == "Canoe"


def test_put_section_rejects_unknown_section(client):
    r = client.put("/api/trips/a-2026-04/section/badname",
                    json={})
    assert r.status_code == 400


def test_put_section_validates(client):
    r = client.put("/api/trips/a-2026-04/section/gear",
                    json={"shared": [{"item": 123}], "personal": []})
    assert r.status_code == 422


def test_put_routes_writes_file(client, tmp_path):
    r = client.put("/api/trips/a-2026-04/routes",
                    json=[{"name": "Day 1 paddle", "waypoints": []}])
    assert r.status_code == 200
    r2 = client.get("/api/trips/a-2026-04/routes")
    assert r2.json()[0]["name"] == "Day 1 paddle"


def test_post_create_writes_trip_json(client, tmp_path):
    r = client.post("/api/trips", json={
        "park": "killarney", "start": "2027-06-01", "end": "2027-06-04",
        "participants": ["Alex"],
    })
    assert r.status_code == 200
    slug = r.json()["slug"]
    assert slug == "killarney-2027-06"
    body = client.get(f"/api/trips/{slug}").json()
    assert body["dates"]["start"] == "2027-06-01"
    assert body["participants"] == ["Alex"]


def test_post_create_409_on_duplicate(client):
    payload = {"park": "killarney", "start": "2027-06-01",
                "end": "2027-06-04", "participants": []}
    client.post("/api/trips", json=payload)
    r = client.post("/api/trips", json=payload)
    assert r.status_code == 409


def test_delete_trip_removes_dir(client):
    r = client.delete("/api/trips/a-2026-04")
    assert r.status_code == 200
    r2 = client.get("/api/trips/a-2026-04")
    assert r2.status_code == 404
