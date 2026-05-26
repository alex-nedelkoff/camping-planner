import json

import pytest
from fastapi.testclient import TestClient

import app.services.trips as trips_svc
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _write_trip(tmp_path, monkeypatch, mode, site=""):
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_path)
    slug = "balsam-lake-2026-05"
    d = tmp_path / slug
    d.mkdir()
    trip = {
        "schema_version": 1, "name": slug, "park": "balsam-lake",
        "mode": mode,
        "dates": {"start": "2026-05-30", "end": "2026-05-31"},
        "participants": ["Alex"],
        "nights": [{"date": "2026-05-30", "site": site}],
        "itinerary": [], "gear": [], "food": [], "costs": [],
    }
    (d / "trip.json").write_text(json.dumps(trip))
    return slug


def test_car_camping_renders_getting_there_not_route(client, tmp_path, monkeypatch):
    slug = _write_trip(tmp_path, monkeypatch, mode="car_camping", site="123")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert 'data-section="getting-there"' in r.text
    assert 'data-section="route"' not in r.text


def test_paddle_still_renders_route(client, tmp_path, monkeypatch):
    slug = _write_trip(tmp_path, monkeypatch, mode="paddle")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert 'data-section="route"' in r.text
    assert 'data-section="getting-there"' not in r.text
