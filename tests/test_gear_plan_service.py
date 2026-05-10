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
