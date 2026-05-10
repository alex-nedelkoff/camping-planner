# camping-planner

Shared trip planning for canoe and camping trips with friends. Markdown files
in `trips/<slug>/` are the source of truth; `build_trip.py` renders them into
a self-contained `trip.html` per trip; a small FastAPI app at `app/` provides
a browser UI for creating/rebuilding trips, editing the gear table, checking
park availability, and syncing per-user packing checklists across devices.

## Quick start

```bash
git clone git@github.com:alex-nedelkoff/camping-planner.git
cd camping-planner
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# open http://127.0.0.1:8000/
```

The web UI serves both the index (`/`) and individual trip pages
(`/trips/<slug>/trip.html`) so you don't need a separate static-file server.

## Two ways to work

Both paths write back to the same markdown files — pick whichever fits the moment.

**Edit-then-rebuild (git-first):**
```bash
$EDITOR trips/<slug>/packing.md
python3 build_trip.py trips/<slug>/
git add trips/<slug>/ && git commit -am "..." && git push
```

**Web UI:** open the index, click "+ New Trip" or "Rebuild" on any trip card,
or open a trip page and use the in-browser "Edit gear" button. Commit the
markdown changes afterwards.

## Persistence

- **Trip content** — markdown files in `trips/<slug>/`, committed to git.
- **Operational state** — `camping.sqlite3` at the repo root (gitignored,
  auto-created). Holds availability/weather caches and per-user packing
  checkbox state. Safe to delete; the app rebuilds an empty schema on next
  boot.

## Identity

On first visit the UI prompts for your name and stores it in a `cp_user`
cookie. The pill in the header lets you switch users; switching re-hydrates
the trip page's packing checkboxes against your personal state. No password
— the app is meant for a small trusted group on localhost. Leaving the name
blank uses a "shared" bucket.

## Starting a new trip

Either via the index "+ New Trip" form, or by hand:

```bash
cp -r templates/trip-template trips/<park>-<YYYY-MM>/
$EDITOR trips/<park>-<YYYY-MM>/trip.md  # fill in frontmatter
python3 build_trip.py trips/<park>-<YYYY-MM>/
```

Slug convention: `<park>-<YYYY-MM>` derived from `park` + `start_date`.

## Sensitive content

Anything you don't want committed (phone numbers, emergency contacts,
satellite-messenger PINs) goes in:

- `private/` — gitignored top-level folder
- `*.local.md` — gitignored anywhere

Sync these out-of-band.

## Park availability

The web UI has a "Check Park Availability" form on the index. CLI also works:

```bash
python3 ontario_parks.py check killarney --start 2026-05-15 --end 2026-05-18
```

See `CLAUDE.md` for the Ontario Parks API reference and Azure WAF rate-limit
warnings.

## Tests

```bash
pytest tests/ -q
```

79 tests, ~1s. Camis API is always mocked — tests never hit Ontario Parks.

## Repo layout

- `app/` — FastAPI web UI
  - `app/main.py` — entry point, route + static mounts, schema init
  - `app/config.py` — paths, cache TTLs
  - `app/models.py` — Pydantic schemas
  - `app/services/` — `db`, `trips`, `availability`, `weather_cache`, `identity`
  - `app/routes/` — `pages`, `trips`, `parks`, `checklist`, `identity`
  - `app/templates/`, `app/static/` — Jinja2 + extracted CSS/JS
- `build_trip.py` — markdown → HTML trip page generator
- `ontario_parks.py`, `weather.py`, `route_map.py`, `route_engine.py`, `osm_data.py` — auxiliary modules used by `build_trip.py`
- `parks.json`, `park_activities.json`, `api_attribute_filterable.json`, `map_names_cache.json`, `osm_killarney_cache.json` — park metadata + caches
- `templates/trip-template/` — markdown skeletons copied when creating a new trip (NB: not Jinja templates)
- `trips/` — one folder per trip
- `tests/` — pytest suite
- `legacy/` — pre-FastAPI sheet-driven flow, kept for reference
- `launch.py` — legacy stdlib HTTP server. Functionally replaced by `app/`; remove when you're confident nobody's still pointing at it
- `FastAPI-refactor.md` — refactor history (Phases 1–3 complete) and rationale for what was deferred

## Jeff's Maps vectorizer (optional)

If you have a Jeff's Maps KMZ for Killarney/French River (paid product),
you can extract its lake polygons and campsite locations into a cache
that augments the OSM data.

System dependency — Tesseract OCR binary:

- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr`

Run the extractor (one-shot, only when the map version changes):

```bash
python3 jeffs_extractor.py path/to/jeffs.kmz \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --out jeffs_killarney_cache.json
```

The KMZ itself is gitignored; only the extracted JSON is committed.
