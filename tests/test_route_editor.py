"""HTTP tests for the waypoint editor endpoints — JSON-only, no auth."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    trips = tmp_path / "trips"
    trips.mkdir()
    (trips / "t").mkdir()
    (trips / "t" / "trip.md").write_text(
        "---\npark: killarney\nstart_date: 2026-05-15\n---\n"
    )
    monkeypatch.setattr("app.config.TRIPS_DIR", trips)
    monkeypatch.setattr("app.routes.route_editor.TRIPS_DIR", trips)
    return TestClient(app), trips


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
    body = r.json()
    assert [w["name"] for w in body["waypoints"]] == ["A", "B"]


def test_post_with_empty_waypoints_writes_empty_gpx(setup):
    client, trips = setup
    r = client.post("/api/trips/t/route", json={"waypoints": []})
    assert r.status_code == 200
    assert r.json()["saved"] == 0
    assert (trips / "t" / "route.gpx").exists()
    assert "<trk>" not in (trips / "t" / "route.gpx").read_text()


def test_route_meta_returns_centre_and_seed(setup):
    client, _ = setup
    r = client.get("/api/trips/t/route-meta")
    assert r.status_code == 200
    body = r.json()
    assert body["park"] == "killarney"
    assert body["centre"] == [46.01, -81.4]
    assert body["zoom"] == 12
    assert body["waypoints"] == []
    # raster_url is None on a clean test env (no mosaic data), bounds None
    assert "raster_url" in body and "raster_bounds" in body


def test_route_meta_includes_existing_waypoints(setup):
    client, trips = setup
    from app.services import route_gpx
    route_gpx.save_waypoints(trips / "t", [
        {"lat": 46.1, "lon": -81.3, "name": "Pre-existing"},
    ])
    r = client.get("/api/trips/t/route-meta")
    assert r.status_code == 200
    seed = r.json()["waypoints"]
    assert len(seed) == 1 and seed[0]["name"] == "Pre-existing"


def test_endpoints_404_for_unknown_trip(setup):
    client, _ = setup
    assert client.get("/api/trips/missing/route").status_code == 404
    assert client.get("/api/trips/missing/route-meta").status_code == 404
    r = client.post("/api/trips/missing/route", json={"waypoints": []})
    assert r.status_code == 404
