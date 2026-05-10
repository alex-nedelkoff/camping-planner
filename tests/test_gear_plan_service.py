"""Tests for the gear-plan service."""

import pytest

from app.services import gear_plan as gp


def write_trip_md(trip_dir, frontmatter_yaml: str | None, body: str = "") -> None:
    gear_md = trip_dir / "gear.md"
    if frontmatter_yaml is None:
        gear_md.write_text(body, encoding="utf-8")
    else:
        gear_md.write_text(f"---\n{frontmatter_yaml}---\n{body}", encoding="utf-8")
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
    monkeypatch.setattr(gp, "TRIPS_DIR", trips)
    return trips


def test_load_no_frontmatter_returns_empty_plan(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", None,
                  body="## Old gear table\n| A | B |\n")
    plan = gp.load("killarney-2026-07")
    assert plan["items"] == []
    assert plan["participants"] == ["Tom", "Alex", "Jordan"]
    assert "Old gear table" in plan["legacy_body"]


def test_load_with_frontmatter_round_trips(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", (
        "items:\n"
        "  - item_id: compass\n"
        "    qty: 1\n"
        "    who: Tom\n"
        "    notes: ''\n"
        "    override_weight_g: null\n"
    ), body="(generated)\n")
    plan = gp.load("killarney-2026-07")
    assert plan["items"][0]["item_id"] == "compass"
    assert plan["legacy_body"] == ""


def test_load_handles_crlf_line_endings(tmp_trips):
    """Windows-edited gear.md or trip.md may have CRLF line endings."""
    trip_dir = tmp_trips / "killarney-2026-07"
    (trip_dir / "gear.md").write_bytes(
        b"---\r\nitems:\r\n  - item_id: compass\r\n    qty: 1\r\n---\r\n"
    )
    (trip_dir / "trip.md").write_bytes(
        b"---\r\npark: killarney\r\n"
        b"start_date: 2026-07-10\r\nend_date: 2026-07-12\r\n"
        b"participants:\r\n  - Tom\r\n---\r\n"
    )
    plan = gp.load("killarney-2026-07")
    assert plan["items"][0]["item_id"] == "compass"
    assert plan["participants"] == ["Tom"]


def test_load_unknown_trip_raises(tmp_trips):
    with pytest.raises(FileNotFoundError):
        gp.load("nope")


SAMPLE_CATALOG = {
    "version": 1,
    "categories": ["Navigation", "Cook", "Other"],
    "items": [
        {"id": "compass", "name": "Compass", "category": "Navigation", "weight_g": 30},
        {"id": "stove", "name": "Stove", "category": "Cook", "weight_g": 73},
        {"id": "tent", "name": "Tent", "category": "Other", "weight_g": None},
    ],
}

SAMPLE_PLAN = {
    "items": [
        {"item_id": "compass", "qty": 1, "who": "Tom", "notes": "", "override_weight_g": None},
        {"item_id": "stove", "qty": 2, "who": "shared", "notes": "", "override_weight_g": None},
        {"item_id": "tent", "qty": 1, "who": "shared", "notes": "", "override_weight_g": None},
    ],
    "participants": ["Tom", "Alex"],
    "legacy_body": "",
}


def test_compute_totals_per_row():
    totals = gp.compute_totals(SAMPLE_PLAN, SAMPLE_CATALOG)
    rows = totals["items"]
    assert rows[0]["weight_g_each"] == 30
    assert rows[0]["weight_g_total"] == 30
    assert rows[1]["weight_g_each"] == 73
    assert rows[1]["weight_g_total"] == 146   # 73 * 2
    assert rows[2]["weight_g_each"] is None
    assert rows[2]["weight_g_total"] is None
    assert rows[2]["unknown_weight"] is True


def test_compute_totals_by_who_and_trip():
    totals = gp.compute_totals(SAMPLE_PLAN, SAMPLE_CATALOG)
    assert totals["by_who"]["Tom"] == 30
    assert totals["by_who"]["shared"] == 146  # only the stove counts (tent unknown)
    assert totals["trip_g"] == 176
    assert totals["unknown_count"] == 1


def test_compute_totals_override_weight():
    plan = {
        "items": [
            {"item_id": "compass", "qty": 1, "who": "Tom",
             "notes": "", "override_weight_g": 50},
            {"item_id": "tent", "qty": 1, "who": "shared",
             "notes": "", "override_weight_g": 1200},
        ],
        "participants": ["Tom"],
        "legacy_body": "",
    }
    totals = gp.compute_totals(plan, SAMPLE_CATALOG)
    assert totals["items"][0]["weight_g_each"] == 50
    assert totals["items"][1]["weight_g_each"] == 1200
    assert totals["items"][1]["unknown_weight"] is False
    assert totals["trip_g"] == 1250


def test_compute_totals_unknown_item_id():
    plan = {
        "items": [
            {"item_id": "ghost", "qty": 1, "who": "Tom",
             "notes": "", "override_weight_g": None},
        ],
        "participants": ["Tom"],
        "legacy_body": "",
    }
    totals = gp.compute_totals(plan, SAMPLE_CATALOG)
    row = totals["items"][0]
    assert row["unknown_item"] is True
    assert row["name"] is None
    assert row["category"] is None
    assert row["weight_g_total"] is None
    assert totals["trip_g"] == 0
    assert totals["unknown_count"] == 1
