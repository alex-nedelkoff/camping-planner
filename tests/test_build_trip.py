"""Tests for build_trip.py."""
from pathlib import Path

import pytest

from build_trip import load_trip


def _write_minimal_trip(trip_dir: Path) -> None:
    """Create a minimal valid trip directory at trip_dir."""
    trip_dir.mkdir(parents=True, exist_ok=True)
    (trip_dir / "trip.md").write_text(
        "---\n"
        "park: killarney\n"
        "start_date: 2026-05-15\n"
        "end_date: 2026-05-18\n"
        "participants:\n"
        "  - Alex\n"
        "  - Friend\n"
        "nights:\n"
        "  - date: 2026-05-15\n"
        "    site: '61'\n"
        "    location: OSA Lake\n"
        "---\n"
        "\n"
        "Intro text body.\n"
    )
    (trip_dir / "itinerary.md").write_text("## Day 1\n\nPaddle.\n")
    (trip_dir / "gear.md").write_text("Gear list.\n")
    (trip_dir / "food.md").write_text("")
    (trip_dir / "packing.md").write_text("- [ ] Tent\n")
    (trip_dir / "costs.md").write_text("")


def test_load_trip_parses_frontmatter_and_sections(tmp_path):
    trip_dir = tmp_path / "test-trip"
    _write_minimal_trip(trip_dir)

    result = load_trip(trip_dir)

    assert result["frontmatter"]["park"] == "killarney"
    assert result["frontmatter"]["start_date"] == "2026-05-15"
    assert result["frontmatter"]["participants"] == ["Alex", "Friend"]
    assert result["frontmatter"]["nights"][0]["site"] == "61"
    assert result["frontmatter"]["nights"][0]["location"] == "OSA Lake"
    assert "Intro text body." in result["intro"]
    assert "Paddle." in result["itinerary"]
    assert "- [ ] Tent" in result["packing"]
    assert result["route_file"] is None


def test_load_trip_picks_up_gpx_route(tmp_path):
    trip_dir = tmp_path / "test-trip"
    _write_minimal_trip(trip_dir)
    (trip_dir / "route.gpx").write_text("<gpx></gpx>")

    result = load_trip(trip_dir)

    assert result["route_file"] is not None
    assert result["route_file"].name == "route.gpx"


def test_load_trip_picks_up_kml_route(tmp_path):
    trip_dir = tmp_path / "test-trip"
    _write_minimal_trip(trip_dir)
    (trip_dir / "route.kml").write_text("<kml></kml>")

    result = load_trip(trip_dir)

    assert result["route_file"] is not None
    assert result["route_file"].name == "route.kml"


def test_load_trip_prefers_gpx_over_kml(tmp_path):
    trip_dir = tmp_path / "test-trip"
    _write_minimal_trip(trip_dir)
    (trip_dir / "route.gpx").write_text("<gpx></gpx>")
    (trip_dir / "route.kml").write_text("<kml></kml>")

    result = load_trip(trip_dir)

    assert result["route_file"].name == "route.gpx"


def test_load_trip_raises_on_missing_trip_md(tmp_path):
    trip_dir = tmp_path / "test-trip"
    trip_dir.mkdir()
    # No trip.md created.
    with pytest.raises(ValueError, match="trip.md not found"):
        load_trip(trip_dir)


def test_load_trip_raises_on_missing_frontmatter(tmp_path):
    trip_dir = tmp_path / "test-trip"
    trip_dir.mkdir()
    (trip_dir / "trip.md").write_text("No frontmatter here.\n")
    for n in ("itinerary", "gear", "food", "packing", "costs"):
        (trip_dir / f"{n}.md").write_text("")

    with pytest.raises(ValueError, match="frontmatter"):
        load_trip(trip_dir)


from build_trip import render_section


def test_render_section_converts_unchecked_task_to_checkbox():
    md = "- [ ] First item\n"
    html = render_section(md, "packing")
    assert 'type="checkbox"' in html
    assert 'data-cb-key="packing--first-item"' in html
    # Unchecked must NOT include the literal " checked" attribute.
    assert " checked" not in html


def test_render_section_converts_checked_task_to_checkbox():
    md = "- [x] Done item\n"
    html = render_section(md, "packing")
    assert 'data-cb-key="packing--done-item"' in html
    assert "checked" in html


def test_render_section_renders_tables():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    html = render_section(md, "gear")
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_render_section_handles_headings_and_paragraphs():
    md = "## Hello\n\nA paragraph.\n"
    html = render_section(md, "intro")
    assert "<h2>Hello</h2>" in html
    assert "<p>A paragraph.</p>" in html
