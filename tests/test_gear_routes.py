"""FastAPI tests for /api/gear CRUD."""

import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import gear as gear_svc


@pytest.fixture
def client(tmp_path, monkeypatch):
    catalog_path = tmp_path / "gear.json"
    catalog_path.write_text(json.dumps({
        "version": 1,
        "categories": ["Navigation", "Cook", "Other"],
        "items": [
            {"id": "compass", "name": "Compass",
             "category": "Navigation", "weight_g": 30},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(gear_svc, "GEAR_JSON", catalog_path)
    gear_svc._invalidate_cache()

    trips_dir = tmp_path / "trips"
    trips_dir.mkdir()
    monkeypatch.setattr(gear_svc, "TRIPS_DIR", trips_dir)
    monkeypatch.setattr(config, "TRIPS_DIR", trips_dir)

    yield TestClient(app)


def test_get_gear_returns_catalog(client):
    r = client.get("/api/gear")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["categories"] == ["Navigation", "Cook", "Other"]
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == "compass"


def test_post_gear_creates_item(client):
    r = client.post("/api/gear", json={
        "name": "Headlamp", "category": "Other", "weight_g": 90,
    })
    assert r.status_code == 200
    assert r.json()["id"] == "headlamp"


def test_post_gear_accepts_null_weight(client):
    r = client.post("/api/gear", json={
        "name": "Custom Tent", "category": "Other", "weight_g": None,
    })
    assert r.status_code == 200


def test_post_gear_validation_error_returns_400(client):
    r = client.post("/api/gear", json={
        "name": "Bad", "category": "bogus", "weight_g": 0,
    })
    assert r.status_code == 400
    assert "category" in r.json()["detail"]["error"]


def test_put_gear_updates_existing(client):
    r = client.put("/api/gear/compass", json={
        "name": "Compass", "category": "Navigation", "weight_g": 35,
    })
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert cat["items"][0]["weight_g"] == 35


def test_put_gear_unknown_id_returns_404(client):
    r = client.put("/api/gear/nope", json={
        "name": "X", "category": "Other", "weight_g": 1,
    })
    assert r.status_code == 404


def test_delete_gear_blocks_when_referenced(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "gear.md").write_text(
        "---\nitems:\n  - item_id: compass\n    qty: 1\n---\n", encoding="utf-8",
    )
    r = client.delete("/api/gear/compass")
    assert r.status_code == 409
    assert "killarney-2026-07" in r.json()["detail"]["references"]


def test_delete_gear_force_proceeds(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "gear.md").write_text(
        "---\nitems:\n  - item_id: compass\n    qty: 1\n---\n", encoding="utf-8",
    )
    r = client.delete("/api/gear/compass?force=true")
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert cat["items"] == []


def test_get_gear_refs(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "gear.md").write_text(
        "---\nitems:\n  - item_id: compass\n    qty: 1\n---\n", encoding="utf-8",
    )
    r = client.get("/api/gear/refs/compass")
    assert r.status_code == 200
    assert r.json()["references"] == ["killarney-2026-07"]


def test_post_category_adds(client):
    r = client.post("/api/gear/categories", json={"name": "Photography"})
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert "Photography" in cat["categories"]


def test_post_category_duplicate_returns_400(client):
    r = client.post("/api/gear/categories", json={"name": "cook"})
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]["error"]


def test_put_category_renames_and_updates_items(client):
    """Add a category, then rename it (no items use it) — happy path."""
    client.post("/api/gear/categories", json={"name": "Tmp"})
    r = client.put("/api/gear/categories/Tmp", json={"new_name": "Tmp2"})
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert "Tmp2" in cat["categories"]
    assert "Tmp" not in cat["categories"]


def test_put_category_renames_navigation_to_orient(client):
    r = client.put("/api/gear/categories/Navigation", json={"new_name": "Orient"})
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert "Orient" in cat["categories"]
    assert "Navigation" not in cat["categories"]
    assert cat["items"][0]["category"] == "Orient"


def test_put_category_unknown_returns_404(client):
    r = client.put("/api/gear/categories/Bogus", json={"new_name": "X"})
    assert r.status_code == 404


def test_put_category_protected_other_returns_400(client):
    r = client.put("/api/gear/categories/Other", json={"new_name": "Misc"})
    assert r.status_code == 400


def test_put_category_collision_returns_400(client):
    r = client.put("/api/gear/categories/Cook", json={"new_name": "Other"})
    assert r.status_code == 400


def test_delete_category_blocked_when_in_use(client):
    r = client.delete("/api/gear/categories/Navigation")
    assert r.status_code == 409


def test_delete_category_force_reassigns_to_other(client):
    r = client.delete("/api/gear/categories/Navigation?force=true")
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert "Navigation" not in cat["categories"]
    assert cat["items"][0]["category"] == "Other"


def test_delete_category_unused_succeeds(client):
    # Cook has no items in fixture
    r = client.delete("/api/gear/categories/Cook")
    assert r.status_code == 200


def test_delete_category_protected_other_returns_400(client):
    r = client.delete("/api/gear/categories/Other?force=true")
    assert r.status_code == 400
