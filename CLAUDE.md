# Camping Planner — Claude Guide

## Ontario Parks API Reference

Ontario Parks reservations run on the **Camis/Aspira** platform at `reservations.ontarioparks.com`. There is no official public API — these are undocumented endpoints reverse-engineered from browser network traffic.

### Base URL

```
https://reservations.ontarioparks.com
```

### Authentication

None required for read-only endpoints. No API key needed.

### Rate Limits — IMPORTANT

The site is behind **Azure WAF** (Web Application Firewall) which will block your IP after ~15-20 rapid requests.

- **Ban duration**: 30+ minutes (IP-based)
- **Safe cadence**: 1.5-3 seconds between requests
- **Checking 2-3 parks** (~10-15 requests) is fine with delays
- **Bulk exploration** (50+ requests) will trigger the WAF

If you get a 403 with HTML containing "Azure WAF":
1. You are rate limited. Wait 30+ minutes before retrying.
2. As a workaround, `curl` with a different User-Agent sometimes bypasses the ban when `requests` (Python) is still blocked, since the WAF may track by User-Agent + IP combo.
3. Playwright fallback can sometimes work since the browser gets a fresh session, but the WAF may also serve a CAPTCHA to headless browsers.

### Key Endpoints

#### List all parks
```
GET /api/resourceLocation
```
Returns all parks with `resourceLocationId`, names, GPS, descriptions. ~133 items.

#### Get campground maps (hierarchical)
```
GET /api/maps
```
Returns root-level navigation maps. Very large response. To get maps for a specific park:
```
GET /api/maps?resourceLocationId={resourceLocationId}
```
This returns the park's campground maps with `mapId`, `mapResources` (individual sites), and `mapLinks` (child campground maps).

#### Check availability (primary endpoint)
```
GET /api/availability/map?mapId={mapId}&bookingCategoryId=0&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&isReserving=true&getDailyAvailability=true&partySize=4
```
Returns JSON with:
- `resourceAvailabilities`: dict of `{resourceId: [{availability: code, remainingQuota: null}, ...]}` — one entry per day
- `mapLinkAvailabilities`: dict of `{childMapId: [code, code, ...]}` — aggregated child map availability

**Availability codes:**
- `0` = Available
- `1` = Available (alternate type)
- `2` = Available (walk-in/first-come)
- `3` = Reserved
- `5` = Reserved
- `6` = Not operating / closed

One request returns ALL sites in a campground. No need to query individual sites.

#### Get site details and attributes
```
GET /api/resourcelocation/resources?resourceLocationId={resourceLocationId}
```
Returns ALL sites for a park (~100-400 resources) with full details including `definedAttributes`. This is the richest endpoint — contains privacy ratings, site dimensions, ground cover, distances to amenities, etc.

Each resource has a `definedAttributes` array where `attributeDefinitionId` maps to the attribute catalog.

#### Get attribute definitions (catalog)
```
GET /api/attribute/filterable
```
Returns all 55 attribute definitions with names and enum values. Key attributes:
- `-32761` Privacy: 0=Poor, 1=Average, 2=Good
- `-32762` Quality: 0=Poor, 1=Average, 2=Good
- `-32763` Site Shade: 0=Full Shade, 1=No Shade, 2=Partial AM, 3=Partial PM, 4=Partial
- `-32743` Site Length (m): numeric
- `-32742` Site Width (m): numeric
- `-32724` Toilet Distance (m): numeric
- `-32723` Water Tap Distance (m): numeric
- `-32749` Shoreline Access: 0=Easy, 1=Moderate, 2=Difficult, 3=None
- `-32759` Ground Cover: 0=Gravel, 1=Sand, 2=Grass, 3=Soil, 4=Rock
- `-32725` Dogs Allowed: 0=Yes, 1=No
- `-32766` Service Type: 0=Non-Electric, 1=Electric
- `-32765` Electrical Service: 0=15A, 1=30A, 2=15/30A, 3=15/30/50A
- `-32736` Double Site: 0=Yes, 1=No

