"""End-to-end tests for the meal-plan routes and trip-payload integration."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, foods as foods_svc, meal_plan as mp_svc, trips as trips_svc

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Catalog
    catalog_path = tmp_path / "foods.json"
    catalog_path.write_text(json.dumps({
        "version": 1, "categories": ["meal", "snack"], "foods": [
            {"id": "tuna-pouch", "name": "Tuna pouch", "category": "snack",
             "kcal_per_serving": 110, "serving_size": "1 pouch", "url": None},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(foods_svc, "FOODS_JSON", catalog_path)
    foods_svc._invalidate_cache()

    # Trips dir from repo
    tmp_trips = tmp_path / "trips"
    if (REPO_ROOT / "trips").exists():
        shutil.copytree(REPO_ROOT / "trips", tmp_trips)
    else:
        tmp_trips.mkdir()
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(mp_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(foods_svc, "TRIPS_DIR", tmp_trips)

    # DB
    tmp_db = tmp_path / "test.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)

    yield TestClient(app)


def test_get_meals_returns_scaffold_for_legacy_trip(client):
    r = client.get("/api/trip/killarney-2026-05/meals")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["plan"]["calorie_target"]["activity_level"] == "backcountry"
    assert len(body["plan"]["days"]) >= 1
    assert body["totals"]["target_kcal"] >= 0
    # Legacy prose surfaced for the migration banner
    assert body["plan"]["legacy_body"]


def test_post_meals_saves_and_round_trips(client):
    payload = {
        "calorie_target": {"activity_level": "backcountry", "kcal_per_person_per_day": 4000},
        "days": [{"date": "2026-05-08", "label": "Friday", "meals": [
            {"meal": "dinner", "items": [
                {"food_id": "tuna-pouch", "servings": 2, "who": "shared", "note": ""},
            ]},
        ]}],
    }
    r = client.post("/api/trip/killarney-2026-05/meals", json=payload)
    assert r.status_code == 200
    r2 = client.get("/api/trip/killarney-2026-05/meals")
    plan = r2.json()["plan"]
    assert plan["legacy_body"] == ""
    assert plan["days"][0]["meals"][0]["items"][0]["food_id"] == "tuna-pouch"


def test_trip_payload_marks_food_section_as_meal_plan(client):
    r = client.get("/api/trip/killarney-2026-05")
    assert r.status_code == 200
    body = r.json()
    food_section = next(s for s in body["sections"] if s["id"] == "food")
    assert food_section["kind"] == "meal-plan"


def test_food_section_is_not_legacy_editable(client):
    """Food section must use the meal-plan UI; legacy save-section endpoint
    must NOT accept writes to it (would destroy the YAML frontmatter)."""
    r = client.post(
        "/api/save-section?trip=killarney-2026-05&section=food",
        json={"markdown": "garbage that would overwrite YAML"},
    )
    assert r.status_code == 400


def test_food_section_payload_is_marked_not_editable(client):
    """The trip payload must mark the food section as not legacy-editable."""
    r = client.get("/api/trip/killarney-2026-05")
    assert r.status_code == 200
    food_section = next(s for s in r.json()["sections"] if s["id"] == "food")
    assert food_section["editable"] is False
    assert food_section["kind"] == "meal-plan"
