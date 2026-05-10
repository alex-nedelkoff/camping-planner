"""Tests for the meal-plan service."""

import datetime

import pytest

from app.services import meal_plan as mp


def write_trip_md(trip_dir, frontmatter_yaml: str | None, body: str = "") -> None:
    food_md = trip_dir / "food.md"
    if frontmatter_yaml is None:
        food_md.write_text(body, encoding="utf-8")
    else:
        food_md.write_text(f"---\n{frontmatter_yaml}---\n{body}", encoding="utf-8")
    (trip_dir / "trip.md").write_text(
        "---\npark: killarney\n"
        "start_date: 2026-07-10\nend_date: 2026-07-12\n"
        "participants:\n  - Tom\n  - Alex\n  - Jordan\n---\n",
        encoding="utf-8",
    )


@pytest.fixture
def tmp_trips(tmp_path, monkeypatch):
    trips = tmp_path / "trips"
    (trips / "killarney-2026-07").mkdir(parents=True)
    monkeypatch.setattr(mp, "TRIPS_DIR", trips)
    return trips


def test_activity_defaults_table():
    assert mp.ACTIVITY_DEFAULTS["backcountry"] == 4000
    assert mp.ACTIVITY_DEFAULTS["bikepacking"] == 4500
    assert mp.ACTIVITY_DEFAULTS["boat-camping"] == 3500
    assert mp.ACTIVITY_DEFAULTS["car-camping"] == 2500


def test_load_no_frontmatter_returns_empty_plan_with_day_scaffold(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", None, body="Old prose here\n")
    plan = mp.load("killarney-2026-07")
    assert plan["calorie_target"]["activity_level"] == "backcountry"
    assert plan["calorie_target"]["kcal_per_person_per_day"] == 4000
    assert plan["participants"] == ["Tom", "Alex", "Jordan"]
    assert [d["date"] for d in plan["days"]] == [
        "2026-07-10", "2026-07-11", "2026-07-12",
    ]
    assert plan["legacy_body"].strip() == "Old prose here"


def test_load_with_frontmatter_round_trips(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", (
        "calorie_target:\n"
        "  activity_level: bikepacking\n"
        "  kcal_per_person_per_day: 4500\n"
        "days:\n"
        "  - date: 2026-07-10\n"
        "    label: Friday\n"
        "    meals:\n"
        "      - meal: dinner\n"
        "        items:\n"
        "          - food_id: tuna-pouch\n"
        "            servings: 2\n"
        "            who: Tom\n"
        "            note: ''\n"
    ), body="(generated)\n")
    plan = mp.load("killarney-2026-07")
    assert plan["calorie_target"]["activity_level"] == "bikepacking"
    assert plan["days"][0]["meals"][0]["items"][0]["food_id"] == "tuna-pouch"
    assert plan["legacy_body"] == ""


def test_load_unknown_trip_raises(tmp_trips):
    with pytest.raises(FileNotFoundError):
        mp.load("nope")


def test_load_handles_crlf_line_endings(tmp_trips):
    """food.md / trip.md edited on Windows can have CRLF line endings."""
    trip_dir = tmp_trips / "killarney-2026-07"
    food_md = trip_dir / "food.md"
    food_md.write_bytes(
        b"---\r\ncalorie_target:\r\n  activity_level: bikepacking\r\n"
        b"  kcal_per_person_per_day: 4500\r\ndays: []\r\n---\r\nbody\r\n"
    )
    (trip_dir / "trip.md").write_bytes(
        b"---\r\npark: killarney\r\n"
        b"start_date: 2026-07-10\r\nend_date: 2026-07-12\r\n"
        b"participants:\r\n  - Tom\r\n---\r\n"
    )
    plan = mp.load("killarney-2026-07")
    assert plan["calorie_target"]["activity_level"] == "bikepacking"
    assert plan["legacy_body"] == ""
    assert plan["participants"] == ["Tom"]
