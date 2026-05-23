# Trip data → JSON, server-rendered trip pages, sibling nav

**Status:** design — awaiting user review before plan
**Author / brainstorm partner:** Alex + Claude
**Date:** 2026-05-22

## Motivation

Two related problems with today's architecture:

1. **Per-trip data is fragmented across `.md` files** (`trip.md`, `gear.md`, `food.md`, `costs.md`, `itinerary.md`, `packing.md`). Editing is fragile — gear-table edits go through regex (`replace_first_table` in `app/services/trips.py`) that depends on exact markdown shape. There's no schema, no validation, and most files can't be edited from the UI at all.

2. **Some pages are dead-ends.** `/overlay/` and `/trips/<slug>/trip.html` have no navigation back to home or to other trips. The per-section `.md` files (`food.md`, `gear.md`, `costs.md`, `itinerary.md`, `packing.md`) are also orphaned — they sit on disk but nothing in the UI links to them.

This design consolidates trip data into one structured file per trip (`trip.json`), replaces the static-baked `trip.html` with a server-rendered page that reads `trip.json` on each request, makes every section inline-editable, and adds a shared header nav band so no page is a dead-end.

## Decisions (locked-in)

| Question | Decision |
|---|---|
| JSON scope | One `trip.json` per trip — holds frontmatter + gear + costs + packing + itinerary + food |
| Edit model | Inline edit on the trip page; explicit "edit mode" per section |
| Render model | Server-render `/trip/<slug>` on each request (Jinja); no build step |
| Compute model | Cache weather + route data aggressively in SQLite; recompute lazily |
| Sibling-trip nav | Hybrid: chevrons + dropdown — `← [Killarney 2026-05 ▼] →` |
| Route section inline editing | Lightweight (reorder / rename / delete waypoints + segments); drawing new polylines stays in `/overlay/` |
| Packing checkbox interaction | Goes through edit mode like every other section — no special-case immediate-save |

## Architecture overview

```
┌───────────────────────────────────────────────────────────────┐
│  Browser                                                       │
│  ┌──────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │   /      │  │  /trip/<slug>    │  │  /overlay/?trip=...  │ │
│  │  index   │  │  trip page       │  │  map drawing tool    │ │
│  │  (SPA)   │  │  (server-rendered)│  │  (existing)          │ │
│  └────┬─────┘  └────────┬─────────┘  └──────────┬───────────┘ │
└───────┼─────────────────┼──────────────────────┼──────────────┘
        │                 │                      │
        ▼ JSON API        ▼ HTML + PATCH         ▼ static assets
┌───────────────────────────────────────────────────────────────┐
│  FastAPI (app/)                                                │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐│
│  │ routes/pages.py │  │ routes/trips.py                       ││
│  │   /             │  │   GET /trip/<slug>                    ││
│  │   /overlay/     │  │   GET/POST/PATCH/DELETE /api/trips/.. ││
│  └─────────────────┘  └──────────────────────────────────────┘│
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ services/trips.py — load/save trip.json, Pydantic models │ │
│  │ services/weather_cache.py — SQLite cache (existing)      │ │
│  │ services/route_cache.py   — NEW: caches route renders    │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────┬──────────────────────────────────────┘
                         ▼ filesystem (source of truth)
                ┌────────────────────────────┐
                │  trips/<slug>/             │
                │   ├── trip.json   ◄── all  │
                │   │                  data  │
                │   └── manual_routes.json   │
                └────────────────────────────┘
                         ▼ derived caches
                ┌────────────────────────────┐
                │  camping.sqlite3           │
                │   ├── weather_cache        │
                │   └── route_cache (NEW)    │
                └────────────────────────────┘
```

**Source-of-truth rule:** `trip.json` is the only authoritative data. Caches (weather, route renders) are derived from `trip.json` + `manual_routes.json` and are disposable. If a cache is missing or stale, recompute on next request.

**What `route_cache` actually caches:** the Leaflet map config + computed paddle/portage distances + the HTML block embedded into the trip page's Route section. Keyed by `manual_routes.json` content hash so edits invalidate cleanly. Map tiles themselves are not cached locally — Leaflet pulls them from OSM tile servers at view time.

**What goes away:**
- `build_trip.py` (no more HTML baking)
- Per-section `.md` files in each trip directory
- Static `trip.html` files
- `replace_first_table` regex-based markdown editing
- `weather.py` direct calls (folded into `weather_cache`)
- Endpoints: `/save-gear`, `/rebuild`, `/new-trip` (replaced by `/api/trips/*`)

