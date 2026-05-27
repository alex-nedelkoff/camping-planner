import json

import pytest
from fastapi.testclient import TestClient

import app.services.trips as trips_svc
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _write_trip(tmp_path, monkeypatch, mode, site=""):
    import app.config as config
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
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


def test_hero_image_set_per_park(client, tmp_path, monkeypatch):
    import app.services.park_assets as pa
    parks_root = tmp_path / "parksimg"
    (parks_root / "balsam-lake").mkdir(parents=True)
    (parks_root / "balsam-lake" / "hero.jpg").write_bytes(b"x")
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", parks_root)
    slug = _write_trip(tmp_path, monkeypatch, mode="car_camping", site="401")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert '--hero-image: url("/static/img/parks/balsam-lake/hero.jpg")' in r.text


def test_hero_image_default_when_absent(client, tmp_path, monkeypatch):
    import app.services.park_assets as pa
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path / "empty")
    slug = _write_trip(tmp_path, monkeypatch, mode="paddle")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert '--hero-image: url("/static/img/killarney-hero.jpg")' in r.text


def test_car_camping_renders_route_map_and_zoom_maps(client, tmp_path, monkeypatch):
    import app.services.park_assets as pa
    parks_root = tmp_path / "parksimg"
    (parks_root / "balsam-lake").mkdir(parents=True)
    for f in ("campground-map.png", "park-map.png"):
        (parks_root / "balsam-lake" / f).write_bytes(b"x")
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", parks_root)
    slug = _write_trip(tmp_path, monkeypatch, mode="car_camping", site="401")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert 'id="gt-route-map"' in r.text
    assert 'data-park-lat=' in r.text and 'data-home-lat=' in r.text
    assert r.text.count('class="zoom-map"') == 2
    assert 'data-img="/static/img/parks/balsam-lake/campground-map.png"' in r.text
    assert "Download official PDF" in r.text
