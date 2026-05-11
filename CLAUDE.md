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

- `app/` — FastAPI web UI. Entry point: `uvicorn app.main:app --reload --port 8000`
  - `app/main.py` — FastAPI instance, `db.init_schema()` on boot, `/static` and `/trips` mounts, router includes
  - `app/config.py` — central paths + cache TTLs (REPO_ROOT, TRIPS_DIR, TEMPLATE_DIR, PARKS_JSON, DATABASE_PATH)
  - `app/models.py` — Pydantic request/response schemas
  - `app/services/db.py` — SQLite connection, schema init + auto-migration, generic JSON-blob cache, per-user checklist state
  - `app/services/identity.py` — cookie-based identity (`cp_user`); no password
  - `app/services/trips.py` — scan/create/rebuild/save-gear logic; markdown table editor; injects cached weather into build_trip
  - `app/services/availability.py` — `ontario_parks.check_park` wrapped in `availability_cache` (15 min TTL)
  - `app/services/weather_cache.py` — `weather.get_weather` wrapped in `weather_cache` (1 hour TTL)
  - `app/routes/{pages,trips,parks,checklist,identity}.py` — thin route handlers
  - `app/templates/` — Jinja2 templates (NOT the same as `templates/trip-template/`)
  - `app/static/` — `index.css`, `index.js`
- `camping.sqlite3` — gitignored. Caches + checklist state. Safe to delete; app re-creates the schema empty on next boot. Trip content is *not* in here.
- `launch.py` — legacy stdlib HTTP server. Functionally replaced by `app/`; kept until smoke-tested in the wild, then deleted.
- `build_trip.py` — markdown → trip.html renderer (called from `app/services/trips.py`)
- `ontario_parks.py` — availability checker (API + Playwright fallback)
- `weather.py` — weather data via Open-Meteo API (historical averages + forecast)
- `route_map.py` — KML/GPX parser, Leaflet map + SVG offline map generator
- `parks.json` — park configs with resourceLocationId, mapId, drive times from Ajax
- `park_activities.json` — curated hikes/swimming/paddling/tips per park
- `api_attribute_filterable.json` — cached attribute definitions (55 attributes)
- `map_names_cache.json` — cached campground map names
- `osm_data.py` — loads + merges all Killarney datasets (OSM lakes/portages,
  Jeff's lake polygons, yellow paths, GPX campsites + portages)
- `gpx_loader.py` — GPX → list-of-dicts parsing for campsites and portages
- `data/` — cached + source data files (gitted):
  - `osm_killarney_cache.json` — OSM lakes (51 named) + portages (sparse)
  - `jeffs_killarney_cache.json` — Jeff's lake polygons (33 named + 30 unnamed)
  - `jeffs_canoe_paths.json` — yellow paddle paths extracted from Jeff's KMZ
  - `killarneyCampsites.gpx` — 214 numbered campsite waypoints (PaddlePlanner)
  - `killarneyPortages.gpx` — 110 portages × 2 endpoints (PaddlePlanner)
- `route_engine.py` — auto-routes paddling segments + estimates from merged data
- `templates/trip-template/` — markdown skeletons copied when creating a new trip
- `trips/<slug>/` — per-trip markdown source of truth + generated `trip.html`
- `legacy/` — pre-FastAPI sheet-driven flow (`trip_planner.py`, sample resource data, etc.). Kept for reference.
- `FastAPI-refactor.md` — phase history (Phases 1–3 complete) and rationale for what was skipped

**Source of truth:** markdown files in `trips/<slug>/` for trip *content*. SQLite (`camping.sqlite3`) holds operational state only — caches and per-user checklist toggles. Disaster-recovery story: git restores trip content; the DB is rebuildable on demand.

**Identity:** cookie-based, no password. The `cp_user` cookie names the active user; empty/absent = "shared" bucket. Phase 2 checklist rows (no user) auto-migrate to the shared bucket on first Phase 3 boot. See `FastAPI-refactor.md` for phase history.

---

## Trip Planning Workflow

### Overview

```
trips/<slug>/*.md  ──build_trip.py──►  trips/<slug>/trip.html
       ▲                                        ▲
       │                                        │
   git (truth)                          FastAPI app at app/
                                        + camping.sqlite3 (caches, per-user toggles)
```

Markdown files in `trips/<slug>/` are the source of truth. `build_trip.py` renders them into a self-contained `trip.html` per trip. The FastAPI app at `app/` provides a browser UI for creating trips, rebuilding HTML, editing the gear table, checking park availability, and syncing per-user packing checkboxes.

## Data sources

| Feature | Source | Notes |
|---|---|---|
| Lake polygons | OSM Overpass + Jeff's KMZ | OSM is named-canonical; Jeff's are tighter shapes |
| Portages (110) | `data/killarneyPortages.gpx` | PaddlePlanner.com; merged with sparse OSM |
| Campsites (214) | `data/killarneyCampsites.gpx` | PaddlePlanner.com; name = site number |
| Yellow paddle paths | Jeff's KMZ raster extraction | `jeffs_paths_extractor.py` (OCR text-removed) |
| Weather | Open-Meteo API | `weather.py` |
| Route maps | KML/GPX in trip dir | `route_map.py` |

`osm_data.load_killarney_features()` consolidates all of the above into one dict consumed by `route_engine` and the FastAPI layer.

### Two ways to work

**Edit-then-rebuild (git-first):**
```bash
$EDITOR trips/<slug>/packing.md
python3 build_trip.py trips/<slug>/
git add trips/<slug>/ && git commit -am "..."
```

**Web UI (FastAPI):**
```bash
uvicorn app.main:app --reload --port 8000
# http://127.0.0.1:8000/  → index, "+ New Trip", rebuild, availability check
# http://127.0.0.1:8000/trips/<slug>/trip.html  → trip page (gear edit, checkboxes)
```

The two paths coexist: the web UI writes back to the same markdown files; commit those after editing.

### Starting a new trip

Either via the index "+ New Trip" form, or:
```bash
cp -r templates/trip-template trips/<park>-<YYYY-MM>/
$EDITOR trips/<park>-<YYYY-MM>/trip.md   # fill frontmatter
python3 build_trip.py trips/<park>-<YYYY-MM>/
```

Slug convention is `<park>-<YYYY-MM>` derived from `park` + `start_date`.

### Section files (per trip)

| File           | Purpose                                                               |
|----------------|-----------------------------------------------------------------------|
| `trip.md`      | YAML frontmatter (park, dates, participants, nights, access_point) + intro markdown |
| `itinerary.md` | Day-by-day schedule                                                   |
| `gear.md`      | Shared gear table — editable in-browser via the Edit gear button     |
| `food.md`      | Shared meal plan                                                      |
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

### HTML trip page features

- Self-contained (all CSS/JS inline; only external dep is the Leaflet CDN for online maps)
- Works offline — checkboxes persist via `localStorage` per-user; SVG map fallback for routes
- Per-user packing checklist sync via `/api/checklist` when the FastAPI app is running
- Weather section (historical or forecast)
- Route map (Leaflet online + SVG offline)
- Responsive + print-friendly (`@media print` styles)

### Tests

```bash
pytest tests/ -q       # 79 tests, ~1s
```

Tests cover `build_trip.py` rendering, OSM/route logic, the gear-table editor, FastAPI routes (with TestClient), the SQLite layer (incl. v0→v1 migration), and identity. The Camis API is **always mocked** in tests — never hit Ontario Parks from the test suite.
