"""FastAPI tests for /api/foods CRUD."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import foods as foods_svc


@pytest.fixture
def client(tmp_path, monkeypatch):
    catalog_path = tmp_path / "foods.json"
    catalog_path.write_text(json.dumps({
        "version": 1, "categories": ["meal", "snack"], "foods": [
            {"id": "tuna-pouch", "name": "Tuna pouch", "category": "snack",
             "kcal_per_serving": 110, "serving_size": "1 pouch", "url": None},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(foods_svc, "FOODS_JSON", catalog_path)
    foods_svc._invalidate_cache()

    trips_dir = tmp_path / "trips"
    trips_dir.mkdir()
    monkeypatch.setattr(foods_svc, "TRIPS_DIR", trips_dir)
    monkeypatch.setattr(config, "TRIPS_DIR", trips_dir)

    yield TestClient(app)


def test_get_foods_returns_catalog(client):
    r = client.get("/api/foods")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["categories"] == ["meal", "snack"]
    assert len(body["foods"]) == 1
    assert body["foods"][0]["id"] == "tuna-pouch"


def test_post_foods_creates_food(client):
    r = client.post("/api/foods", json={
        "name": "Snickers Bar", "category": "snack",
        "kcal_per_serving": 250, "serving_size": "1 bar", "url": None,
    })
    assert r.status_code == 200
    assert r.json()["id"] == "snickers-bar"


def test_post_foods_validation_error_returns_400(client):
    r = client.post("/api/foods", json={
        "name": "Bad", "category": "bogus",
        "kcal_per_serving": 0, "serving_size": "1", "url": None,
    })
    assert r.status_code == 400
    assert "category" in r.json()["detail"]["error"]


def test_put_foods_updates_existing(client):
    r = client.put("/api/foods/tuna-pouch", json={
        "name": "Tuna pouch", "category": "snack",
        "kcal_per_serving": 120, "serving_size": "1 pouch", "url": None,
    })
    assert r.status_code == 200
    cat = client.get("/api/foods").json()
    assert cat["foods"][0]["kcal_per_serving"] == 120


def test_put_foods_unknown_id_returns_404(client):
    r = client.put("/api/foods/nope", json={
        "name": "X", "category": "snack",
        "kcal_per_serving": 1, "serving_size": "1", "url": None,
    })
    assert r.status_code == 404


def test_delete_foods_blocks_when_referenced(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: tuna-pouch\n"
        "            servings: 2\n---\n", encoding="utf-8",
    )
    r = client.delete("/api/foods/tuna-pouch")
    assert r.status_code == 409
    assert "killarney-2026-07" in r.json()["detail"]["references"]


def test_delete_foods_force_proceeds(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: tuna-pouch\n"
        "            servings: 2\n---\n", encoding="utf-8",
    )
    r = client.delete("/api/foods/tuna-pouch?force=true")
    assert r.status_code == 200
    cat = client.get("/api/foods").json()
    assert cat["foods"] == []


def test_get_foods_refs(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: tuna-pouch\n"
        "            servings: 2\n---\n", encoding="utf-8",
    )
    r = client.get("/api/foods/refs/tuna-pouch")
    assert r.status_code == 200
    assert r.json()["references"] == ["killarney-2026-07"]
