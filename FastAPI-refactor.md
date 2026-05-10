# FastAPI Refactor Plan

Migration plan for swapping the hand-rolled `launch.py` HTTP server for a FastAPI application. Markdown stays the source of truth for trip content; this refactor is purely about replacing the web layer.

---

## Status

- **Phase 1** — done. FastAPI app at `app/`, served by `uvicorn app.main:app`. All previous endpoints reproduced 1:1.
- **Phase 2** — done. SQLite at `camping.sqlite3` (gitignored) for caches and checklist sync. Markdown still source of truth for trip content.
- **Phase 3** — done. Cookie-based identity (no password); per-user packing checklists. v0 (Phase 2) DBs auto-migrate on first boot.

## Decisions (locked for this pass)

1. **Source of truth: markdown files in `trips/<slug>/`.** Git history continues to be the change log for trip plans. SQLite holds operational state only — caches and per-trip toggles. Delete `camping.sqlite3` and the app rebuilds the schema empty on next boot; nothing in `trips/` is affected.
2. **Auxiliary modules untouched.** `build_trip.py`, `ontario_parks.py`, `weather.py`, `route_engine.py`, `route_map.py`, `osm_data.py` are pure functions. The cache wrappers live in `app/services/`. `build_trip.py` got a single-line injection point (`weather_provider`) so the FastAPI path uses cached weather while the CLI stays zero-dep.
3. **Identity deferred.** Checklist sync is shared (any user toggling syncs to all). Per-user state requires identity — Phase 3.

---

## Why FastAPI (vs. keeping `http.server`)

- Replaces ~300 lines of hand-rolled `do_GET` / `do_POST` / JSON encoding / param parsing with declarative routes and Pydantic models.
- Free OpenAPI docs at `/docs` — useful when adding endpoints later (Phase 2 caches, checklist sync).
- Jinja2 templates pull the inline CSS/JS strings out of `launch.py` (currently ~140 lines of embedded HTML/JS/CSS) into editable files.
- `TestClient` makes route tests trivial; the current handlers have no tests.

---

## Proposed file structure

New / modified items marked. Everything else unchanged.

```
camping-planner/
├── app/                              # NEW — FastAPI application package
│   ├── __init__.py
│   ├── main.py                       # FastAPI() instance, StaticFiles mounts, uvicorn entry
│   ├── config.py                     # REPO_ROOT, TRIPS_DIR, TEMPLATE_DIR, PARKS_JSON
│   ├── models.py                     # Pydantic request/response schemas
│   ├── services/                     # Business logic — wraps existing modules
│   │   ├── __init__.py
│   │   ├── trips.py                  # scan_trips, split_trips, create_trip, save_gear_table
│   │   └── availability.py           # thin wrapper around ontario_parks.check_park
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── pages.py                  # GET /  (index page)
│   │   ├── trips.py                  # POST /api/new-trip, /api/rebuild, /api/save-gear
│   │   └── parks.py                  # GET  /api/availability
│   ├── templates/                    # Jinja2 templates (server-rendered HTML)
│   │   ├── base.html
│   │   ├── index.html
│   │   └── partials/
│   │       └── trip_card.html
│   └── static/                       # Extracted from launch.py inline strings
│       ├── css/
│       │   └── index.css
│       └── js/
│           └── index.js
│
├── tests/
│   ├── __init__.py                   # existing
│   ├── test_build_trip.py            # existing — unchanged
│   ├── test_routes.py                # NEW — FastAPI TestClient tests
│   └── fixtures/                     # existing
│
├── build_trip.py                     # UNCHANGED
├── ontario_parks.py                  # UNCHANGED
├── weather.py                        # UNCHANGED
├── route_engine.py                   # UNCHANGED
├── route_map.py                      # UNCHANGED
├── osm_data.py                       # UNCHANGED
├── parks.json                        # UNCHANGED
├── park_activities.json              # UNCHANGED
├── api_attribute_filterable.json     # UNCHANGED
├── map_names_cache.json              # UNCHANGED
├── osm_killarney_cache.json          # UNCHANGED
├── templates/trip-template/          # UNCHANGED — markdown skeletons (note: NOT Jinja templates)
├── trips/                            # UNCHANGED — markdown source of truth
│
├── launch.py                         # KEPT during transition, DELETED after Phase 1 lands
├── requirements.txt                  # MODIFIED — add fastapi, uvicorn[standard], jinja2, python-multipart
├── README.md                         # MODIFIED — new run command
├── CLAUDE.md                         # MODIFIED — note new entry point + structure
└── FastAPI-refactor.md               # this document
```

