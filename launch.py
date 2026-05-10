"""
Local trip launcher. Starts an HTTP server with an index UI and action endpoints.

Usage:
    python launch.py [--port 8000] [--no-browser]
"""

import argparse
import datetime
import http.server
import json
import os
import re
import shutil
import socketserver
import sys
import threading
import urllib.parse
import webbrowser
from html import escape
from pathlib import Path

import yaml

import build_trip
import ontario_parks


_MD_TABLE_RE = re.compile(
    r"(^\|.+\|[ \t]*\n\|[\s|:\-]+\|[ \t]*\n)((?:^\|.*\|[ \t]*\n)*)",
    re.MULTILINE,
)


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


REPO_ROOT = Path(__file__).resolve().parent
TRIPS_DIR = REPO_ROOT / "trips"
TEMPLATE_DIR = REPO_ROOT / "templates" / "trip-template"
PARKS_JSON = REPO_ROOT / "parks.json"


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


def scan_trips():
    """Return a list of trip metadata dicts from trips/*/trip.md."""
    if not TRIPS_DIR.exists():
        return []
    trips = []
    for trip_dir in sorted(TRIPS_DIR.iterdir()):
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


def split_trips(trips):
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


def load_park_options():
    """Return a list of (slug, name) tuples from parks.json, sorted by name."""
    try:
        data = json.loads(PARKS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    parks = data.get("parks", {})
    return sorted(
        ((slug, info.get("name", slug)) for slug, info in parks.items()),
        key=lambda x: x[1],
    )


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

INDEX_CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       max-width: 900px; margin: 0 auto; padding: 1.5rem; color: #222;
       line-height: 1.55; background: #fafafa; }
h1, h2, h3 { color: #1f3a3a; }
h2 { border-bottom: 2px solid #2d5016; padding-bottom: 0.25rem; margin-top: 0; }
section { background: white; padding: 1.25rem 1.5rem; margin: 1rem 0;
          border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.trip-header { background: #2d5016; color: white; padding: 1.25rem 1.5rem;
               border-radius: 10px; margin-bottom: 1rem; display: flex;
               justify-content: space-between; align-items: center; gap: 1rem;
               flex-wrap: wrap; }
.trip-header h1 { color: white; margin: 0; }
.card { padding: 0.9rem 1rem; margin: 0.75rem 0; border: 1px solid #e3e3e3;
        border-radius: 8px; background: #fff; }
.card h3 { margin: 0 0 0.3rem; }
.card.error { border-color: #d99; background: #fdf3f3; }
.meta { color: #555; font-size: 0.92rem; margin-bottom: 0.6rem; }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.btn { display: inline-block; padding: 0.45rem 0.9rem; background: #2d5016;
       color: white; border: none; border-radius: 6px; cursor: pointer;
       text-decoration: none; font-size: 0.92rem; font-family: inherit; }
.btn:hover { background: #3a6420; }
.btn:disabled { opacity: 0.6; cursor: wait; }
.btn.secondary { background: #6b7a5a; }
.btn.secondary:hover { background: #7d8d6c; }
form label { display: block; margin: 0.6rem 0; font-size: 0.95rem; }
form input, form select { padding: 0.4rem; border: 1px solid #ccc;
                          border-radius: 4px; min-width: 220px;
                          margin-left: 0.5rem; font-family: inherit; }
.warn { color: #8a5a00; background: #fff8e1; padding: 0.5rem 0.75rem;
        border-left: 3px solid #d9a000; border-radius: 4px; margin: 0 0 0.75rem; }
.empty { color: #888; font-style: italic; }
.status { margin-left: 0.75rem; font-size: 0.9rem; color: #555; }
.status.error { color: #c00; }
table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }
th { background: #f0f4ee; }
"""

INDEX_JS = r"""
function toggleNewTrip() {
  var s = document.getElementById('new-trip');
  s.hidden = !s.hidden;
}

async function rebuild(btn, name) {
  var orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rebuilding…';
  try {
    var r = await fetch('/api/rebuild?trip=' + encodeURIComponent(name), {method: 'POST'});
    var j = await r.json();
    btn.textContent = j.ok ? 'Rebuilt ✓' : 'Failed';
  } catch (e) {
    btn.textContent = 'Error';
  }
  setTimeout(function() { btn.textContent = orig; btn.disabled = false; }, 2000);
}

async function createTrip(ev) {
  ev.preventDefault();
  var f = ev.target;
  var status = document.getElementById('new-trip-status');
  status.className = 'status';
  status.textContent = 'Creating…';
  var body = {
    park: f.park.value,
    start: f.start.value,
    end: f.end.value,
    participants: f.participants.value.split(',').map(function(s){return s.trim();}).filter(Boolean),
  };
  try {
    var r = await fetch('/api/new-trip', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    var j = await r.json();
    if (j.ok) {
      status.textContent = 'Created ' + j.trip_dir + ' — reloading…';
      setTimeout(function(){ location.reload(); }, 800);
    } else {
      status.className = 'status error';
      status.textContent = 'Error: ' + (j.error || 'unknown');
    }
  } catch (e) {
    status.className = 'status error';
    status.textContent = 'Error: ' + e.message;
  }
}

async function checkAvail(ev) {
  ev.preventDefault();
  var f = ev.target;
  var btn = document.getElementById('avail-btn');
  var out = document.getElementById('avail-results');
  btn.disabled = true;
  btn.textContent = 'Checking…';
  out.innerHTML = '<p>Checking — this can take 5–15 seconds…</p>';
  var params = new URLSearchParams({park: f.park.value, start: f.start.value, end: f.end.value});
  try {
    var r = await fetch('/api/availability?' + params.toString());
    var j = await r.json();
    if (j.ok) {
      var html = '<h3>' + escapeHtml(j.park_name) + ': ' + j.total_available + ' site(s) available</h3>';
      var keys = Object.keys(j.campgrounds || {});
      if (keys.length) {
        html += '<table><thead><tr><th>Campground</th><th>Available / Total</th></tr></thead><tbody>';
        keys.forEach(function(name) {
          var info = j.campgrounds[name];
          html += '<tr><td>' + escapeHtml(name) + '</td><td>' + info.available + ' / ' + info.total + '</td></tr>';
        });
        html += '</tbody></table>';
      }
      out.innerHTML = html;
    } else {
      out.innerHTML = '<p class="status error">Error: ' + escapeHtml(j.error || 'unknown') + '</p>';
    }
  } catch (e) {
    out.innerHTML = '<p class="status error">Error: ' + escapeHtml(e.message) + '</p>';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Check';
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}
"""


def _trip_card(trip):
    if "error" in trip:
        return (
            f'<div class="card error">'
            f'<strong>{escape(trip["name"])}</strong>: {escape(trip["error"])}'
            f'</div>'
        )
    days_label = ""
    start = _parse_date(trip["start_date"])
    if start:
        delta = (start - datetime.date.today()).days
        if delta > 0:
            days_label = f"{delta} day{'s' if delta != 1 else ''} away"
        elif delta == 0:
            days_label = "starting today"
        else:
            days_label = f"{abs(delta)} day{'s' if abs(delta) != 1 else ''} ago"
    name = escape(trip["name"])
    return (
        f'<div class="card">'
        f'<h3>{escape(trip["park_name"])}</h3>'
        f'<div class="meta">{escape(trip["start_date"])} → {escape(trip["end_date"])}'
        f' · {len(trip["participants"])} participant'
        f'{"s" if len(trip["participants"]) != 1 else ""}'
        + (f' · {escape(days_label)}' if days_label else '') +
        f'</div>'
        f'<div class="actions">'
        f'<a class="btn" href="/trips/{name}/trip.html" target="_blank">Open Trip</a>'
        f'<button class="btn secondary" onclick="rebuild(this, \'{name}\')">Rebuild</button>'
        f'</div></div>'
    )


def render_index():
    trips = scan_trips()
    upcoming, past, broken = split_trips(trips)
    park_options = "".join(
        f'<option value="{escape(slug)}">{escape(name)}</option>'
        for slug, name in load_park_options()
    )
    upcoming_html = (
        "".join(_trip_card(t) for t in upcoming)
        or '<p class="empty">No upcoming trips.</p>'
    )
    past_html = (
        "".join(_trip_card(t) for t in past)
        or '<p class="empty">No past trips.</p>'
    )
    broken_section = ""
    if broken:
        broken_section = (
            '<section><h2>⚠ Trips with errors</h2>'
            + "".join(_trip_card(t) for t in broken)
            + '</section>'
        )
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Camping Trips</title>
<style>{INDEX_CSS}</style>
</head><body>
<header class="trip-header">
  <h1>🏕 Camping Trips</h1>
  <button class="btn" onclick="toggleNewTrip()">+ New Trip</button>
</header>

<section id="new-trip" hidden>
  <h2>New Trip</h2>
  <form onsubmit="createTrip(event)">
    <label>Park
      <select name="park" required>
        <option value="">— select —</option>
        {park_options}
      </select>
    </label>
    <label>Start date <input type="date" name="start" required></label>
    <label>End date <input type="date" name="end" required></label>
    <label>Participants (comma separated)
      <input type="text" name="participants" placeholder="Alex, Jordan">
    </label>
    <button type="submit" class="btn">Create</button>
    <span id="new-trip-status" class="status"></span>
  </form>
</section>

{broken_section}

<section>
  <h2>Upcoming</h2>
  {upcoming_html}
</section>

<section>
  <h2>Past</h2>
  {past_html}
</section>

<section>
  <h2>Check Park Availability</h2>
  <p class="warn">⚠ Ontario Parks rate-limits aggressively (Azure WAF will ban your IP for 30+ min after ~15 rapid requests). One check at a time, please.</p>
  <form onsubmit="checkAvail(event)">
    <label>Park
      <select name="park" required>
        <option value="">— select —</option>
        {park_options}
      </select>
    </label>
    <label>Start <input type="date" name="start" required></label>
    <label>End <input type="date" name="end" required></label>
    <button type="submit" class="btn" id="avail-btn">Check</button>
  </form>
  <div id="avail-results"></div>
</section>

<script>{INDEX_JS}</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class LauncherHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_index()
            return
        if path == "/api/availability":
            self._handle_availability()
            return
        super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/rebuild":
            self._handle_rebuild()
            return
        if path == "/api/new-trip":
            self._handle_new_trip()
            return
        if path == "/api/save-gear":
            self._handle_save_gear()
            return
        self.send_error(404, "Not found")

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[launch] {fmt % args}\n")

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_index(self):
        try:
            html = render_index()
        except Exception as exc:
            html = (
                "<!DOCTYPE html><html><body>"
                f"<h1>Error rendering index</h1><pre>{escape(str(exc))}</pre>"
                "</body></html>"
            )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_rebuild(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        trip = (params.get("trip") or [""])[0]
        trip_dir = TRIPS_DIR / trip
        if not trip or not trip_dir.is_dir():
            self._send_json({"ok": False, "error": "trip not found"}, status=404)
            return
        try:
            html = build_trip.build_html(trip_dir)
            (trip_dir / "trip.html").write_text(html, encoding="utf-8")
            self._send_json({"ok": True, "message": f"rebuilt {trip}"})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def _handle_new_trip(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            self._send_json({"ok": False, "error": f"bad json: {exc}"}, status=400)
            return
        park = (body.get("park") or "").strip()
        start = (body.get("start") or "").strip()
        end = (body.get("end") or "").strip()
        participants = body.get("participants") or []
        if not (park and start and end):
            self._send_json(
                {"ok": False, "error": "park, start, end required"}, status=400,
            )
            return
        try:
            start_date = datetime.date.fromisoformat(start)
            datetime.date.fromisoformat(end)
        except ValueError as exc:
            self._send_json({"ok": False, "error": f"bad date: {exc}"}, status=400)
            return
        slug = f"{park}-{start_date.strftime('%Y-%m')}"
        target = TRIPS_DIR / slug
        if target.exists():
            self._send_json(
                {"ok": False, "error": f"trip directory '{slug}' already exists"},
                status=409,
            )
            return
        if not TEMPLATE_DIR.is_dir():
            self._send_json(
                {"ok": False, "error": f"template dir missing: {TEMPLATE_DIR}"},
                status=500,
            )
            return
        try:
            shutil.copytree(TEMPLATE_DIR, target)
            participants_yaml = (
                "\n".join(f"  - {p}" for p in participants)
                if participants else "  - "
            )
            trip_md = (
                "---\n"
                f"park: {park}\n"
                f"start_date: {start}\n"
                f"end_date: {end}\n"
                f"participants:\n{participants_yaml}\n"
                "---\n\n"
                f"# {slug}\n\n"
                "New trip — fill in details.\n"
            )
            (target / "trip.md").write_text(trip_md, encoding="utf-8")
            self._send_json({"ok": True, "trip_dir": slug})
        except Exception as exc:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def _handle_save_gear(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        trip = (params.get("trip") or [""])[0]
        trip_dir = TRIPS_DIR / trip
        if not trip or not trip_dir.is_dir():
            self._send_json({"ok": False, "error": "trip not found"}, status=404)
            return
        gear_md = trip_dir / "gear.md"
        if not gear_md.exists():
            self._send_json({"ok": False, "error": "gear.md not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            self._send_json({"ok": False, "error": f"bad json: {exc}"}, status=400)
            return
        rows = body.get("rows")
        if not isinstance(rows, list) or any(not isinstance(r, list) for r in rows):
            self._send_json(
                {"ok": False, "error": "rows must be a list of lists"}, status=400,
            )
            return
        try:
            text = gear_md.read_text(encoding="utf-8")
            new_text = replace_first_table(text, rows)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        try:
            gear_md.write_text(new_text, encoding="utf-8")
            html = build_trip.build_html(trip_dir)
            (trip_dir / "trip.html").write_text(html, encoding="utf-8")
            self._send_json({"ok": True})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def _handle_availability(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        park = (params.get("park") or [""])[0]
        start = (params.get("start") or [""])[0]
        end = (params.get("end") or [""])[0]
        if not (park and start and end):
            self._send_json(
                {"ok": False, "error": "park, start, end required"}, status=400,
            )
            return
        try:
            result = ontario_parks.check_park(park, start, end)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
            return
        campgrounds = {}
        for cg_id, cg_info in (result.get("campgrounds") or {}).items():
            if not isinstance(cg_info, dict) or "error" in cg_info:
                continue
            name = ontario_parks.resolve_map_name(cg_id)
            campgrounds[name] = {
                "available": cg_info.get("available_count", 0),
                "total": cg_info.get("total_count", 0),
            }
        self._send_json({
            "ok": True,
            "park_name": result.get("park_name"),
            "total_available": result.get("total_available", 0),
            "campgrounds": campgrounds,
        })


# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------

class _ReusableThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open the browser.",
    )
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)

    server = _ReusableThreadingServer(("127.0.0.1", args.port), LauncherHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Camping Planner UI -> {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=[url]).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
