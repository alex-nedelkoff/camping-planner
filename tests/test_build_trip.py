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


from unittest.mock import patch

from app.services.trips import load_trip_payload


_FAKE_WEATHER = {
    "source": "forecast",
    "days": [
        {
            "date": "2026-05-15",
            "high": 18.0,
            "low": 5.0,
            "precip_mm": 0.0,
            "precip_chance": 10,
            "code": 1,
            "description": "Mainly clear",
            "icon": "☀️",
        }
    ],
}


def _section_html(payload, section_id: str) -> str:
    for s in payload["sections"]:
        if s["id"] == section_id:
            return s["html"]
    return ""


def _all_html(payload) -> str:
    return payload["header_html"] + "".join(s["html"] for s in payload["sections"])


def test_load_trip_payload_assembles_sections(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "sample-trip"
    from app.services import trips as trips_svc
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", fixture.parent)

    from app.services import meal_plan as mp_svc
    monkeypatch.setattr(mp_svc, "TRIPS_DIR", fixture.parent)

    from app.services import gear_plan as gp_svc
    monkeypatch.setattr(gp_svc, "TRIPS_DIR", fixture.parent)

    with patch("build_trip.weather_provider", return_value=_FAKE_WEATHER), \
         patch("build_trip._osm_data.load_killarney_features",
               side_effect=FileNotFoundError("no cache")):
        payload = load_trip_payload("sample-trip")

    assert payload["slug"] == "sample-trip"
    section_ids = [s["id"] for s in payload["sections"]]
    # Intro + itinerary + weather + gear/food/packing/costs (no route — no GPX, no OSM).
    assert "intro" in section_ids
    assert "itinerary" in section_ids
    assert "weather" in section_ids
    assert "gear" in section_ids
    assert "route" not in section_ids

    full = _all_html(payload)
    # Gear is now a gear-plan section (html: ""); check non-gear markers in HTML.
    for marker in ("Welcome to the test trip", "Day 1", "Tent", "Permit"):
        assert marker in full, f"missing: {marker}"

    # Gear section is now a structured gear-plan section, not raw HTML.
    gear_section = next(s for s in payload["sections"] if s["id"] == "gear")
    assert gear_section["kind"] == "gear-plan"
    assert gear_section["editable"] is False
    # The fixture gear.md has no frontmatter — legacy_body surfaces the old prose.
    assert "Canoe" in gear_section["payload"]["plan"]["legacy_body"]

    # Food section is now a structured meal-plan section, not raw HTML.
    food_section = next(s for s in payload["sections"] if s["id"] == "food")
    assert food_section["kind"] == "meal-plan"
    # Legacy prose is surfaced in the payload for the migration banner.
    assert "Friday dinner" in food_section["payload"]["plan"]["legacy_body"]

    assert "Mainly clear" in _section_html(payload, "weather")
    assert "Killarney" in payload["header_html"]
    assert "2026-05-15" in payload["header_html"]
    assert "Alex" in payload["header_html"]

    assert 'data-cb-key="packing--tent"' in _section_html(payload, "packing")
    assert 'data-cb-key="packing--stove"' in _section_html(payload, "packing")


def test_load_trip_payload_renders_auto_route_when_no_gpx(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "sample-trip"
    from app.services import trips as trips_svc
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", fixture.parent)

    fake_osm = {
        "lakes": [
            {
                "name": "Killarney Lake",
                "polygon": [
                    [46.00, -81.50], [46.00, -81.30],
                    [46.10, -81.30], [46.10, -81.50],
                    [46.00, -81.50],
                ],
                "centroid": [46.05, -81.40],
            },
        ],
        "portages": [],
    }
    with patch("build_trip.weather_provider", return_value=_FAKE_WEATHER), \
         patch("build_trip._osm_data.load_killarney_features", return_value=fake_osm):
        payload = load_trip_payload("sample-trip")

    section_ids = [s["id"] for s in payload["sections"]]
    assert "route" in section_ids
    route_html = _section_html(payload, "route")
    for header in ("Day", "Paddle", "Portage", "Est. time"):
        assert header in route_html


def test_load_trip_payload_omits_route_when_no_osm_cache(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "sample-trip"
    from app.services import trips as trips_svc
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", fixture.parent)

    with patch("build_trip.weather_provider", return_value=_FAKE_WEATHER), \
         patch("build_trip._osm_data.load_killarney_features",
               side_effect=FileNotFoundError("no cache")):
        payload = load_trip_payload("sample-trip")
    assert "route" not in [s["id"] for s in payload["sections"]]