Two folders named `templates/` is intentional: the repo-level `templates/trip-template/` holds **markdown** skeletons users copy into a new trip; `app/templates/` holds **Jinja2** templates for the web UI. Different layers, different purposes.

---

## Endpoint mapping (1:1 with current `launch.py`)

| Current handler                  | New route                             | Notes                                                 |
|----------------------------------|---------------------------------------|-------------------------------------------------------|
| `_serve_index`                   | `GET /` → `pages.py`                  | Renders `index.html` via Jinja2                       |
| `super().do_GET()` for `/trips/` | `StaticFiles` mount on `/trips`       | Serves generated `trip.html` and any sibling assets   |
| `_handle_availability`           | `GET /api/availability` → `parks.py`  | Query params validated by Pydantic                    |
| `_handle_rebuild`                | `POST /api/rebuild` → `trips.py`      | Returns `{ok, message}` like today                    |
| `_handle_new_trip`               | `POST /api/new-trip` → `trips.py`     | JSON body → `NewTripRequest` Pydantic model           |
| `_handle_save_gear`              | `POST /api/save-gear` → `trips.py`    | JSON body → `SaveGearRequest`; rewrites `gear.md`     |

Response shapes stay identical so the existing inline JS in `build_trip.py` (`/api/save-gear` call) keeps working without changes.

---

## Phase 1 — task breakdown

### 1. Dependencies
- Add to `requirements.txt`:
  - `fastapi>=0.110`
  - `uvicorn[standard]>=0.27`
  - `jinja2>=3.1`
  - `python-multipart>=0.0.9` (for any future form posts)
- `pip install -r requirements.txt`.

### 2. Skeleton (`app/main.py`, `app/config.py`)
- `FastAPI(title="Camping Planner")` instance.
- Mount `StaticFiles(directory="app/static")` at `/static`.
- Mount `StaticFiles(directory="trips")` at `/trips` so generated `trip.html` files remain reachable at the same URL paths they use today.
- `Jinja2Templates(directory="app/templates")`.
- `config.py` centralises `REPO_ROOT`, `TRIPS_DIR`, `TEMPLATE_DIR`, `PARKS_JSON` (currently duplicated in `launch.py` and `build_trip.py`).

### 3. Pydantic models (`app/models.py`)
- `NewTripRequest { park: str, start: date, end: date, participants: list[str] }`
- `SaveGearRequest { rows: list[list[str]] }`
- `AvailabilityQuery { park: str, start: date, end: date }`
- Response models for the three success/error JSON shapes the frontend already consumes.

### 4. Services (`app/services/`)
Move the non-HTTP logic out of `launch.py`:
- `trips.scan_trips()`, `trips.split_trips()`, `trips.create_trip(park, start, end, participants)`, `trips.save_gear_table(slug, rows)`, `trips.rebuild(slug)`
- `availability.check(park, start, end)` — wraps `ontario_parks.check_park` and reshapes the result the way `_handle_availability` does today.

These functions take primitives and return primitives — no `self`, no request objects. Makes them trivially testable and easy to call from Phase 2 background jobs if we ever add them.

### 5. Routes (`app/routes/`)
Three small modules, registered with `app.include_router(...)` in `main.py`. Each route is a thin shell: validate input via Pydantic, call into `services/`, return.

### 6. Templates (`app/templates/`)
- `base.html` — `<head>` shell with `index.css` link.
- `index.html` — port the current f-string from `launch.py:render_index`. Loops over `upcoming`, `past`, `broken` lists passed from the route.
- `partials/trip_card.html` — port `_trip_card`.

Keep markup byte-identical where possible so the existing CSS/JS keeps working.