Full attribute catalog is cached at `api_attribute_filterable.json`.

#### Other useful endpoints
```
GET /api/equipment              — equipment categories (tent, trailer, etc.)
GET /api/resourcecategory       — resource type categories (68 types)
GET /api/bookingcategories      — booking types
GET /api/maps/root              — root navigation maps only
```

### ID System

All IDs are **negative 32-bit integers** (Camis convention):
- `resourceLocationId`: identifies a park (e.g., Killarney = `-2147483601`)
- `mapId`: identifies a campground map within a park (e.g., Killarney root = `-2147483434`)
- `resourceId`: identifies an individual campsite
- `attributeDefinitionId`: identifies an attribute type

Park IDs and mapIds are stored in `parks.json`. To find a park's `mapId`:
1. Browse `reservations.ontarioparks.com`, navigate to the park's campground, grab `mapId` from URL
2. Or use: `GET /api/maps?resourceLocationId={id}` (but this requires Playwright — see below)

### Approach 1: Direct API with `requests` (preferred)

Use `ontario_parks.py` functions:
```python
from ontario_parks import check_park, check_multiple_parks, get_availability
results = check_park("killarney", "2026-07-10", "2026-07-12", party_size=4)
```
Or CLI:
```bash
python3 ontario_parks.py check killarney --start 2026-07-10 --end 2026-07-12
python3 ontario_parks.py list        # configured parks
python3 ontario_parks.py list-all    # all parks from API
```

### Approach 2: `curl` with different User-Agent

When Python `requests` is WAF-blocked, `curl` with a Windows User-Agent sometimes still works:
```bash
curl -sL -H "Accept: application/json" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  "https://reservations.ontarioparks.com/api/availability/map?mapId=-2147483434&bookingCategoryId=0&startDate=2026-07-10&endDate=2026-07-12&isReserving=true&getDailyAvailability=true&partySize=4"
```

### Approach 3: Playwright browser automation (fallback)

When the API is fully blocked, Playwright can load the reservation page and intercept the API calls the SPA makes internally. The site may serve an Azure WAF CAPTCHA to headless browsers too, so this isn't guaranteed.

Key Playwright technique — intercept the `/api/resourcelocation/resources` and `/api/availability/map` responses the page makes:
```python
captured = {}
def on_response(response):
    if '/api/resourcelocation/resources' in response.url and response.status == 200:
        captured['data'] = response.json()
page.on("response", on_response)
page.goto(url, timeout=45000, wait_until="domcontentloaded")
```

### Typical request counts per operation

| Operation | Requests | Notes |
|---|---|---|
| Check 1 park availability | 1 + N child maps | Killarney = 6 requests (1 root + 5 campgrounds) |
| Check 3 parks | ~10-18 | Safe with 1.5s delays |
| List all parks | 1 | `/api/resourceLocation` |
| Get site details for 1 park | 1 | `/api/resourcelocation/resources` — returns ALL sites |
| Get attribute definitions | 1 | `/api/attribute/filterable` — returns all 55 attributes |
| Refresh map name cache | 1 | `/api/maps` — large response |

### Project files