**What stays:**
- `manual_routes.json` — separate file (editor artifact from `/overlay/`, distinct write-path)
- `weather_cache` (existing pattern, generalized to route cache as well)
- Identity (`/whoami`), park availability (`/availability`), checklist endpoints
- `/overlay/` as the heavy-duty map editor

## `trip.json` schema

One file per trip at `trips/<slug>/trip.json`. Validated by Pydantic models on every read/write. Prose blocks stored as markdown strings, rendered server-side at request time via `python-markdown`.

```json
{
  "schema_version": 1,
  "name": "killarney-2026-05",
  "park": "killarney",
  "dates": { "start": "2026-05-15", "end": "2026-05-18" },
  "participants": ["Alex", "pizza-zip"],
  "access_point": "George Lake",

  "nights": [
    { "date": "2026-05-15", "site": "61", "location": "OSA Lake", "gps": null },
    { "date": "2026-05-16", "site": "82", "location": "Baie Fine",
      "gps": [46.044041, -81.503845] }
  ],

  "itinerary": [
    { "date": "2026-05-15", "label": "Day 1 — Friday",
      "notes": "Depart Ajax ~5h drive...\n\n- Permit pickup\n- Launch from George Lake" }
  ],

  "gear": {
    "shared": [
      { "item": "Canoe (rental?)", "who": "TBD", "notes": "confirm with outfitter" }
    ],
    "personal": [
      { "person": "Alex", "items": [{ "item": "Sleeping bag", "notes": "" }] }
    ]
  },

  "food": [
    { "slot": "friday-dinner", "label": "Friday dinner",
      "items": [{ "name": "Filet + mash + cuke salad", "who": "Alex" }],
      "notes": "" }
  ],

  "costs": [
    { "item": "Permit / reservation", "who_paid": "", "amount": null, "currency": "CAD" }
  ],

  "packing": [
    { "category": "Shelter & sleep",
      "items": [{ "label": "Tent", "checked": false }] }
  ]
}
```

**Schema notes:**
- `schema_version` is explicit so future migrations can branch on it. Unknown version → load fails fast.
- `itinerary[].notes` and `food[].notes` are markdown strings. Server renders to HTML at request time. Preserves the current free-form writing flow.
- `gear.personal` groups by person rather than being flat — matches actual usage ("Alex brings X, pizza-zip brings Y").
- `costs[].amount` is `number | null`. Null = "not paid yet / unknown." Explicit `currency` (defaults `"CAD"`).
- `food[].slot` is a stable kebab-case key. `label` is the human-readable rename target.
- **Not in `trip.json`:** weather data, computed route HTML, map tiles. Those live in side-caches keyed by `trip.name + dates + manual_routes.json hash`.
- **Out of scope:** linking `food[].items` to the food library in `camping-planner-food/foods.yaml`. Note for a future iteration; keep `food[].items` as `{name, who}` loose for now.

## Routes & API

### Page routes (server-rendered HTML)

| Route | Returns |
|---|---|
| `GET /` | Index SPA (existing — minor template tweaks only) |
| `GET /trip/<slug>` | Trip detail page — Jinja template, reads `trip.json`, fetches cached weather + route HTML |
| `GET /overlay/?trip=<slug>` | Map overlay — `trip` query param scopes the `manual_routes.json` it loads and the "← back to trip" nav target |

### JSON API

| Route | Method | Body | Purpose |
|---|---|---|---|
| `GET /api/trips` | GET | — | List of `{slug, name, park, dates, prev_slug, next_slug}` sorted by start date. Powers index + sibling-nav dropdown in one fetch. |
| `GET /api/trips/<slug>` | GET | — | Full `trip.json` (just the source-of-truth data — does not include computed weather or rendered route HTML; those are server-embedded into the `/trip/<slug>` page response, not exposed via this endpoint) |
| `POST /api/trips` | POST | `{park, start, end, participants?}` | Create new trip → returns `{slug}` |
| `DELETE /api/trips/<slug>` | DELETE | — | Remove trip directory |
| `PATCH /api/trips/<slug>/meta` | PATCH | partial of `{park, dates, participants, access_point, nights}` | Frontmatter-style updates |
| `PUT /api/trips/<slug>/section/<name>` | PUT | full section object | `<name>` ∈ `gear \| food \| costs \| itinerary \| packing`. Full replacement, no diffs. |
| `POST /api/trips/<slug>/refresh-weather` | POST | — | Force weather cache miss |
| `POST /api/trips/<slug>/refresh-route` | POST | — | Force route cache miss (after `manual_routes.json` edits) |

