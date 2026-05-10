"""
Trip Planner — Generate camping trip plans from a collaborative Google Sheet.

Uses `gws` CLI for Google Workspace operations (Sheets, Drive).
Generates self-contained HTML trip pages from Sheet data.
"""

import json
import subprocess
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from html import escape

PROJECT_DIR = Path(__file__).parent
PARKS_FILE = PROJECT_DIR / "parks.json"
ACTIVITIES_FILE = PROJECT_DIR / "park_activities.json"

# Tab names in the trip planning sheet
TABS = {
    "info": "Trip Info",
    "participants": "Participants",
    "route": "Route",
    "gear": "Gear",
    "food": "Shared Food",
    "itinerary": "Itinerary",
    "costs": "Costs",
    "packing": "Packing Checklist",
}


# ── gws helpers ──────────────────────────────────────────────────────────────

def gws_json(args: list[str], input_json: dict = None) -> dict:
    """Run a gws command and return parsed JSON output."""
    cmd = ["gws"] + args + ["--format", "json"]
    if input_json is not None:
        cmd += ["--json", json.dumps(input_json)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gws error: {result.stderr.strip()}")
    return json.loads(result.stdout)


def gws_raw(args: list[str], input_json: dict = None, upload: str = None) -> str:
    """Run a gws command and return raw output."""
    cmd = ["gws"] + args + ["--format", "json"]
    if input_json is not None:
        cmd += ["--json", json.dumps(input_json)]
    if upload:
        cmd += ["--upload", upload]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # gws writes info messages (like "Using keyring backend") to stderr even on success
    if result.returncode != 0:
        raise RuntimeError(f"gws error (exit {result.returncode}): {result.stderr.strip()}")
    return result.stdout


# ── Sheet operations ─────────────────────────────────────────────────────────

def create_trip_sheet(title: str) -> dict:
    """Create a new trip planning sheet with all tabs. Returns {id, url}."""
    # Create spreadsheet with multiple sheets
    body = {
        "properties": {"title": title},
        "sheets": [
            {"properties": {"title": tab_name, "index": i}}
            for i, tab_name in enumerate(TABS.values())
        ],
    }
    data = gws_json(["sheets", "spreadsheets", "create"], body)
    sheet_id = data["spreadsheetId"]
    sheet_url = data["spreadsheetUrl"]

    # Write headers for each tab
    _write_tab_headers(sheet_id)

    return {"id": sheet_id, "url": sheet_url}


def _write_tab_headers(sheet_id: str):
    """Write header rows to all tabs."""
    headers = {
        TABS["info"]: [["Field", "Value"]],
        TABS["participants"]: [["Name", "Driving?", "Car Capacity", "Dietary", "Phone", "Notes"]],
        TABS["route"]: [["Day", "Site / Location", "Lake / Area", "Travel", "Notes"]],
        TABS["gear"]: [["Item", "Assigned To", "Status", "Notes"]],
        TABS["food"]: [["Item", "Brought By", "Meal", "Serves", "Notes"]],
        TABS["itinerary"]: [["Day", "Time", "Activity", "Notes"]],
        TABS["costs"]: [["Expense", "Paid By", "Amount", "Split Between", "Per Person"]],
        TABS["packing"]: [["Category", "Item", "Packed?"]],
    }

    # Batch update all headers
    value_ranges = []
    for tab_name, rows in headers.items():
        value_ranges.append({
            "range": f"'{tab_name}'!A1",
            "values": rows,
        })

    gws_json(
        ["sheets", "spreadsheets", "values", "batchUpdate",
         "--params", json.dumps({"spreadsheetId": sheet_id})],
        {"valueInputOption": "RAW", "data": value_ranges},
    )


def write_tab_data(sheet_id: str, tab_key: str, rows: list[list[str]], start_row: int = 2):
    """Write data rows to a tab (after headers)."""
    tab_name = TABS[tab_key]
    range_str = f"'{tab_name}'!A{start_row}"
    gws_raw(
        ["sheets", "spreadsheets", "values", "update",
         "--params", json.dumps({
             "spreadsheetId": sheet_id,
             "range": range_str,
             "valueInputOption": "USER_ENTERED",
         })],
        {"values": rows},
    )


def read_tab(sheet_id: str, tab_key: str) -> list[list[str]]:
    """Read all data from a tab. Returns list of rows (including header)."""
    tab_name = TABS[tab_key]
    data = gws_json(
        ["sheets", "spreadsheets", "values", "get",
         "--params", json.dumps({
             "spreadsheetId": sheet_id,
             "range": f"'{tab_name}'",
         })]
    )
    return data.get("values", [])


def read_all_tabs(sheet_id: str) -> dict[str, list[list[str]]]:
    """Read all tabs from a trip sheet. Returns {tab_key: rows}."""
    result = {}
    for key in TABS:
        try:
            result[key] = read_tab(sheet_id, key)
        except Exception:
            result[key] = []
    return result


def parse_trip_info(rows: list[list[str]]) -> dict:
    """Parse the Trip Info tab into a dict."""
    info = {}
    for row in rows[1:]:  # skip header
        if len(row) >= 2:
            info[row[0].strip()] = row[1].strip()
    return info


def parse_table(rows: list[list[str]]) -> list[dict]:
    """Parse a tab with headers into a list of dicts."""
    if len(rows) < 2:
        return []
    headers = [h.strip() for h in rows[0]]
    result = []
    for row in rows[1:]:
        entry = {}
        for i, header in enumerate(headers):
            entry[header] = row[i].strip() if i < len(row) else ""
        if any(entry.values()):
            result.append(entry)
    return result


# ── Sheet template population ────────────────────────────────────────────────

DEFAULT_PACKING_LIST = [
    ["Shelter", "Tent"],
    ["Shelter", "Sleeping bag"],
    ["Shelter", "Sleeping pad / air mattress"],
    ["Shelter", "Pillow"],
    ["Clothing", "Rain jacket"],
    ["Clothing", "Warm layers / fleece"],
    ["Clothing", "Hiking boots"],
    ["Clothing", "Sandals / camp shoes"],
    ["Clothing", "Extra socks"],
    ["Clothing", "Swimsuit"],
    ["Clothing", "Hat / sunglasses"],
    ["Cooking", "Plates / bowls / cups"],
    ["Cooking", "Utensils (fork, knife, spoon)"],
    ["Cooking", "Pot / pan"],
    ["Cooking", "Lighter / matches"],
    ["Cooking", "Dish soap + sponge"],
    ["Cooking", "Trash bags"],
    ["Cooking", "Water bottles"],
    ["Hygiene", "Toothbrush + toothpaste"],
    ["Hygiene", "Sunscreen"],
    ["Hygiene", "Bug spray"],
    ["Hygiene", "Toilet paper"],
    ["Hygiene", "Hand sanitizer"],
    ["Hygiene", "Towel"],
    ["Safety", "First aid kit"],
    ["Safety", "Headlamp / flashlight"],
    ["Safety", "Pocket knife / multi-tool"],
    ["Safety", "Whistle"],
    ["Misc", "Camp chair"],
    ["Misc", "Firewood / firestarter"],
    ["Misc", "Cards / games"],
    ["Misc", "Phone charger / battery pack"],
    ["Misc", "Cash (for park store)"],
    ["Misc", "Park reservation confirmation"],
]


def populate_template(sheet_id: str, trip_info: dict = None,
                      participants: list[dict] = None):
    """Fill in a trip sheet with provided data."""
    if trip_info:
        rows = [[k, v] for k, v in trip_info.items()]
        write_tab_data(sheet_id, "info", rows)

    if participants:
        rows = [
            [p.get("name", ""), p.get("driving", ""), p.get("car_capacity", ""),
             p.get("dietary", ""), p.get("phone", ""), p.get("notes", "")]
            for p in participants
        ]
        write_tab_data(sheet_id, "participants", rows)

    # Always populate packing checklist
    packing_rows = [[cat, item, ""] for cat, item in DEFAULT_PACKING_LIST]
    write_tab_data(sheet_id, "packing", packing_rows)


# ── HTML generation ──────────────────────────────────────────────────────────

def generate_html(sheet_id: str, output_path: str = None, route_file: str = None) -> str:
    """Read a trip sheet and generate a self-contained HTML trip page."""
    tabs = read_all_tabs(sheet_id)

    trip_info = parse_trip_info(tabs.get("info", []))
    participants = parse_table(tabs.get("participants", []))
    route = parse_table(tabs.get("route", []))
    gear = parse_table(tabs.get("gear", []))
    food = parse_table(tabs.get("food", []))
    itinerary = parse_table(tabs.get("itinerary", []))
    costs = parse_table(tabs.get("costs", []))
    packing = parse_table(tabs.get("packing", []))

    park_name = trip_info.get("Park", "Camping Trip")
    start_date = trip_info.get("Start Date", "")
    end_date = trip_info.get("End Date", "")
    park_key = trip_info.get("Park Key", "")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

    # Load activities if available
    activities = {}
    if ACTIVITIES_FILE.exists():
        with open(ACTIVITIES_FILE) as f:
            all_activities = json.load(f)
        activities = all_activities.get(park_key, {})

    # Try to get park info from parks.json
    park_data = {}
    if PARKS_FILE.exists():
        with open(PARKS_FILE) as f:
            parks = json.load(f).get("parks", {})
        park_data = parks.get(park_key, {})

    # Build maps link
    maps_query = f"{park_name} Ontario Provincial Park"
    maps_link = f"https://www.google.com/maps/dir/Ajax,+ON/{maps_query.replace(' ', '+')}"

    # Fetch weather data
    weather_data = {"source": "unavailable", "days": []}
    if start_date and end_date:
        try:
            from weather import get_weather
            weather_data = get_weather(park_key=park_key, start_date=start_date, end_date=end_date)
        except Exception:
            pass

    # Parse route file (KML/GPX) if provided
    route_map_html = ""
    if route_file:
        try:
            from route_map import parse_route_file, generate_map_section
            route_data = parse_route_file(route_file)
            route_map_html = generate_map_section(route_data)
        except Exception as e:
            print(f"Warning: could not parse route file: {e}")

    html = _render_html(
        trip_info=trip_info,
        participants=participants,
        route=route,
        gear=gear,
        food=food,
        itinerary=itinerary,
        costs=costs,
        packing=packing,
        activities=activities,
        park_data=park_data,
        maps_link=maps_link,
        sheet_url=sheet_url,
        weather=weather_data,
        route_map_html=route_map_html,
    )

    if output_path:
        Path(output_path).write_text(html)
        print(f"Generated: {output_path}")

    return html


def _render_html(**ctx) -> str:
    """Render the full HTML trip page."""
    ti = ctx["trip_info"]
    e = escape

    park_name = e(ti.get("Park", "Camping Trip"))
    dates = f'{e(ti.get("Start Date", ""))} to {e(ti.get("End Date", ""))}'
    title = f"{park_name} — {dates}"

    # Build sections
    participants_html = _section_participants(ctx["participants"])
    getting_there_html = _section_getting_there(ctx["trip_info"], ctx["maps_link"])
    weather_html = _section_weather(ctx.get("weather", {}))
    route_html = _section_route(ctx.get("route", []))
    itinerary_html = _section_itinerary(ctx["itinerary"])
    activities_html = _section_activities(ctx["activities"])
    gear_html = _section_gear(ctx["gear"])
    food_html = _section_food(ctx["food"])
    costs_html = _section_costs(ctx["costs"], ctx["participants"])
    packing_html = _section_packing(ctx["packing"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
{CSS}
</style>
</head>
<body>
<header>
<h1>{park_name}</h1>
<p class="subtitle">{dates}</p>
<p class="meta">
{e(ti.get("Campground", ""))} {("· Site " + e(ti.get("Site Number", ""))) if ti.get("Site Number") else ""}
· {len(ctx["participants"])} people
</p>
<p class="sheet-link"><a href="{e(ctx['sheet_url'])}" target="_blank">Edit Trip Sheet</a></p>
</header>
<main>
{participants_html}
{getting_there_html}
{weather_html}
{route_html}
{ctx.get("route_map_html", "")}
{itinerary_html}
{activities_html}
{gear_html}
{food_html}
{costs_html}
{packing_html}
</main>
<footer>
<p>Generated {datetime.now().strftime("%b %d, %Y")} · <a href="{e(ctx['sheet_url'])}" target="_blank">Edit in Google Sheets</a></p>
</footer>
<script>
{JS}
</script>
</body>
</html>"""


def _section_participants(participants):
    if not participants:
        return ""
    rows = ""
    for p in participants:
        rows += f"""<tr>
<td>{escape(p.get('Name',''))}</td>
<td>{escape(p.get('Driving?',''))}</td>
<td>{escape(p.get('Dietary',''))}</td>
<td>{escape(p.get('Phone',''))}</td>
<td>{escape(p.get('Notes',''))}</td>
</tr>"""
    return f"""<section id="participants">
<h2>Who's Coming</h2>
<table>
<thead><tr><th>Name</th><th>Driving?</th><th>Dietary</th><th>Phone</th><th>Notes</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</section>"""


def _section_getting_there(info, maps_link):
    meeting = info.get("Meeting Point", "")
    departure = info.get("Departure Time", "")
    drive = info.get("Drive Time", "")
    checkin = info.get("Check-in Time", "")
    checkout = info.get("Check-out Time", "")

    items = []
    if meeting:
        items.append(f"<li><strong>Meeting point:</strong> {escape(meeting)}</li>")
    if departure:
        items.append(f"<li><strong>Departure:</strong> {escape(departure)}</li>")
    if drive:
        items.append(f"<li><strong>Drive time:</strong> {escape(drive)}</li>")
    if checkin:
        items.append(f"<li><strong>Check-in:</strong> {escape(checkin)}</li>")
    if checkout:
        items.append(f"<li><strong>Check-out:</strong> {escape(checkout)}</li>")

    return f"""<section id="getting-there">
<h2>Getting There</h2>
<ul>{''.join(items)}</ul>
<a href="{escape(maps_link)}" target="_blank" class="btn">Open in Google Maps</a>
</section>"""


def _section_weather(weather):
    if not weather or not weather.get("days"):
        return ""
    source = weather["source"]
    label = "Forecast" if source == "forecast" else "Historical Averages"
    hint = "" if source == "forecast" else " (typical conditions for these dates)"

    cards = ""
    for day in weather["days"]:
        icon = day.get("icon", "")
        desc = day.get("description", "")
        high = day.get("high", "?")
        low = day.get("low", "?")
        precip = day.get("precip_mm", 0)
        chance = day.get("precip_chance")

        precip_str = ""
        if chance is not None:
            precip_str = f'<span class="precip">{chance}% rain</span>'
        elif precip > 0:
            precip_str = f'<span class="precip">~{precip}mm</span>'

        date_str = day.get("date", "")
        # Format date nicely
        try:
            from datetime import datetime as dt
            d = dt.strptime(date_str, "%Y-%m-%d")
            date_str = d.strftime("%a %b %d")
        except Exception:
            pass

        cards += f"""<div class="weather-card">
<div class="weather-icon">{icon}</div>
<div class="weather-date">{escape(date_str)}</div>
<div class="weather-temp">{high}° / {low}°C</div>
<div class="weather-desc">{escape(desc)}</div>
{precip_str}
</div>"""

    return f"""<section id="weather">
<h2>{escape(label)}</h2>
<p class="hint">{escape(hint)}</p>
<div class="weather-grid">{cards}</div>
</section>"""


def _section_route(route):
    if not route:
        return ""
    html = '<div class="route-timeline">'
    for i, stop in enumerate(route):
        day = stop.get("Day", "")
        site = stop.get("Site / Location", "")
        lake = stop.get("Lake / Area", "")
        travel = stop.get("Travel", "")
        notes = stop.get("Notes", "")

        connector = '<div class="route-connector"></div>' if i < len(route) - 1 else ""

        html += f"""<div class="route-stop">
<div class="route-marker">{"🏕️" if i > 0 and i < len(route) - 1 else "🚗" if i == 0 else "🏁"}</div>
<div class="route-details">
<strong>{escape(day)}</strong> — {escape(site)}
{f'<span class="route-lake">{escape(lake)}</span>' if lake else ''}
{f'<div class="route-travel">{escape(travel)}</div>' if travel else ''}
{f'<div class="note">{escape(notes)}</div>' if notes else ''}
</div>
</div>
{connector}"""
    html += "</div>"

    return f"""<section id="route">
<h2>Route</h2>
{html}
</section>"""


def _section_itinerary(itinerary):
    if not itinerary:
        return ""
    current_day = ""
    html = ""
    for item in itinerary:
        day = item.get("Day", "")
        if day != current_day:
            if current_day:
                html += "</div>"
            current_day = day
            html += f'<div class="day-block"><h3>{escape(day)}</h3>'
        time_str = item.get("Time", "")
        activity = item.get("Activity", "")
        notes = item.get("Notes", "")
        html += f'<div class="event"><span class="time">{escape(time_str)}</span> <strong>{escape(activity)}</strong>'
        if notes:
            html += f' <span class="note">— {escape(notes)}</span>'
        html += '</div>'
    if current_day:
        html += "</div>"

    return f"""<section id="itinerary">
<h2>Itinerary</h2>
{html}
</section>"""


def _section_activities(activities):
    if not activities:
        return ""
    html = ""
    hikes = activities.get("hikes", [])
    if hikes:
        html += "<h3>Hikes</h3><div class='activity-list'>"
        for h in hikes:
            html += f"""<div class="activity-card">
<strong>{escape(h['name'])}</strong>
<span class="badge">{escape(h.get('difficulty',''))}</span>
<span class="badge">{escape(h.get('distance',''))}</span>
<span class="badge">{escape(h.get('time',''))}</span>
<p>{escape(h.get('notes',''))}</p>
</div>"""
        html += "</div>"

    swimming = activities.get("swimming", [])
    if swimming:
        html += "<h3>Swimming</h3><ul>"
        for s in swimming:
            html += f"<li>{escape(s)}</li>"
        html += "</ul>"

    paddling = activities.get("paddling", [])
    if paddling:
        html += "<h3>Paddling</h3><ul>"
        for p in paddling:
            html += f"<li>{escape(p)}</li>"
        html += "</ul>"

    tips = activities.get("tips", [])
    if tips:
        html += "<h3>Tips</h3><ul>"
        for t in tips:
            html += f"<li>{escape(t)}</li>"
        html += "</ul>"

    return f"""<section id="activities">
<h2>Activities</h2>
{html}
</section>"""


def _section_gear(gear):
    if not gear:
        return ""
    rows = ""
    for g in gear:
        status = g.get("Status", "")
        cls = "bringing" if status.lower() == "bringing" else "needed" if status.lower() == "needed" else ""
        rows += f"""<tr class="{cls}">
<td>{escape(g.get('Item',''))}</td>
<td>{escape(g.get('Assigned To',''))}</td>
<td>{escape(status)}</td>
<td>{escape(g.get('Notes',''))}</td>
</tr>"""
    return f"""<section id="gear">
<h2>Gear Assignments</h2>
<table>
<thead><tr><th>Item</th><th>Assigned To</th><th>Status</th><th>Notes</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</section>"""


def _section_food(food):
    if not food:
        return ""
    rows = ""
    for f_item in food:
        rows += f"""<tr>
<td>{escape(f_item.get('Item',''))}</td>
<td>{escape(f_item.get('Brought By',''))}</td>
<td>{escape(f_item.get('Meal',''))}</td>
<td>{escape(f_item.get('Serves',''))}</td>
<td>{escape(f_item.get('Notes',''))}</td>
</tr>"""
    return f"""<section id="food">
<h2>Shared Food</h2>
<table>
<thead><tr><th>Item</th><th>Brought By</th><th>Meal</th><th>Serves</th><th>Notes</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</section>"""


def _section_costs(costs, participants):
    if not costs:
        return ""
    rows = ""
    totals = {}
    for c in costs:
        amount_str = c.get("Amount", "0").replace("$", "").replace(",", "")
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 0
        paid_by = c.get("Paid By", "")
        split_between = c.get("Split Between", "Everyone")
        if split_between.lower() == "everyone":
            n = len(participants) if participants else 1
        else:
            n = len([s.strip() for s in split_between.split(",") if s.strip()])
        per_person = amount / n if n > 0 else 0

        rows += f"""<tr>
<td>{escape(c.get('Expense',''))}</td>
<td>{escape(paid_by)}</td>
<td>${amount:.2f}</td>
<td>{escape(split_between)}</td>
<td>${per_person:.2f}</td>
</tr>"""

        # Track who owes who
        if paid_by:
            totals.setdefault(paid_by, 0)
            totals[paid_by] += amount - per_person  # They paid but only owe their share

    total_amount = sum(
        float(c.get("Amount", "0").replace("$", "").replace(",", "") or 0)
        for c in costs
    )

    return f"""<section id="costs">
<h2>Costs</h2>
<table>
<thead><tr><th>Expense</th><th>Paid By</th><th>Amount</th><th>Split Between</th><th>Per Person</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p class="total"><strong>Total: ${total_amount:.2f}</strong></p>
</section>"""


def _section_packing(packing):
    if not packing:
        return ""
    current_cat = ""
    html = ""
    for item in packing:
        cat = item.get("Category", "")
        name = item.get("Item", "")
        if not name:
            continue
        if cat != current_cat:
            if current_cat:
                html += "</div>"
            current_cat = cat
            html += f'<div class="pack-category"><h3>{escape(cat)}</h3>'
        item_id = f"pack-{escape(cat)}-{escape(name)}".replace(" ", "-").lower()
        html += f'<label class="check-item"><input type="checkbox" data-pack="{item_id}"> {escape(name)}</label>'
    if current_cat:
        html += "</div>"

    return f"""<section id="packing">
<h2>Packing Checklist</h2>
<p class="hint">Checkboxes are saved on this device.</p>
{html}
</section>"""


# ── CSS ──────────────────────────────────────────────────────────────────────

CSS = """
:root {
  --green: #2d5016;
  --green-light: #e8f5e9;
  --tan: #f5f0e8;
  --bark: #5d4037;
  --text: #1a1a1a;
  --muted: #666;
  --border: #ddd;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  color: var(--text);
  max-width: 800px;
  margin: 0 auto;
  padding: 16px;
  background: #fafafa;
  line-height: 1.5;
}
header {
  background: var(--green);
  color: white;
  padding: 32px 24px;
  border-radius: 12px;
  margin-bottom: 24px;
}
header h1 { font-size: 2em; margin-bottom: 4px; }
header .subtitle { font-size: 1.2em; opacity: 0.9; }
header .meta { opacity: 0.8; margin-top: 4px; }
header .sheet-link a { color: var(--green-light); text-decoration: underline; }
section {
  background: white;
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 16px;
  border: 1px solid var(--border);
}
h2 {
  color: var(--green);
  font-size: 1.3em;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--green-light);
}
h3 { color: var(--bark); margin: 12px 0 8px; }
table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--green-light); color: var(--green); font-weight: 600; }
tr.needed { background: #fff3e0; }
tr.bringing { background: var(--green-light); }
ul { padding-left: 20px; }
li { margin-bottom: 4px; }
.btn {
  display: inline-block;
  background: var(--green);
  color: white;
  padding: 10px 20px;
  border-radius: 8px;
  text-decoration: none;
  margin-top: 12px;
  font-weight: 500;
}
.btn:hover { opacity: 0.9; }
.day-block { margin-bottom: 16px; }
.event { padding: 4px 0; }
.time { color: var(--green); font-weight: 600; min-width: 70px; display: inline-block; }
.note { color: var(--muted); font-style: italic; }
.activity-list { display: grid; gap: 10px; }
.activity-card {
  background: var(--tan);
  padding: 12px;
  border-radius: 8px;
}
.activity-card p { margin-top: 6px; color: var(--muted); font-size: 0.9em; }
.badge {
  display: inline-block;
  background: var(--green-light);
  color: var(--green);
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.8em;
  margin-right: 4px;
}
.total { margin-top: 8px; font-size: 1.1em; }
.pack-category { margin-bottom: 12px; }
.check-item {
  display: block;
  padding: 4px 0;
  cursor: pointer;
}
.check-item input { margin-right: 8px; }
.check-item:has(input:checked) { color: var(--muted); text-decoration: line-through; }
.hint { color: var(--muted); font-size: 0.85em; margin-bottom: 8px; }
footer {
  text-align: center;
  padding: 20px;
  color: var(--muted);
  font-size: 0.85em;
}
.weather-grid { display: flex; gap: 10px; overflow-x: auto; }
.weather-card {
  background: var(--tan);
  border-radius: 10px;
  padding: 12px 16px;
  min-width: 120px;
  text-align: center;
  flex-shrink: 0;
}
.weather-icon { font-size: 1.8em; }
.weather-date { font-weight: 600; font-size: 0.85em; margin-top: 4px; }
.weather-temp { font-size: 1.1em; color: var(--green); font-weight: 600; }
.weather-desc { font-size: 0.8em; color: var(--muted); }
.precip { font-size: 0.8em; color: #1565c0; }
.route-timeline { padding-left: 8px; }
.route-stop { display: flex; gap: 12px; align-items: flex-start; padding: 8px 0; }
.route-marker { font-size: 1.4em; flex-shrink: 0; }
.route-details { flex: 1; }
.route-lake { display: inline-block; background: #e3f2fd; color: #1565c0; padding: 1px 8px; border-radius: 10px; font-size: 0.85em; margin-left: 4px; }
.route-travel { color: var(--muted); font-size: 0.9em; font-style: italic; }
.route-connector { border-left: 2px dashed var(--border); height: 16px; margin-left: 17px; }
footer a { color: var(--green); }
@media (max-width: 600px) {
  body { padding: 8px; }
  header { padding: 20px 16px; }
  header h1 { font-size: 1.5em; }
  section { padding: 16px; }
  table { font-size: 0.8em; }
  th, td { padding: 6px; }
}
@media print {
  body { max-width: none; background: white; }
  header { background: none; color: black; border: 2px solid black; }
  header .sheet-link { display: none; }
  section { break-inside: avoid; border: 1px solid #ccc; }
  .btn { display: none; }
  .check-item input { appearance: none; border: 1px solid #999; width: 12px; height: 12px; display: inline-block; }
}
"""

# ── JavaScript ───────────────────────────────────────────────────────────────

JS = """
// Persist packing checklist in localStorage
const KEY = 'camping-trip-' + document.title.replace(/[^a-z0-9]/gi, '-').toLowerCase();

function loadChecks() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {};
  } catch { return {}; }
}

function saveChecks(state) {
  localStorage.setItem(KEY, JSON.stringify(state));
}

const state = loadChecks();
document.querySelectorAll('[data-pack]').forEach(cb => {
  const id = cb.dataset.pack;
  if (state[id]) cb.checked = true;
  cb.addEventListener('change', () => {
    state[id] = cb.checked;
    saveChecks(state);
  });
});
"""


# ── Drive operations ─────────────────────────────────────────────────────────

def upload_to_drive(file_path: str, folder_id: str = None) -> dict:
    """Upload a file to Google Drive. Returns {id, url}."""
    name = Path(file_path).name
    meta = {"name": name, "mimeType": "text/html"}
    if folder_id:
        meta["parents"] = [folder_id]

    result = json.loads(gws_raw(
        ["drive", "files", "create",
         "--params", json.dumps({"uploadType": "multipart"})],
        input_json=meta,
        upload=file_path,
    ))

    file_id = result.get("id", "")
    return {
        "id": file_id,
        "url": f"https://drive.google.com/file/d/{file_id}/view",
    }


def share_file(file_id: str):
    """Make a Drive file viewable by anyone with the link."""
    gws_raw(
        ["drive", "permissions", "create",
         "--params", json.dumps({"fileId": file_id})],
        input_json={"role": "reader", "type": "anyone"},
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Camping trip planner")
    sub = parser.add_subparsers(dest="command")

    # new-trip
    new_parser = sub.add_parser("new-trip", help="Create a new trip planning sheet")
    new_parser.add_argument("--title", default=None, help="Sheet title")
    new_parser.add_argument("--park", help="Park key from parks.json")
    new_parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    new_parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    new_parser.add_argument("--participants", help="Comma-separated names")

    # generate
    gen_parser = sub.add_parser("generate", help="Generate HTML from trip sheet")
    gen_parser.add_argument("--sheet-id", required=True, help="Google Sheet ID")
    gen_parser.add_argument("--output", default="trip.html", help="Output HTML file")
    gen_parser.add_argument("--route-file", help="KML or GPX route file to embed as map")

    # upload
    up_parser = sub.add_parser("upload", help="Upload HTML to Google Drive")
    up_parser.add_argument("--file", required=True, help="HTML file to upload")
    up_parser.add_argument("--folder-id", help="Drive folder ID")
    up_parser.add_argument("--share", action="store_true", help="Make shareable")

    args = parser.parse_args()

    if args.command == "new-trip":
        # Build trip info
        parks = {}
        if PARKS_FILE.exists():
            with open(PARKS_FILE) as f:
                parks = json.load(f).get("parks", {})

        trip_info = {}
        if args.park:
            park = parks.get(args.park, {})
            trip_info["Park"] = park.get("name", args.park)
            trip_info["Park Key"] = args.park
            trip_info["Drive Time"] = park.get("driveFromAjax", "")
        if args.start:
            trip_info["Start Date"] = args.start
        if args.end:
            trip_info["End Date"] = args.end

        title = args.title or f"{trip_info.get('Park', 'Camping')} Trip — {args.start or 'TBD'}"
        print(f"Creating trip sheet: {title}")

        result = create_trip_sheet(title)
        sheet_id = result["id"]

        participants = None
        if args.participants:
            names = [n.strip() for n in args.participants.split(",")]
            participants = [{"name": n} for n in names]

        populate_template(sheet_id, trip_info, participants)

        print(f"Sheet created: {result['url']}")
        print(f"Sheet ID: {sheet_id}")
        print("Share this with your group and have everyone fill in their sections.")

    elif args.command == "generate":
        generate_html(args.sheet_id, args.output, getattr(args, "route_file", None))

    elif args.command == "upload":
        result = upload_to_drive(args.file, args.folder_id)
        print(f"Uploaded: {result['url']}")
        if args.share:
            share_file(result["id"])
            print("Shared with anyone who has the link.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
