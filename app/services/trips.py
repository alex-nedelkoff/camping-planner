"""Trip discovery, creation, and editing services.

Pure functions over the filesystem and the build_trip render library.
Routes call into these; tests import them directly.
"""

import datetime
import json
import re
import shutil
from pathlib import Path

import yaml

import build_trip

from app.config import PARKS_JSON, TEMPLATE_DIR, TRIPS_DIR
from app.services import weather_cache as _weather_cache

# Route the trip renderer through the SQLite-cached weather lookup so repeated
# trip loads don't re-hit Open-Meteo.
build_trip.weather_provider = _weather_cache.get_weather


_MD_TABLE_RE = re.compile(
    r"(^\|.+\|[ \t]*\n\|[\s|:\-]+\|[ \t]*\n)((?:^\|.*\|[ \t]*\n)*)",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Markdown table editing (used by the gear save endpoint)
# ---------------------------------------------------------------------------


def _md_escape_cell(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\n", " ")
        .strip()
    )


def replace_first_table(md_text: str, new_rows: list) -> str:
    """Replace the data rows of the first markdown table; preserve the header."""
    match = _MD_TABLE_RE.search(md_text)
    if not match:
        raise ValueError("no markdown table found")
    header_block = match.group(1)
    header_line = header_block.splitlines()[0]
    ncols = len(header_line.strip().strip("|").split("|"))
    rendered = []
    for row in new_rows:
        cells = [_md_escape_cell(c) for c in (row or [])]
        cells = (cells + [""] * ncols)[:ncols]
        rendered.append("| " + " | ".join(cells) + " |")
    new_rows_md = ("\n".join(rendered) + "\n") if rendered else ""
    return md_text[: match.start()] + header_block + new_rows_md + md_text[match.end():]


# ---------------------------------------------------------------------------
# Trip discovery
# ---------------------------------------------------------------------------


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def scan_trips(trips_dir: Path | None = None) -> list[dict]:
    """Return a list of trip metadata dicts from <trips_dir>/*/trip.md."""
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    if not trips_dir.exists():
        return []
    trips = []
    for trip_dir in sorted(trips_dir.iterdir()):
        if not trip_dir.is_dir():
            continue
        trip_md = trip_dir / "trip.md"
        if not trip_md.exists():
            continue
        try:
            text = trip_md.read_text(encoding="utf-8")
            match = build_trip.FRONTMATTER_RE.match(text)
            if not match:
                trips.append({"name": trip_dir.name, "error": "missing frontmatter"})
                continue
            fm = yaml.safe_load(match.group(1)) or {}
            fm = build_trip._stringify_dates(fm)
            park_info = build_trip._load_park_info(fm.get("park", ""))
            trips.append({
                "name": trip_dir.name,
                "park": fm.get("park", ""),
                "park_name": park_info.get("name") or fm.get("park", "Trip"),
                "start_date": fm.get("start_date", ""),
                "end_date": fm.get("end_date", ""),
                "participants": fm.get("participants", []) or [],
                "has_html": (trip_dir / "trip.html").exists(),
            })
        except Exception as exc:
            trips.append({"name": trip_dir.name, "error": str(exc)})
    return trips


def split_trips(trips: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Sort trips into (upcoming, past, broken) buckets."""
    today = datetime.date.today()
    upcoming, past, broken = [], [], []
    for trip in trips:
        if "error" in trip:
            broken.append(trip)
            continue
        end = _parse_date(trip.get("end_date"))
        if end is None or end >= today:
            upcoming.append(trip)
        else:
            past.append(trip)
    upcoming.sort(key=lambda t: _parse_date(t.get("start_date")) or datetime.date.min)
    past.sort(
        key=lambda t: _parse_date(t.get("start_date")) or datetime.date.min,
        reverse=True,
    )
    return upcoming, past, broken


def trip_card_meta(trip: dict) -> dict:
    """Compute display-only fields for a trip (days_label, participant_count)."""
    if "error" in trip:
        return trip
    enriched = dict(trip)
    enriched["participant_count"] = len(trip.get("participants", []))
    days_label = ""
    start = _parse_date(trip.get("start_date"))
    if start:
        delta = (start - datetime.date.today()).days
        if delta > 0:
            days_label = f"{delta} day{'s' if delta != 1 else ''} away"
        elif delta == 0:
            days_label = "starting today"
        else:
            days_label = f"{abs(delta)} day{'s' if abs(delta) != 1 else ''} ago"
    enriched["days_label"] = days_label
    return enriched


def load_park_options(parks_json: Path | None = None) -> list[tuple[str, str]]:
    """Return [(slug, name), ...] from parks.json, sorted by name."""
    if parks_json is None:
        parks_json = PARKS_JSON
    try:
        data = json.loads(parks_json.read_text(encoding="utf-8"))
    except Exception:
        return []
    parks = data.get("parks", {})
    return sorted(
        ((slug, info.get("name", slug)) for slug, info in parks.items()),
        key=lambda x: x[1],
    )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


class TripError(Exception):
    """Raised by service mutations; carries an HTTP-friendly status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def create_trip(
    park: str,
    start: datetime.date,
    end: datetime.date,
    participants: list[str],
    trips_dir: Path | None = None,
    template_dir: Path | None = None,
) -> str:
    """Create a new trip directory from the template. Returns the slug."""
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    if template_dir is None:
        template_dir = TEMPLATE_DIR
    park = (park or "").strip()
    if not park:
        raise TripError("park is required", status=400)
    slug = f"{park}-{start.strftime('%Y-%m')}"
    target = trips_dir / slug
    if target.exists():
        raise TripError(f"trip directory '{slug}' already exists", status=409)
    if not template_dir.is_dir():
        raise TripError(f"template dir missing: {template_dir}", status=500)

    try:
        shutil.copytree(template_dir, target)
        participants_yaml = (
            "\n".join(f"  - {p}" for p in participants)
            if participants else "  - "
        )
        trip_md = (
            "---\n"
            f"park: {park}\n"
            f"start_date: {start.isoformat()}\n"
            f"end_date: {end.isoformat()}\n"
            f"participants:\n{participants_yaml}\n"
            "---\n\n"
            f"# {slug}\n\n"
            "New trip — fill in details.\n"
        )
        (target / "trip.md").write_text(trip_md, encoding="utf-8")
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise

    return slug


def save_gear_table(
    slug: str,
    rows: list[list[str]],
    trips_dir: Path | None = None,
) -> None:
    """Replace gear.md's first table with `rows`. Trip is rendered on demand
    by /api/trip/<slug>, so there's no HTML artifact to refresh here."""
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    trip_dir = trips_dir / slug
    if not slug or not trip_dir.is_dir():
        raise TripError("trip not found", status=404)
    gear_md = trip_dir / "gear.md"
    if not gear_md.exists():
        raise TripError("gear.md not found", status=404)
    if not isinstance(rows, list) or any(not isinstance(r, list) for r in rows):
        raise TripError("rows must be a list of lists", status=400)
    text = gear_md.read_text(encoding="utf-8")
    try:
        new_text = replace_first_table(text, rows)
    except ValueError as exc:
        raise TripError(str(exc), status=400) from exc
    gear_md.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Trip rendering payload (consumed by /api/trip/<slug>)
# ---------------------------------------------------------------------------


def load_trip_payload(slug: str, trips_dir: Path | None = None) -> dict:
    """Build the SPA payload for a trip: header HTML + per-section rendered HTML.

    Returned shape:
        {
          "slug": str,
          "frontmatter": dict,
          "park_name": str,
          "header_html": str,
          "sections": [
            {"id": str, "title": str, "html": str, "editable": bool},
            ...
          ],
        }
    """
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    trip_dir = trips_dir / slug
    if not slug or not trip_dir.is_dir():
        raise TripError("trip not found", status=404)

    trip = build_trip.load_trip(trip_dir)
    fm = trip["frontmatter"]
    park_info = build_trip._load_park_info(fm.get("park", ""))
    park_name = park_info.get("name") or fm.get("park", "Trip")

    sections: list[dict] = []
    sections.append({
        "id": "intro", "title": "Overview", "editable": True,
        "html": build_trip.render_section(trip["intro"], "intro") if trip["intro"] else "",
    })
    sections.append({
        "id": "itinerary", "title": "Itinerary", "editable": True,
        "html": build_trip.render_section(trip["itinerary"], "itinerary"),
    })

    route_html = build_trip.render_route_section(trip)
    if route_html:
        sections.append({
            "id": "route", "title": "Route", "editable": False, "html": route_html,
        })

    weather_html = build_trip.render_weather_section(
        fm.get("park", ""), fm.get("start_date", ""), fm.get("end_date", ""),
    )
    if weather_html:
        sections.append({
            "id": "weather", "title": "Weather", "editable": False, "html": weather_html,
        })

    for section_id in ("gear", "food", "packing", "costs"):
        sections.append({
            "id": section_id,
            "title": section_id.capitalize(),
            "editable": True,
            "html": build_trip.render_section(trip[section_id], section_id),
        })

    return {
        "slug": slug,
        "frontmatter": fm,
        "park_name": park_name,
        "header_html": build_trip.render_header(fm),
        "sections": sections,
    }
