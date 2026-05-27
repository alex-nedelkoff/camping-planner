import json

import pytest

import app.services.trips as trips_svc


def test_create_trip_v2_persists_mode(tmp_path, monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    slug = trips_svc.create_trip_v2(
        park="balsam-lake", start_date="2026-05-30", end_date="2026-05-31",
        participants=["Alex"], mode="car_camping",
    )
    data = json.loads((tmp_path / slug / "trip.json").read_text())
    assert data["mode"] == "car_camping"


def test_create_trip_v2_defaults_paddle(tmp_path, monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    slug = trips_svc.create_trip_v2(
        park="killarney", start_date="2026-07-01", end_date="2026-07-03",
        participants=[],
    )
    data = json.loads((tmp_path / slug / "trip.json").read_text())
    assert data["mode"] == "paddle"


def test_post_trips_accepts_mode(tmp_path, monkeypatch):
    import app.config as config
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    c = TestClient(app)
    r = c.post("/api/trips", json={
        "park": "balsam-lake", "start": "2026-05-30", "end": "2026-05-31",
        "participants": ["Alex"], "mode": "car_camping",
    })
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    data = json.loads((tmp_path / slug / "trip.json").read_text())
    assert data["mode"] == "car_camping"
