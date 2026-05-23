"""Snapshot-ish smoke tests for the nav band across pages."""

import json
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, trips as trips_svc


@pytest.fixture
def client(tmp_path, monkeypatch):
    tmp_trips = tmp_path / "trips"
    tmp_trips.mkdir()
    for slug, start in [("a-2026-04", "2026-04-01"),
                         ("b-2026-06", "2026-06-15")]:
        d = tmp_trips / slug
        d.mkdir()
        (d / "trip.json").write_text(json.dumps({
            "schema_version": 1, "name": slug,
            "park": "killarney",
            "dates": {"start": start, "end": start[:8] + "10"},
            "participants": ["Alex"], "access_point": "",
            "nights": [], "itinerary": [],
            "gear": {"shared": [], "personal": []},
            "food": [], "costs": [], "packing": [],
        }))
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    tmp_db = tmp_path / "x.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)
    yield TestClient(app)


def test_nav_band_on_trip_page_has_chevrons_and_dropdown(client):
    r = client.get("/trip/a-2026-04")
    assert r.status_code == 200
    html = r.text
    assert 'class="nav-band"' in html
    assert "trip-dropdown" in html
    assert 'href="/trip/b-2026-06"' in html


def test_nav_band_on_trip_page_dropdown_lists_all_trips(client):
    r = client.get("/trip/a-2026-04")
    html = r.text
    assert "a-2026-04" in html and "b-2026-06" in html


def test_nav_band_on_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'class="nav-band"' in r.text
