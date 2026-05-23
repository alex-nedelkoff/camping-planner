import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, trips as trips_svc


@pytest.fixture
def client(tmp_path, monkeypatch):
    tmp_trips = tmp_path / "trips"
    tmp_trips.mkdir()
    d = tmp_trips / "k-2026-05"
    d.mkdir()
    (d / "trip.json").write_text(json.dumps({
        "schema_version": 1, "name": "k-2026-05", "park": "killarney",
        "dates": {"start": "2026-05-15", "end": "2026-05-18"},
        "participants": ["Alex"], "access_point": "George Lake",
        "nights": [{"date": "2026-05-15", "site": "61",
                    "location": "OSA Lake", "gps": None}],
        "itinerary": [{"date": "2026-05-15", "label": "Day 1",
                       "notes": "Depart Ajax"}],
        "gear": [
            {"item": "Canoe", "category": "Boat", "notes": "",
             "bringers": [], "shared": True},
            {"item": "Tent", "category": "Sleep", "notes": "",
             "bringers": [], "shared": True},
        ],
        "food": [{"slot": "friday-dinner", "label": "Friday dinner",
                  "items": [], "notes": ""}],
        "costs": [{"item": "Permit", "who_paid": "Alex",
                   "amount": 45.0, "currency": "CAD"}],
    }))
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    tmp_db = tmp_path / "x.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)
    from app.services import weather_cache, route_cache
    monkeypatch.setattr(weather_cache, "get_weather",
                         lambda **kw: {"days": [
                             {"date": "2026-05-15", "high": 18,
                              "low": 5, "summary": "sun"}]})
    monkeypatch.setattr(route_cache, "get_route_render",
                         lambda *a, **kw: {"html": "<div>fake</div>",
                                            "distance_km": 12.3,
                                            "empty": False})
    yield TestClient(app)


def test_trip_page_renders(client):
    r = client.get("/trip/k-2026-05")
    assert r.status_code == 200
    html = r.text
    assert "k-2026-05" in html
    assert "OSA Lake" in html
    assert "Day 1" in html
    assert "Depart Ajax" in html
    assert "Canoe" in html
    assert "Friday dinner" in html
    assert "Permit" in html
    assert "Tent" in html
    assert "12.3 km" in html
    assert "sun" in html


def test_trip_page_404(client):
    r = client.get("/trip/does-not-exist")
    assert r.status_code == 404
