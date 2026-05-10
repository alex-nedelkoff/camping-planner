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

- `ontario_parks.py` — availability checker (API + Playwright fallback)
- `trip_planner.py` — trip planning orchestrator (Sheet creation, HTML generation, Drive upload)
- `weather.py` — weather data via Open-Meteo API (historical averages + forecast)
- `route_map.py` — KML/GPX parser, Leaflet map + SVG offline map generator
- `parks.json` — park configs with resourceLocationId, mapId, drive times from Ajax
- `park_activities.json` — curated hikes/swimming/paddling/tips per park
- `api_attribute_filterable.json` — cached attribute definitions (55 attributes)
- `sample_resources_killarney.json` — sample site detail data for Killarney (379 sites)
- `map_names_cache.json` — cached campground map names

---

## Trip Planning Workflow

### Overview

The trip planning workflow uses a **collaborative Google Sheet** as the source of truth and generates a **self-contained HTML trip page** from it.

```
Google Sheet (collaborative) → trip_planner.py generate → HTML trip page (offline-capable)
```

### Using `gws` CLI for Google Workspace

The project uses `gws` CLI (installed at `/opt/homebrew/bin/gws`) for all Google Workspace operations. No service account or credentials.json needed.

Common operations:
```bash
# Read a sheet
gws sheets spreadsheets values get --params '{"spreadsheetId":"ID","range":"Sheet1"}'

# Create a spreadsheet
gws sheets spreadsheets create --json '{"properties":{"title":"My Sheet"}}'

# Write to a sheet
gws sheets spreadsheets values update \
  --params '{"spreadsheetId":"ID","range":"Tab!A1","valueInputOption":"USER_ENTERED"}' \
  --json '{"values":[["a","b"],["c","d"]]}'

# Upload file to Drive
gws drive files create --json '{"name":"file.html","mimeType":"text/html"}' --upload file.html

# Share with anyone
gws drive permissions create --params '{"fileId":"ID"}' --json '{"role":"reader","type":"anyone"}'
```

### trip_planner.py usage

```bash
# Create a new trip sheet with template tabs
python3 trip_planner.py new-trip --park killarney --start 2026-07-10 --end 2026-07-12 --participants "Alex,Jordan,Sam"

# Generate HTML from a filled-out sheet
python3 trip_planner.py generate --sheet-id SHEET_ID --output trip.html

# Generate with a KML/GPX route map embedded
python3 trip_planner.py generate --sheet-id SHEET_ID --route-file route.gpx --output trip.html

# Upload to Drive and share
python3 trip_planner.py upload --file trip.html --share
```

### Sheet template tabs

The trip planning sheet has 8 tabs:
1. **Trip Info** — park, dates, meeting point, drive time, check-in/out
2. **Participants** — names, driving status, dietary restrictions, phone numbers
3. **Route** — multi-site/canoe route: day, site/location, lake, travel method, notes
4. **Gear** — items, assignments, status (Bringing/Needed)
5. **Shared Food** — food items, who's bringing, which meal, dietary notes
6. **Itinerary** — day-by-day schedule with times and activities
7. **Costs** — expenses, who paid, split calculation
8. **Packing Checklist** — personal packing items with checkboxes

### Interactive trip creation

When the user asks to plan a trip, Claude should:
1. Ask which park and dates
2. Ask who's coming (or read from survey)
3. Create the Sheet via `trip_planner.py new-trip`
4. Check Ontario Parks for site details and suggest activities
5. Help fill in the itinerary, gear, and food tabs
6. Generate the HTML page
7. Upload to Drive and share the link

### Weather integration

`weather.py` uses Open-Meteo API (free, no key). Automatically included in HTML generation.
- **> 16 days out**: shows historical climate averages for those dates at the park location
- **Within 16 days**: switches to real forecast with precipitation probability and weather codes
- Park GPS coordinates are in `weather.py:PARK_COORDS`

### Route maps (KML/GPX)

`route_map.py` parses KML and GPX files and generates:
- **Leaflet.js interactive map** (online) — OpenStreetMap tiles, colored track lines, clickable waypoint markers
- **Static SVG diagram** (offline) — route shape, waypoints, distances, scale bar, in a collapsible `<details>` element

To download a route file from Google Drive before generating:
```bash
gws drive files get --params '{"fileId":"DRIVE_FILE_ID","alt":"media"}' -o route.gpx
python3 trip_planner.py generate --sheet-id ID --route-file route.gpx --output trip.html
```

### HTML trip page features

- Self-contained (all CSS/JS inline, no external deps except Leaflet CDN for maps)
- Works offline (localStorage for checklists, SVG map fallback)
- Weather section (historical or forecast)
- Route map (Leaflet online + SVG offline)
- Responsive (mobile-friendly)
- Print-friendly (`@media print` styles)
- Links back to the Sheet for edits
