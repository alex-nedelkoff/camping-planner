import json
from pathlib import Path

import pytest

from scripts.migrate_md_to_json import migrate_trip

FIXTURES = Path(__file__).parent / "fixtures" / "migration"


def test_migrate_full_trip_frontmatter_and_itinerary(tmp_path):
    src = FIXTURES / "full"
    dest = tmp_path / "killarney-2026-05"
    dest.mkdir()
    for f in src.iterdir():
        if f.suffix == ".md":
            (dest / f.name).write_text(f.read_text())
    migrate_trip(dest, slug="killarney-2026-05")
    result = json.loads((dest / "trip.json").read_text())
    assert result["schema_version"] == 1
    assert result["park"] == "killarney"
    assert result["dates"]["start"] == "2026-05-15"
    assert result["participants"] == ["Alex", "pizza-zip"]
    assert len(result["nights"]) == 2
    assert result["nights"][1]["gps"] == [46.044041, -81.503845]
    assert len(result["itinerary"]) == 2
    assert result["itinerary"][0]["label"].startswith("Friday")
    assert "Depart Ajax" in result["itinerary"][0]["notes"]
    assert len(result["food"]) == 2
    assert result["food"][0]["slot"] == "friday-dinner"


def test_migrate_refuses_overwrite_without_force(tmp_path):
    dest = tmp_path / "x"
    dest.mkdir()
    (dest / "trip.json").write_text("{}")
    (dest / "trip.md").write_text("---\npark: x\nstart_date: 2026-01-01\nend_date: 2026-01-02\n---\n")
    with pytest.raises(FileExistsError):
        migrate_trip(dest, slug="x")


def test_migrate_gear_costs_packing(tmp_path):
    src = FIXTURES / "full"
    dest = tmp_path / "x"
    dest.mkdir()
    for f in src.iterdir():
        if f.suffix == ".md":
            (dest / f.name).write_text(f.read_text())
    migrate_trip(dest, slug="x")
    result = json.loads((dest / "trip.json").read_text())

    assert result["gear"]["shared"] == [
        {"item": "Canoe", "who": "TBD", "notes": "confirm with outfitter"},
        {"item": "Paddles (2-3)", "who": "", "notes": ""},
    ]
    assert result["gear"]["personal"] == [
        {"person": "Alex",
         "items": [{"item": "Sleeping bag", "notes": ""},
                   {"item": "Headlamp", "notes": ""}]}
    ]
    assert result["costs"] == [
        {"item": "Permit", "who_paid": "Alex", "amount": 45.0, "currency": "CAD"},
        {"item": "Gas", "who_paid": "", "amount": None, "currency": "CAD"},
    ]
    assert result["packing"] == [
        {"category": "Shelter & sleep",
         "items": [{"label": "Tent", "checked": False},
                   {"label": "Sleeping bag", "checked": True}]},
        {"category": "Kitchen",
         "items": [{"label": "Stove", "checked": False}]},
    ]


def test_migrate_archives_md_files(tmp_path):
    src = FIXTURES / "full"
    dest = tmp_path / "x"
    dest.mkdir()
    for f in src.iterdir():
        if f.suffix == ".md":
            (dest / f.name).write_text(f.read_text())
    migrate_trip(dest, slug="x")
    assert not (dest / "trip.md").exists()
    assert (dest / "_archive" / "trip.md").exists()
    assert (dest / "trip.json").exists()
