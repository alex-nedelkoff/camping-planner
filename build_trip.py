"""Trip rendering library.

Pure functions that turn a trip directory's markdown + YAML into rendered
HTML fragments (header, sections, weather widget, route map). The FastAPI
layer composes these into a single API payload; there is no longer a
self-contained HTML output. See app/services/trips.py:load_trip_payload.
"""

import datetime
import json
import re
from html import escape
from pathlib import Path

import markdown as _md
import yaml

import weather as _weather
import route_map as _route_map
import osm_data as _osm_data
import route_engine as _route_engine

# Weather data provider — defaults to direct Open-Meteo lookup. The FastAPI
# layer swaps this for a SQLite-cached version (see app/services/trips.py).
weather_provider = _weather.get_weather

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECTION_FILES = ["itinerary", "gear", "food", "packing", "costs"]
EDITABLE_SECTIONS = ("intro", "itinerary", "gear", "food", "packing", "costs")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)
TASK_LINE_RE = re.compile(
    r"^(?P<prefix>\s*[-*+]\s+)\[(?P<mark>[ xX])\]\s+(?P<label>.+)$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stringify_dates(obj):
    """Recursively convert date/datetime values to ISO strings in parsed YAML."""
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(item) for item in obj]
    return obj


def _slugify(text: str) -> str:
    """Lowercase, replace non-alphanumerics with hyphens, trim hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _load_park_info(park_slug: str) -> dict:
    """Look up park name + drive time from parks.json. Returns {} if not found."""
    repo_root = Path(__file__).parent
    parks_path = repo_root / "parks.json"
    if not parks_path.exists():
        return {}
    data = json.loads(parks_path.read_text(encoding="utf-8"))
    return data.get("parks", {}).get(park_slug, {})


def render_header(fm: dict) -> str:
    """Render the dark green trip-header block (title, meta, nights table)."""
    park_info = _load_park_info(fm.get("park", ""))
    park_name = park_info.get("name", fm.get("park", "Trip"))
    drive = park_info.get("driveFromAjax", "")
    participants = ", ".join(fm.get("participants", []) or [])
    nights_rows = ""
    for night in fm.get("nights", []) or []:
        nights_rows += (
            f"<tr><td>{night.get('date', '')}</td>"
            f"<td>{night.get('site', '')}</td>"
            f"<td>{night.get('location', '')}</td></tr>"
        )
    nights_table = ""
    if nights_rows:
        nights_table = (
            '<table><thead><tr><th>Date</th><th>Site</th><th>Location</th>'
            f"</tr></thead><tbody>{nights_rows}</tbody></table>"
        )
    return (
        '<header class="trip-header">'
        f'<h1>{park_name} &middot; {fm.get("start_date", "")} → '
        f'{fm.get("end_date", "")}</h1>'
        '<div class="trip-meta">'
        f'<span><strong>Participants:</strong> {participants}</span>'
        + (f'<span><strong>Access:</strong> {fm.get("access_point", "")}</span>'
           if fm.get("access_point") else "")
        + (f'<span><strong>Drive from Ajax:</strong> {drive}</span>'
           if drive else "")
        + '</div>'
        + nights_table
        + '</header>'
    )


# ---------------------------------------------------------------------------
# Loading & rendering
# ---------------------------------------------------------------------------

def load_trip(trip_dir) -> dict:
    """Parse a trip directory.

    Returns dict with keys:
      frontmatter (dict from trip.md YAML),
      intro (str, markdown body of trip.md after frontmatter),
      itinerary, gear, food, packing, costs (str, markdown content),
      route_file (Path or None — prefers route.gpx over route.kml).
    """
    trip_dir = Path(trip_dir)
    trip_md_path = trip_dir / "trip.md"
    if not trip_md_path.exists():
        raise ValueError(f"{trip_md_path}: trip.md not found")
    trip_md = trip_md_path.read_text(encoding="utf-8")

    match = FRONTMATTER_RE.match(trip_md)
    if not match:
        raise ValueError(f"{trip_md_path}: missing YAML frontmatter")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    frontmatter = _stringify_dates(frontmatter)
    intro = match.group(2).strip()

    sections = {}
    for name in SECTION_FILES:
        path = trip_dir / f"{name}.md"
        sections[name] = path.read_text(encoding="utf-8") if path.exists() else ""

    route_file = None
    for ext in ("gpx", "kml"):
        candidate = trip_dir / f"route.{ext}"
        if candidate.exists():
            route_file = candidate
            break

    return {
        "frontmatter": frontmatter,
        "intro": intro,
        "route_file": route_file,
        **sections,
    }


def render_section(md_text: str, section_id: str) -> str:
    """Render markdown to HTML. Task-list items become persistent checkboxes."""
    def replace(match):
        prefix = match.group("prefix")
        mark = match.group("mark")
        label = match.group("label")
        checked = "checked" if mark in "xX" else ""
        key = f"{section_id}--{_slugify(label)}"
        attrs = f'type="checkbox" data-cb-key="{escape(key)}"'
        if checked:
            attrs += " checked"
        return f"{prefix}<input {attrs}> {label}"

    processed = TASK_LINE_RE.sub(replace, md_text)
    return _md.markdown(processed, extensions=["tables", "fenced_code"])


def render_weather_section(park_slug: str, start_date: str, end_date: str) -> str:
    """Render the weather widget HTML using weather.get_weather()."""
    data = weather_provider(
        park_key=park_slug, start_date=start_date, end_date=end_date,
    )
    if data["source"] == "unavailable" or not data["days"]:
        return "<p>Weather data unavailable.</p>"

    label = "Forecast" if data["source"] == "forecast" else "Historical averages"
    rows = []
    for day in data["days"]:
        chance = ""
        if day.get("precip_chance") is not None:
            chance = f"{day['precip_chance']}% rain"
        elif day.get("precip_mm", 0) > 0:
            chance = f"~{day['precip_mm']}mm"
        rows.append(
            f"<tr><td>{day['date']}</td>"
            f"<td>{day.get('icon', '')} {day.get('description', '')}</td>"
            f"<td>{day['high']}&deg;C / {day['low']}&deg;C</td>"
            f"<td>{chance}</td></tr>"
        )

    return (
        f"<p><em>{label}</em></p>"
        '<table><thead><tr><th>Date</th><th>Conditions</th>'
        '<th>High / Low</th><th>Precip</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_route_section(trip) -> str:
    """Render the route map section.

    Three modes:
      1. trip['route_file'] set -> use the user-supplied GPX/KML.
      2. No route file but trip frontmatter has 'nights' + 'access_point' ->
         auto-route from cached OSM data.
      3. Neither -> return ''.
    """
    if trip is None:
        return ""
    if not isinstance(trip, dict):
        data = _route_map.parse_route_file(str(trip))
        return _route_map.generate_map_section(data)

    route_file = trip.get("route_file")
    if route_file is not None:
        data = _route_map.parse_route_file(str(route_file))
        return _route_map.generate_map_section(data)

    fm = trip.get("frontmatter", {}) or {}
    nights = fm.get("nights") or []
    access_point = fm.get("access_point")
    if not (nights and access_point):
        return ""

    try:
        osm = _osm_data.load_killarney_features()
    except FileNotFoundError:
        return ""

    # Optional GPX library — used when a real trace exists for a lake-pair
    # leg. Falls back to OSM portage graph otherwise.
    import gpx_library as _gpx_library
    library = _gpx_library.load_library_index(
        Path(__file__).parent / "routes" / "killarney" / "library"
    )

    route = _route_engine.build_route(
        nights=nights, access_point=access_point, osm=osm, library=library,
    )
    return _render_auto_route(route)


def _render_auto_route(route: dict) -> str:
    """Render the OSM-driven route section: map + per-day estimates table."""
    days = _route_engine.build_day_estimates(route["segments"])

    tracks = []
    for seg in route["segments"]:
        if not seg["geometry"]:
            continue
        track_name = f"{seg['from']} → {seg['to']} ({seg['kind']})"
        tracks.append({
            "name": track_name,
            "points": [tuple(pt) for pt in seg["geometry"]],
        })
    waypoints = [
        {"lat": m["lat"], "lon": m["lon"], "name": m["label"], "desc": ""}
        for m in route.get("markers", [])
    ]
    for seg in route["segments"]:
        if seg["kind"] != "portage" or len(seg["geometry"]) < 2:
            continue
        entry = seg["geometry"][0]
        exit_ = seg["geometry"][-1]
        dist = seg["distance_km"]
        waypoints.append({
            "lat": entry[0], "lon": entry[1],
            "name": f"Portage take-out → {seg['to']}", "desc": f"{dist} km",
        })
        waypoints.append({
            "lat": exit_[0], "lon": exit_[1],
            "name": f"Portage put-in ← {seg['from']}", "desc": f"{dist} km",
        })
    map_html = _route_map.generate_map_section({
        "waypoints": waypoints, "tracks": tracks, "source": "auto",
    })

    rows = []
    total_paddle = 0.0
    total_portage = 0.0
    total_minutes = 0
    for day in days:
        approx_marker = " ⚠" if day["approx"] else ""
        portage_cell = (
            "(approx)" if day["approx"] and day["portage_km"] == 0
            else f"{day['portage_km']} km"
        )
        rows.append(
            f"<tr><td>{day['day']}</td>"
            f"<td>{day['label']}{approx_marker}</td>"
            f"<td>{day['paddle_km']} km</td>"
            f"<td>{portage_cell}</td>"
            f"<td>{day['human_time']}</td></tr>"
        )
        total_paddle += day["paddle_km"]
        total_portage += day["portage_km"]
        total_minutes += day["minutes"]

    rows.append(
        f"<tr><td><strong>Total</strong></td><td></td>"
        f"<td><strong>{round(total_paddle, 1)} km</strong></td>"
        f"<td><strong>{round(total_portage, 1)} km</strong></td>"
        f"<td><strong>{_route_engine.format_human_time(total_minutes)}</strong></td></tr>"
    )

    warnings_html = ""
    if route.get("warnings"):
        items = "".join(f"<li>{w}</li>" for w in route["warnings"])
        warnings_html = f'<div class="warnings"><ul>{items}</ul></div>'

    table_html = (
        "<table><thead><tr><th>Day</th><th>Leg</th>"
        "<th>Paddle</th><th>Portage</th><th>Est. time</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )

    return f"{warnings_html}{map_html}{table_html}"