- `app/` — FastAPI single-page app. Entry point: `uvicorn app.main:app --reload --port 8000`
  - `app/main.py` — FastAPI instance, `db.init_schema()` on boot, `/static` mount, router includes
  - `app/config.py` — central paths + cache TTLs (REPO_ROOT, TRIPS_DIR, TEMPLATE_DIR, PARKS_JSON, DATABASE_PATH)
  - `app/models.py` — Pydantic request/response schemas
  - `app/services/db.py` — SQLite connection, schema init + auto-migration, generic JSON-blob cache, per-user checklist state
  - `app/services/identity.py` — cookie-based identity (`cp_user`); no password
  - `app/services/trips.py` — scan/create/save-gear logic; markdown table editor; `load_trip_payload` (used by `/api/trip/<slug>`); injects cached weather into build_trip
  - `app/services/availability.py` — `ontario_parks.check_park` wrapped in `availability_cache` (15 min TTL)
  - `app/services/weather_cache.py` — `weather.get_weather` wrapped in `weather_cache` (1 hour TTL)
  - `app/routes/{pages,trips,parks,checklist,identity}.py` — thin route handlers. `pages.py` always serves the same SPA shell; routing happens client-side
  - `app/templates/` — Jinja2 templates (`base.html`, `index.html` SPA shell)
  - `app/static/css/` — `index.css` (shell + sidebar) and `trip.css` (trip pane visuals)
  - `app/static/js/` — `index.js` (router + sidebar + forms) and `trip.js` (per-trip behaviours: checklist sync, gear editor, embedded-script bootstrapping)
  - `app/static/js/foods.js` — `/foods` master-detail UI.
  - `app/static/js/meal-plan.js` — trip-page meal planner section.
  - `app/services/foods.py` — load/search/upsert/delete foods; mtime-invalidated cache.
  - `app/services/meal_plan.py` — read/write the YAML meal plan in `trips/<slug>/food.md`; compute calorie totals against an activity-level target.
- `camping.sqlite3` — gitignored. Caches + checklist state. Safe to delete; app re-creates the schema empty on next boot. Trip content is *not* in here.
- `build_trip.py` — markdown → rendered HTML fragments (header, sections, weather, route map). Pure render library; the FastAPI layer composes these via `load_trip_payload`. No more `trip.html` artifact.
- `foods.json` — git-tracked foods catalog (name, category, kcal/serving, serving size, url). Edited via the `/foods` page; loaded once and cached in-memory by `app/services/foods.py`.
- `ontario_parks.py` — availability checker (API + Playwright fallback)
- `weather.py` — weather data via Open-Meteo API (historical averages + forecast)
- `route_map.py` — KML/GPX parser, Leaflet map + SVG offline map generator
- `parks.json` — park configs with resourceLocationId, mapId, drive times from Ajax
- `park_activities.json` — curated hikes/swimming/paddling/tips per park
- `api_attribute_filterable.json` — cached attribute definitions (55 attributes)
- `map_names_cache.json` — cached campground map names
- `osm_data.py`, `osm_killarney_cache.json` — OSM lakes/portages cache used by `route_engine.py`
- `route_engine.py` — auto-routes paddling segments + estimates from OSM data
- `templates/trip-template/` — markdown skeletons copied when creating a new trip
- `trips/<slug>/` — per-trip markdown source of truth (rendered on demand by the FastAPI app; no `trip.html` artifact)
- `legacy/` — pre-FastAPI sheet-driven flow (`trip_planner.py`, sample resource data, etc.). Kept for reference.
- `FastAPI-refactor.md` — phase history (Phases 1–3 complete) and rationale for what was skipped

**Source of truth:** markdown files in `trips/<slug>/` for trip *content*. `parks.json` for park metadata. `foods.json` for the foods catalog. SQLite (`camping.sqlite3`) holds operational state only — caches and per-user checklist toggles. Disaster-recovery story: git restores trip content + foods catalog; the DB is rebuildable on demand.

**Identity:** cookie-based, no password. The `cp_user` cookie names the active user; empty/absent = "shared" bucket. Phase 2 checklist rows (no user) auto-migrate to the shared bucket on first Phase 3 boot. See `FastAPI-refactor.md` for phase history.

---

## Trip Planning Workflow

### Overview

```
trips/<slug>/*.md ─► app.services.trips.load_trip_payload ─► /api/trip/<slug> ─► SPA pane
       ▲                                                          ▲
       │                                                          │
   git (truth)                                  FastAPI app at app/
                                                + camping.sqlite3 (caches, per-user toggles)
```

Markdown files in `trips/<slug>/` are the source of truth. The FastAPI app renders them on demand into the SPA's main pane — there's no per-trip HTML artifact. Edit markdown directly (then commit) or via the in-browser section editors.

### Working with trips