### 7. Static assets (`app/static/`)
- `index.css` — paste of the current `INDEX_CSS` constant.
- `index.js` — paste of the current `INDEX_JS` constant. The `fetch('/api/...')` URLs already match the new routes.

### 8. Tests (`tests/test_routes.py`)
Use `fastapi.testclient.TestClient`. Cover at minimum:
- `GET /` returns 200 and contains "Camping Trips".
- `POST /api/new-trip` with valid body creates the directory; with missing fields returns 400.
- `POST /api/rebuild` on a missing slug returns 404.
- `POST /api/save-gear` with malformed `rows` returns 400.
- `GET /api/availability` is fine to mock — don't hit Camis from tests (WAF risk noted in `CLAUDE.md`).

### 9. Run command + docs
- New entry point: `uvicorn app.main:app --reload --port 8000`
- Update `README.md` "Quick start" section.
- Update `CLAUDE.md` with the new layout and entry point.
- Delete `launch.py` once tests pass and the new server has been smoke-tested in a browser.

---

## Verification checklist (browser smoke test before deleting `launch.py`)

- [ ] Index loads at `http://127.0.0.1:8000/` and lists existing trips
- [ ] "Open Trip" link loads the generated `trip.html`
- [ ] "Rebuild" button regenerates the HTML
- [ ] "+ New Trip" form creates a trip directory and reloads
- [ ] "Check Park Availability" form returns campground counts
- [ ] In a generated trip page, the "Edit gear" → "Save" round-trip still rewrites `gear.md` and reloads
- [ ] Checklist checkboxes still persist (still `localStorage` in Phase 1 — moves to DB in Phase 2)

---

## Phase 2 — built

**Goal achieved:** SQLite holds operational state that doesn't fit in markdown. Markdown remains source of truth for *trip content*.

### What landed

- `app/services/db.py` — stdlib `sqlite3`, `init_schema()` called at app boot, generic `cache_get/cache_set` helpers, `checklist_load/checklist_set`. Schema uses `CREATE TABLE IF NOT EXISTS`; deleting `camping.sqlite3` is safe.
- Tables:
  - `availability_cache(park, start_date, end_date, fetched_at, payload)` — TTL `AVAILABILITY_CACHE_TTL` (15 min). Backs `/api/availability`. Avoids re-hitting the Camis WAF.
  - `weather_cache(park, start_date, end_date, fetched_at, payload)` — TTL `WEATHER_CACHE_TTL` (1 hour). Backs the weather block in generated trip pages (via `build_trip.weather_provider` injection).
  - `checklist_state(trip_slug, item_key, checked, updated_at)` — shared (no per-user yet). Replaces `localStorage` as the source of truth when reachable; `localStorage` stays as offline fallback.
- Endpoints: `GET /api/checklist?trip=<slug>`, `POST /api/checklist?trip=<slug>` with `{key, checked}`.
- `build_trip.py` JS rewritten to dual-write: paint from `localStorage` instantly, hydrate from `/api/checklist`, POST on change. Catches `fetch` errors so the page still works opened off a thumb drive.
- Tests: `tests/test_db.py` (8) + new route tests in `tests/test_routes.py` (cache hit assertion, checklist round-trip, 404s, validation).

### What was *not* built (and why)

- **`trips` mirror table.** The plan suggested it for "sort/filter on the index page." No such feature exists, and 10 trips × a few small markdown reads is microseconds. Premature; would just create a sync bug surface. Skipped per "don't design for hypothetical future requirements."
- **`audit_log` table.** Marked optional in the plan; no consumer.
- **Per-user checklist state.** Belongs in Phase 3 alongside identity. The `checklist_state` table omits `user` rather than storing nullable placeholders — adding a `user` column later is a one-statement migration and the obvious moment to do it.

### Cache invalidation, briefly

- Both caches are time-only (no manual bust). The `/api/availability` response now carries `cached: true|false` so the UI could expose a "refresh" button later. Not wired into the form yet.
- `availability.check(...)` accepts `force_refresh=True` for a future refresh control.
- Weather cache is keyed by `(park, start, end)` only — historical-vs-forecast switchover at 16-day boundary just produces a different payload that overwrites the row.

