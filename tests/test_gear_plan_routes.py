"""End-to-end tests for the gear-plan routes and trip-payload integration."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, gear as gear_svc, gear_plan as gp_svc, trips as trips_svc

REPO_ROOT = Path(__file__).resolve().parent.parent


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

    tmp_trips = tmp_path / "trips"
    if (REPO_ROOT / "trips").exists():
        shutil.copytree(REPO_ROOT / "trips", tmp_trips)
    else:
        tmp_trips.mkdir()
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(gp_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(gear_svc, "TRIPS_DIR", tmp_trips)

    tmp_db = tmp_path / "test.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)

    yield TestClient(app)


def test_get_gear_plan_returns_scaffold_for_legacy_trip(client, tmp_path):
    """Self-contained legacy trip — don't depend on a repo trip's current state."""
    trip_dir = tmp_path / "trips" / "legacy-2026-09"
    trip_dir.mkdir(parents=True)
    (trip_dir / "trip.md").write_text(
        "---\npark: killarney\n"
        "start_date: 2026-09-04\nend_date: 2026-09-06\n"
        "participants:\n  - Sam\n---\n", encoding="utf-8",
    )
    (trip_dir / "gear.md").write_text(
        "## Shared gear\n\n| Item |\n|---|\n| Old |\n", encoding="utf-8",
    )
    r = client.get("/api/trip/legacy-2026-09/gear-plan")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["plan"]["items"] == []
    assert body["plan"]["legacy_body"]
    assert body["totals"]["trip_g"] == 0


def test_post_gear_plan_saves_and_round_trips(client, tmp_path):
    trip_dir = tmp_path / "trips" / "freshtrip-2026-09"
    trip_dir.mkdir(parents=True)
    (trip_dir / "trip.md").write_text(
        "---\npark: killarney\nstart_date: 2026-09-04\n"
        "end_date: 2026-09-06\nparticipants:\n  - Sam\n---\n",
        encoding="utf-8",
    )
    (trip_dir / "gear.md").write_text(
        "---\nitems: []\n---\n\n# Shared gear\n", encoding="utf-8",
    )
    payload = {"items": [
        {"item_id": "compass", "qty": 1, "who": "Sam",
         "notes": "", "override_weight_g": None},
    ]}
    r = client.post("/api/trip/freshtrip-2026-09/gear-plan", json=payload)
    assert r.status_code == 200
    r2 = client.get("/api/trip/freshtrip-2026-09/gear-plan")
    plan = r2.json()["plan"]
    assert plan["items"][0]["item_id"] == "compass"
    assert plan["legacy_body"] == ""


def test_trip_payload_marks_gear_section_as_gear_plan(client):
    r = client.get("/api/trip/killarney-2026-05")
    assert r.status_code == 200
    body = r.json()
    gear_section = next(s for s in body["sections"] if s["id"] == "gear")
    assert gear_section["kind"] == "gear-plan"
    assert gear_section["editable"] is False


def test_gear_section_is_not_legacy_editable(client):
    """Regression: gear section must not accept the legacy save-section API
    (would destroy the YAML frontmatter — same bug we hit on food)."""
    r = client.post(
        "/api/save-section?trip=killarney-2026-05&section=gear",
        json={"markdown": "garbage"},
    )
    assert r.status_code == 400


def test_gear_section_is_not_table_editable(client):
    """save-section-table on gear should also be rejected (was previously
    allowed via the gear table editor)."""
    r = client.post(
        "/api/save-section-table?trip=killarney-2026-05&section=gear",
        json={"rows": [["x", "y", "z"]]},
    )
    assert r.status_code == 400