```bash
uvicorn app.main:app --reload --port 8000
# http://127.0.0.1:8000/             → SPA shell, sidebar lists every trip
# http://127.0.0.1:8000/trips/<slug> → SPA deep-links to a trip
# http://127.0.0.1:8000/new          → new-trip form
# http://127.0.0.1:8000/availability → park availability check
```

The sidebar swaps trips without a page reload — handy for comparing 2+ trips. Save-gear and section saves write straight to markdown; commit them with git.

### Starting a new trip

Either via the SPA "+ New Trip" form, or by hand:
```bash
cp -r templates/trip-template trips/<park>-<YYYY-MM>/
$EDITOR trips/<park>-<YYYY-MM>/trip.md   # fill frontmatter
```

Slug convention is `<park>-<YYYY-MM>` derived from `park` + `start_date`.

### Section files (per trip)

| File           | Purpose                                                               |
|----------------|-----------------------------------------------------------------------|
| `trip.md`      | YAML frontmatter (park, dates, participants, nights, access_point) + intro markdown |
| `itinerary.md` | Day-by-day schedule                                                   |
| `gear.md`      | Shared gear table — editable in-browser via the Edit gear button     |
| `food.md`     | YAML frontmatter for structured per-day meal plan; markdown body regenerated on save. Edit via the in-pane meal planner. |
| `packing.md`   | Personal packing list (the only file with task-list checkboxes)       |
| `costs.md`     | Expense splits                                                        |
| `route.gpx` / `route.kml` | Optional route file; auto-rendered as Leaflet + SVG          |

### Weather integration

`weather.py` uses Open-Meteo API (no key). FastAPI calls go through `app/services/weather_cache.py` (1-hour TTL); CLI `build_trip.py` calls go direct.
- **> 16 days out**: historical climate averages for those dates at the park location
- **Within 16 days**: real forecast with precipitation probability + weather codes
- Park GPS coordinates: `weather.py:PARK_COORDS`

### Route maps (KML/GPX + auto-route)

`route_map.py` parses KML/GPX into:
- **Leaflet.js interactive map** (online) — OSM tiles, coloured tracks, clickable waypoints
- **Static SVG diagram** (offline) — route shape, waypoints, distances, scale bar, in a collapsible `<details>`

If `trip.md` has `nights` + `access_point` but no `route.gpx`/`.kml`, `route_engine.py` auto-routes paddling + portage segments using the cached OSM data in `osm_killarney_cache.json` and produces per-day estimates.

### Foods catalog & meal planner

`foods.json` (repo root) is the catalog of camping foods. Edit it via the `/foods` page (master-detail UI: search/filter on the left, edit form on the right).

Each trip's `food.md` holds a structured meal plan as YAML frontmatter. The meal planner on the trip page lets you add per-day meals, pick foods from the catalog (autocomplete; create-new opens a modal that updates `foods.json`), and shows live calorie totals against an activity-level target. The four activity levels and their default kcal/person/day:

- backcountry → 4000
- bikepacking → 4500
- boat-camping → 3500
- car-camping → 2500

The body of `food.md` is regenerated on every save; hand-edit only the YAML frontmatter (or, better, edit via the UI).

### Trip pane features

- Rendered server-side per request via `/api/trip/<slug>` — no static HTML artifact
- Sidebar trip switcher: click between trips without reloading
- Per-user packing checklist sync via `/api/checklist`
- Gear table inline editor → `/api/save-gear`
- Weather section (historical or forecast)
- Route map (Leaflet from CDN + SVG fallback in `<noscript>`)
- Responsive + print-friendly (`@media print` styles in `app/static/css/trip.css`)

### Tests

```bash
pytest tests/ -q       # 82 tests, ~1s
```

Tests cover `build_trip.py` render functions, OSM/route logic, the gear-table editor, FastAPI routes (incl. SPA shell + `/api/trip/<slug>`), the SQLite layer (incl. v0→v1 migration), and identity. The Camis API is **always mocked** in tests — never hit Ontario Parks from the test suite.
