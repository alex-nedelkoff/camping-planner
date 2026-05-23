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