**Choice rationale:**
- `PUT` for section replace (not `PATCH`) because the client always sends the full section — no partial diff semantics to figure out.
- Sibling-nav `prev_slug`/`next_slug` baked into `/api/trips` list response — keeps the dropdown a one-fetch operation, no separate `/siblings` endpoint.

### Validation

Pydantic v2 models, one per section (`TripMeta`, `GearSection`, `FoodSection`, etc.). Auto-generates 422 on bad payloads. `schema_version` checked on every load — unknown version returns 500 with a clear error (forces explicit migration).

### Error handling

- `trip.json` missing → 404 (don't auto-recover from MD; that would be a setup error)
- Slug collision on `POST /api/trips` → 409
- Weather / route cache recompute failure → render trip page anyway with inline "weather unavailable" / "route render failed" block + retry button. Don't 500 the whole page over an Open-Meteo hiccup.

### Concurrency

Single-user-at-a-time. No optimistic locking / ETags. Per-section design makes adding `If-Match` trivial later if multi-user editing becomes real.

## Templates & inline-edit UX

### File layout

```
app/templates/
├── base.html               (existing — header includes nav_band partial)
├── index.html              (existing — minor changes: trip cards link to /trip/<slug>)
├── trip.html               (NEW — server-rendered trip detail page)
├── overlay.html            (NEW — converted from jeffs_osm_overlay.html, gets nav band)
└── partials/
    ├── nav_band.html       (NEW — shared header strip)
    ├── trip_card.html      (existing — point to /trip/<slug>)
    ├── trip_header.html    (NEW — hero block: park, dates, participants, nights)
    └── section_*.html      (NEW — itinerary, gear, food, packing, costs, route, weather)
```

### Nav band — one partial, three render modes

```
On /trip/<slug>:
┌──────────────────────────────────────────────────────────────┐
│  🏕  Trips  /  ←  [Killarney 2026-05 ▼]  →   [alex] [⚙]    │
└──────────────────────────────────────────────────────────────┘
                    ↑ click → dropdown of all trips + "+ New trip"

On /overlay/?trip=killarney-2026-05:
┌──────────────────────────────────────────────────────────────┐
│  🏕  Trips  /  ←  Back to Killarney 2026-05      [alex] [⚙] │
└──────────────────────────────────────────────────────────────┘

On /overlay/  (no trip context):
┌──────────────────────────────────────────────────────────────┐
│  🏕  Trips                                        [alex] [⚙] │
└──────────────────────────────────────────────────────────────┘
```

Context vars: `nav.{home_href, trip_slug, trip_label, trip_dropdown, prev_slug, next_slug, back_href, back_label, show_user_pill}`. Missing fields hide their UI element. Used by `trip.html`, `overlay.html`, and `index.html`.

### Inline-edit pattern

Each section renders in **read mode** by default. Each section has an `[Edit]` button (top-right). Click → swap to edit UI for that section only (other sections stay read-only). Save → `PUT /api/trips/<slug>/section/<name>` → swap back to read mode rendered from server response.

| Section | Read mode | Edit mode |
|---|---|---|
| **Trip meta** (header) | Hero with dates, park, participants, nights table | Form: park dropdown, date pickers, participants chips, access_point, nights table editor |
| **Itinerary** | Day cards with rendered markdown | Per-day textarea (markdown) + add/remove day |
| **Gear** | Shared + Personal tables, rendered read-only | Editable cells (contenteditable), add/delete rows |
| **Food** | Meal-slot cards: label, items, notes markdown | Per-slot inline editor: items (name + who), notes textarea |
| **Packing** | Categorized checklist (display-only) | Manage-items mode: check/uncheck, add/remove items, rename categories |
| **Costs** | Table + total | Same row-editor pattern as gear |
| **Route** | Leaflet embed showing waypoints + segments | Lightweight inline edit: reorder / rename / delete waypoints + segments. Drawing new polylines on the map stays in `/overlay/`. |
| **Weather** | Daily strip | No inline edit — "Refresh" button → `POST .../refresh-weather` |

**Client-side stack:** plain JS modules per section in `app/static/js/section_<name>.js` (no framework — consistent with what Pizza-zip set up for the SPA). Pattern: `render(data) → DOM`, `enterEditMode()`, `save() → fetch(PUT) → render(response)`.

**Markdown rendering:** server-side via `python-markdown` (already a dep). No client-side markdown library needed.

**Styling:** existing `app/static/css/index.css` + new `trip.css`. The current `trip.html` has its CSS inlined by `build_trip.py` — extract that into `trip.css` to preserve visual continuity.

## Migration

### Script

`scripts/migrate_md_to_json.py`:

```
For each trips/<slug>/ that has trip.md and no trip.json:
  1. Parse trip.md frontmatter                                  → meta block
  2. Parse itinerary.md by `## ...` headings                    → itinerary[]
  3. Parse gear.md (shared table + personal sections)           → gear{}
  4. Parse food.md by `## meal` headings                        → food[]
  5. Parse costs.md (markdown table)                            → costs[]
  6. Parse packing.md (`- [ ]` checkbox groups by category)     → packing[]
  7. Assemble + validate against Pydantic models
  8. Write trip.json
  9. Move *.md files to trips/<slug>/_archive/ (don't delete — backup)
```

Idempotent — refuses to overwrite an existing `trip.json` unless `--force`. Has a `--dry-run` mode that prints JSON to stdout.

**Edge cases the script must handle:**
- Empty sections (e.g., `food.md` is mostly empty headings) — emit empty arrays, not errors
- Nested markdown in itinerary notes — preserve as markdown strings, don't try to re-parse
- Missing files (e.g., trip has no `costs.md` yet) — emit empty array, log warning
- `manual_routes.json` exists — leave it alone

**Known lossy spot:** `food.md` is the most freeform. Migration creates one `food[]` entry per `## heading` and dumps all prose under it into `notes`. No attempt to extract structured items. Expect manual cleanup post-migration.

### Rollout

| Step | What | Reversible? |
|---|---|---|
| 1 | Add Pydantic models + `/api/trips/*` endpoints in parallel with old endpoints | ✓ |
| 2 | Add `trip.html` template + section partials + JS modules | ✓ |
| 3 | Convert `jeffs_osm_overlay.html` → `app/templates/overlay.html` + add nav band | ✓ |
| 4 | Run migration script on `killarney-2026-05` | ✓ (archived) |
| 5 | Verify `/trip/killarney-2026-05` renders end-to-end | — |
| 6 | Switch `trip_card.html` link → `/trip/<slug>` | ✓ |
| 7 | Update `index.js` to call new endpoints; remove old endpoint callers | ✓ |
| 8 | Delete `build_trip.py`, `weather.py`, `tests/test_build_trip.py`, `tests/test_md_table.py`, static `trip.html` files | git remembers — ✓ |
| 9 | Delete `trips/<slug>/_archive/` once confident | ✓ |

**Killbear trip on origin/main:** when you eventually merge `origin/main` into this branch, `trips/killbear-2026-08/*.md` arrives. Re-run the migration script (idempotent); the new trip gets converted in the same shape. The deferred-merge plan does not break this design.

## Testing

### Validation tests
Pydantic models give validation on parse for free. Tests cover edge cases: empty strings, null vs missing fields, schema_version mismatch.

### Migration script tests (`tests/test_migrate_md_to_json.py`)
Fixture-based: golden input under `tests/fixtures/migration/<case>/{*.md}` → expected `trip.json`. Cases: full trip, empty sections, missing files, frontmatter-only trip, weird table whitespace.

### API tests (`tests/test_routes_trips.py`)
FastAPI TestClient + temp `TRIPS_DIR` (existing pattern). Coverage: CRUD on trip, PATCH meta, PUT each section, refresh-weather (mocked), refresh-route (mocked). **Never hit Open-Meteo or Ontario Parks from tests** — existing project rule, carries forward.

### Template rendering smoke tests (`tests/test_templates.py`)
Render `trip.html` with a fixture `trip.json` → assert HTML validity + key strings present. Render `overlay.html` with various nav contexts → check nav band variants. No selenium / browser.

### Manual verification (not automated, listed for completeness)
- `/trip/killarney-2026-05` — click through every section's edit mode
- Nav band: home link, prev/next, dropdown, user pill all work
- `/overlay/?trip=killarney-2026-05` — "← Back" returns to trip page
- Refresh weather button works without rate-limiting
- Inline route editing: reorder waypoints, save, verify `manual_routes.json` updated

### Not tested
- Browser-side JS (no JS test framework in repo)
- Visual regression (manual eye-check only)

## Out of scope

- Linking `food[].items` to the `camping-planner-food/foods.yaml` library — separate future iteration
- Multi-user concurrent editing (optimistic locking, ETags) — design supports adding it later
- Mobile/responsive polish — current trip page is mobile-OK; new design carries that forward but doesn't add new responsive work
- Authentication/authorization — existing identity system carries forward unchanged
- Merging `origin/main` — deferred per user direction; this design survives the eventual merge

## Open questions for review

None left from brainstorming. Spec is ready for plan-writing once the user signs off.