### Files added in Phase 2

- `app/services/db.py`
- `app/services/weather_cache.py`
- `app/routes/checklist.py`
- `tests/test_db.py`
- `camping.sqlite3` (gitignored)

### Files modified

- `app/config.py` — `DATABASE_PATH`, cache TTLs.
- `app/main.py` — `db.init_schema()` on boot; mount `checklist.router`.
- `app/models.py` — added `ChecklistGetResponse`, `ChecklistSetRequest`, `cached` field on `AvailabilityResponse`.
- `app/services/availability.py` — wraps the upstream call in cache get/set.
- `app/services/trips.py` — injects `weather_cache.get_weather` into `build_trip.weather_provider`.
- `app/routes/parks.py` — surfaces `cached` flag.
- `build_trip.py` — `weather_provider` injection point; checklist JS rewritten for dual-write.
- `.gitignore` — `*.sqlite3` family.

---

## Phase 3 — built

Driver: per-user packing checklists. All checkboxes in the generated trip pages come from `packing.md`, which is by design a personal list — sharing it across users was the wrong default.

### What landed

- `app/services/identity.py` — reads/writes the `cp_user` cookie, validates names against a small charset (letters, digits, space, `_`, `-`, `'`, `.`), 40-char cap. No password.
- `app/routes/identity.py` — `GET/POST/DELETE /api/whoami`. Sets a 1-year `cp_user` cookie (samesite=lax, not HttpOnly so the trip-page JS can render the pill).
- `app/services/db.py` — `checklist_state` PK now `(trip_slug, item_key, user)`. Empty string `user=''` is the shared bucket. `init_schema()` auto-migrates Phase 2 DBs by inspecting `PRAGMA table_info` — Phase 2 rows are promoted to `user=''`.
- `app/routes/checklist.py` — reads the user from the cookie on every request; routes are otherwise unchanged.
- UI: a `user-pill` lives in the index header and in every generated trip page. First visit triggers a name prompt on the index. Switching users on a trip page re-hydrates the checklist from the server. localStorage keys are namespaced per-user (`cb:<user>:<key>`) so two people on the same browser don't bleed.
- Tests: `tests/test_db.py` adds 4 (per-user isolation, shared/per-user coexistence, v0→v1 migration, idempotent migration); `tests/test_routes.py` adds 6 (whoami round-trip, name validation, cookie isolation between two TestClients, no-cookie = shared bucket).

### What was *not* built (and why)

- **`audit_log` table.** Plan called this out as becoming "useful at this point." Still no consumer (no UI surface, no alerting). Skipped per "don't design for hypothetical future requirements." When something actually needs it, the schema is a five-line addition.
- **Shared-password `HTTPBasic` gate.** Only relevant if the app is exposed beyond localhost. Currently runs at `127.0.0.1:8000`; revisit if/when deployment changes.

### Migration safety notes

- `init_schema()` is idempotent: detect-via-PRAGMA, not version pragma. Running it on a v1 DB is a no-op; running it on a v0 DB upgrades once and is then a no-op forever.
- The migration uses an explicit `RENAME → CREATE → INSERT … SELECT → DROP` sequence rather than `ALTER TABLE` because SQLite can't change a primary key in place. Wrapped in `executescript` (implicit transaction).
- If you ever need to roll back: the v0 schema is recoverable from any pre-Phase-3 git commit, and Phase 2 rows live under `user=''` in v1 — drop the column, re-add the original PK, and you're back.

---

## Out of scope (all phases so far)

- Authentication / accounts beyond a shared password. Trusted group of ≤8.
- Async job queue. The longest call (Camis availability) is a few seconds — fine inline.
- Postgres, migrations tooling (Alembic). SQLite + `CREATE TABLE IF NOT EXISTS` is sufficient at this size. If a real migration ever lands, write the SQL by hand and gate it on `PRAGMA user_version`.
- Frontend framework (React/Vue). Jinja2 + vanilla JS is enough; htmx is the escape hatch if interactivity grows.
