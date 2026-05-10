"""
Generate a self-contained trip HTML page from a directory of markdown files.

Usage: python3 build_trip.py trips/<trip-name>/
"""

import argparse
import datetime
import json
import re
import sys
from html import escape
from pathlib import Path

import markdown as _md
import yaml

import weather as _weather
import route_map as _route_map
import osm_data as _osm_data
import route_engine as _route_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECTION_FILES = ["itinerary", "gear", "food", "packing", "costs"]
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)
TASK_LINE_RE = re.compile(
    r"^(?P<prefix>\s*[-*+]\s+)\[(?P<mark>[ xX])\]\s+(?P<label>.+)$",
    re.MULTILINE,
)

_PAGE_CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       max-width: 900px; margin: 0 auto; padding: 1.5rem; color: #222;
       line-height: 1.55; background: #fafafa; }
h1, h2, h3 { color: #1f3a3a; }
h1 { border-bottom: 3px solid #2d5016; padding-bottom: 0.3rem; }
section { background: white; padding: 1.25rem 1.5rem; margin: 1rem 0;
          border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
table { width: 100%; border-collapse: collapse; margin: 0.5rem 0; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }
th { background: #f0f4ee; }
input[type=checkbox] { margin-right: 0.5rem; transform: scale(1.2); }
.trip-header { background: #2d5016; color: white; padding: 1.5rem 1.5rem 1rem;
               border-radius: 10px; margin-bottom: 1rem; }
.trip-header h1 { color: white; border-bottom: none; margin: 0 0 0.5rem; }
.trip-meta { display: flex; gap: 1.5rem; flex-wrap: wrap; opacity: 0.95; }
.trip-header table { background: rgba(0,0,0,0.18); border-radius: 6px;
                     overflow: hidden; margin-top: 1rem; }
.trip-header th, .trip-header td { color: white;
                     border-bottom: 1px solid rgba(255,255,255,0.18);
                     padding: 0.5rem 0.75rem; }
.trip-header th { background: rgba(0,0,0,0.28); font-weight: 600; }
.trip-header tr:last-child td { border-bottom: none; }
.gear-edit-toolbar { margin-top: 0.6rem; display: flex; gap: 0.5rem;
                     align-items: center; flex-wrap: wrap; }
.gear-btn { padding: 0.35rem 0.85rem; background: #2d5016; color: white;
            border: none; border-radius: 5px; cursor: pointer;
            font-size: 0.9rem; font-family: inherit; }
.gear-btn:hover { background: #3a6420; }
.gear-btn.secondary { background: #6b7a5a; }
.gear-btn:disabled { opacity: 0.5; cursor: not-allowed; }
#gear table.editing td { background: #fffbe6; }
#gear table.editing td[contenteditable=true]:focus { outline: 2px solid #2d5016;
                     outline-offset: -2px; background: #fff; }
#gear .row-del { background: transparent; border: none; color: #c00;
                 cursor: pointer; font-size: 1.1rem; padding: 0 0.3rem;
                 margin-left: 0.4rem; }
.gear-status { font-size: 0.9rem; color: #555; margin-left: 0.25rem; }
.gear-status.error { color: #c00; }
@media print { body { background: white; } section { box-shadow: none; }
               .gear-edit-toolbar { display: none; } }
"""

_PAGE_JS = r"""
(function() {
  document.querySelectorAll('input[type=checkbox][data-cb-key]').forEach(function(cb) {
    var key = 'cb:' + cb.dataset.cbKey;
    var saved = localStorage.getItem(key);
    if (saved === '1') cb.checked = true;
    if (saved === '0') cb.checked = false;
    cb.addEventListener('change', function() {
      localStorage.setItem(key, cb.checked ? '1' : '0');
    });
  });
})();

(function() {
  var section = document.getElementById('gear');
  if (!section) return;
  var table = section.querySelector('table');
  if (!table) return;
  var tbody = table.querySelector('tbody');
  if (!tbody) return;

  var slugMatch = location.pathname.match(/\/trips\/([^/]+)\//);
  var tripSlug = slugMatch ? slugMatch[1] : null;

  var ncols = 0;
  var firstRow = tbody.querySelector('tr');
  if (firstRow) ncols = firstRow.cells.length;
  if (!ncols) {
    var theadRow = table.querySelector('thead tr');
    if (theadRow) ncols = theadRow.cells.length;
  }
  if (!ncols) return;

  var toolbar = document.createElement('div');
  toolbar.className = 'gear-edit-toolbar';
  toolbar.innerHTML =
    '<button class="gear-btn" id="gear-edit-btn">Edit gear</button>' +
    '<button class="gear-btn" id="gear-add-btn" hidden>+ Add row</button>' +
    '<button class="gear-btn" id="gear-save-btn" hidden>Save</button>' +
    '<button class="gear-btn secondary" id="gear-cancel-btn" hidden>Cancel</button>' +
    '<span class="gear-status" id="gear-status"></span>';
  table.after(toolbar);

  var editBtn = toolbar.querySelector('#gear-edit-btn');
  var addBtn = toolbar.querySelector('#gear-add-btn');
  var saveBtn = toolbar.querySelector('#gear-save-btn');
  var cancelBtn = toolbar.querySelector('#gear-cancel-btn');
  var status = toolbar.querySelector('#gear-status');

  var snapshot = null;

  function addDeleteButtons() {
    Array.from(tbody.querySelectorAll('tr')).forEach(function(tr) {
      if (tr.querySelector('.row-del')) return;
      var lastCell = tr.cells[tr.cells.length - 1];
      if (!lastCell) return;
      var btn = document.createElement('button');
      btn.className = 'row-del';
      btn.textContent = '×';
      btn.title = 'Delete row';
      btn.hidden = true;
      btn.contentEditable = 'false';
      btn.addEventListener('click', function() { tr.remove(); });
      lastCell.appendChild(btn);
    });
  }

  function setEditing(on) {
    table.classList.toggle('editing', on);
    Array.from(tbody.querySelectorAll('td')).forEach(function(td) {
      td.contentEditable = on ? 'true' : 'false';
    });
    Array.from(tbody.querySelectorAll('.row-del')).forEach(function(b) {
      b.hidden = !on;
    });
    editBtn.hidden = on;
    addBtn.hidden = !on;
    saveBtn.hidden = !on;
    cancelBtn.hidden = !on;
  }

  function rowsAsArray() {
    return Array.from(tbody.querySelectorAll('tr')).map(function(tr) {
      return Array.from(tr.cells).map(function(td) {
        var clone = td.cloneNode(true);
        var del = clone.querySelector('.row-del');
        if (del) del.remove();
        return clone.textContent.replace(/\s+/g, ' ').trim();
      });
    });
  }

  addDeleteButtons();

  editBtn.addEventListener('click', function() {
    snapshot = tbody.innerHTML;
    setEditing(true);
    status.textContent = '';
    status.className = 'gear-status';
  });

  cancelBtn.addEventListener('click', function() {
    if (snapshot != null) tbody.innerHTML = snapshot;
    addDeleteButtons();
    setEditing(false);
    status.textContent = '';
  });

  addBtn.addEventListener('click', function() {
    var tr = document.createElement('tr');
    for (var i = 0; i < ncols; i++) {
      var td = document.createElement('td');
      td.contentEditable = 'true';
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
    addDeleteButtons();
    Array.from(tr.querySelectorAll('.row-del')).forEach(function(b) { b.hidden = false; });
    tr.cells[0].focus();
  });

  saveBtn.addEventListener('click', async function() {
    if (!tripSlug) {
      status.textContent = 'Cannot detect trip slug from URL';
      status.className = 'gear-status error';
      return;
    }
    var rows = rowsAsArray();
    saveBtn.disabled = true;
    cancelBtn.disabled = true;
    status.textContent = 'Saving…';
    status.className = 'gear-status';
    try {
      var r = await fetch('/api/save-gear?trip=' + encodeURIComponent(tripSlug), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rows: rows})
      });
      var j = await r.json();
      if (j.ok) {
        status.textContent = 'Saved ✓ — reloading…';
        setTimeout(function() { location.reload(); }, 600);
      } else {
        status.textContent = 'Error: ' + (j.error || 'unknown');
        status.className = 'gear-status error';
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
      }
    } catch (e) {
      status.textContent = 'Error: ' + e.message + ' (is launch.py running?)';
      status.className = 'gear-status error';
      saveBtn.disabled = false;
      cancelBtn.disabled = false;
    }
  });
})();
"""

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
    data = json.loads(parks_path.read_text())
    return data.get("parks", {}).get(park_slug, {})


def _render_header(fm: dict) -> str:
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
    trip_md = trip_md_path.read_text()

    match = FRONTMATTER_RE.match(trip_md)
    if not match:
        raise ValueError(f"{trip_md_path}: missing YAML frontmatter")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    frontmatter = _stringify_dates(frontmatter)
    intro = match.group(2).strip()

    sections = {}
    for name in SECTION_FILES:
        path = trip_dir / f"{name}.md"
        sections[name] = path.read_text() if path.exists() else ""

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
    data = _weather.get_weather(
        park_key=park_slug, start_date=start_date, end_date=end_date,
    )
    if data["source"] == "unavailable" or not data["days"]:
        return '<section id="weather"><h2>Weather</h2><p>Weather data unavailable.</p></section>'

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
        '<section id="weather"><h2>Weather</h2>'
        f"<p><em>{label}</em></p>"
        '<table><thead><tr><th>Date</th><th>Conditions</th>'
        '<th>High / Low</th><th>Precip</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def render_route_section(trip) -> str:
    """Render the route map section.

    Three modes:
      1. trip['route_file'] set -> use the user-supplied GPX/KML (existing behavior).
      2. No route file but trip frontmatter has 'nights' + 'access_point' ->
         auto-route from cached OSM data.
      3. Neither -> return ''.

    Accepts either a trip dict (preferred, new) or a Path/None (legacy: route_file).
    """
    # Backward-compat: accept the old (route_file) signature where caller passed
    # a Path or None. If caller passes a dict, treat it as the trip dict.
    if trip is None:
        return ""
    if not isinstance(trip, dict):
        # Legacy path-only invocation.
        if trip is None:
            return ""
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

    route = _route_engine.build_route(
        nights=nights, access_point=access_point, osm=osm,
    )
    return _render_auto_route(route)


def _render_auto_route(route: dict) -> str:
    """Render the OSM-driven route section: map + per-day estimates table."""
    days = _route_engine.build_day_estimates(route["segments"])

    # Build a route_map-compatible structure to pass to generate_map_section.
    tracks = []
    for seg in route["segments"]:
        if not seg["geometry"]:
            continue
        # Each segment becomes a track; route_map.py will color-cycle them.
        track_name = f"{seg['from']} → {seg['to']} ({seg['kind']})"
        tracks.append({
            "name": track_name,
            "points": [tuple(pt) for pt in seg["geometry"]],
        })
    # Markers (access point + per-night site centroids) become Leaflet pins.
    waypoints = [
        {"lat": m["lat"], "lon": m["lon"], "name": m["label"], "desc": ""}
        for m in route.get("markers", [])
    ]
    # Add portage entry/exit pins for each portage actually used in the route.
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

    # Per-day estimates table.
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

    return (
        f'<section id="route"><h2>Route</h2>'
        f"{warnings_html}"
        f"{map_html}"
        f"{table_html}"
        f"</section>"
    )

# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def build_html(trip_dir) -> str:
    """Build the full self-contained HTML page for a trip directory."""
    trip = load_trip(trip_dir)
    fm = trip["frontmatter"]

    sections_html = []
    if trip["intro"]:
        sections_html.append(
            f'<section id="intro">{render_section(trip["intro"], "intro")}</section>'
        )
    sections_html.append(
        f'<section id="itinerary"><h2>Itinerary</h2>'
        f'{render_section(trip["itinerary"], "itinerary")}</section>'
    )
    sections_html.append(render_route_section(trip))
    sections_html.append(render_weather_section(
        fm.get("park", ""), fm.get("start_date", ""), fm.get("end_date", ""),
    ))
    sections_html.append(
        f'<section id="gear"><h2>Gear</h2>'
        f'{render_section(trip["gear"], "gear")}</section>'
    )
    sections_html.append(
        f'<section id="food"><h2>Food</h2>'
        f'{render_section(trip["food"], "food")}</section>'
    )
    sections_html.append(
        f'<section id="packing"><h2>Packing</h2>'
        f'{render_section(trip["packing"], "packing")}</section>'
    )
    sections_html.append(
        f'<section id="costs"><h2>Costs</h2>'
        f'{render_section(trip["costs"], "costs")}</section>'
    )

    body = _render_header(fm) + "\n".join(s for s in sections_html if s)
    title = (
        f'{_load_park_info(fm.get("park", "")).get("name", "Trip")} '
        f'{fm.get("start_date", "")}'
    )
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title>'
        f'<style>{_PAGE_CSS}</style>'
        '</head><body>'
        f'{body}'
        f'<script>{_PAGE_JS}</script>'
        '</body></html>'
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trip_dir", help="Path to trip directory (contains trip.md)")
    parser.add_argument(
        "--refresh-osm", action="store_true",
        help="Re-fetch the Killarney OSM cache from Overpass before rendering.",
    )
    args = parser.parse_args(argv)

    if args.refresh_osm:
        _osm_data.refresh_killarney_cache()

    trip_dir = Path(args.trip_dir)
    html = build_html(trip_dir)
    out_path = trip_dir / "trip.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
