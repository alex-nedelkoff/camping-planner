# UI Fix — Trip Launcher

## Problem

The current workflow to view a trip requires two manual steps:
1. `python -m http.server`
2. Navigate to `http://localhost:8000/trips/<name>/trip.html`

There is no index page and no way to act on trips (rebuild, create, check availability) without dropping to the terminal.

## Solution

Add `launch.py` — a small Python stdlib HTTP server that serves an index UI and handles trip actions.

```bash
python launch.py          # starts on 127.0.0.1:8000, opens browser automatically
python launch.py --port 9000
```

---

## UI Layout

```
┌───────────────────────────────────────┐
│  🏕 Camping Trips          [New Trip] │
├───────────────────────────────────────┤
│  Upcoming                             │
│                                       │
│  Killarney Provincial Park            │
│  May 15 → 18, 2026 · 2 participants  │
│  [Open Trip]  [Rebuild]               │
├───────────────────────────────────────┤
│  Past                                 │
│  (none yet)                           │
├───────────────────────────────────────┤
│  Check Park Availability              │
│  ⚠ Ontario Parks rate-limits — one   │
│    check at a time, please.           │
│  Park: [dropdown]  Start: [] End: []  │
│  [Check]  → results appear inline     │
└───────────────────────────────────────┘
```

- Same green/card aesthetic as the trip pages
- Trips sorted by `start_date` descending, split into **Upcoming** (end_date ≥ today) and **Past**
- "Rebuild" button shows a spinner while pending (rebuild calls Open-Meteo, ~2–5s), then "Rebuilt ✓"
- "Check" button is disabled while a request is in flight (WAF protection)
- "New Trip" expands an inline form

---

## Server Routes

| Method | Path | Action |
|--------|------|--------|
| `GET` | `/` | Render index page (scans `trips/*/trip.md` fresh each request; malformed trips are shown as warning cards, not fatal) |
| `GET` | `/trips/<name>/trip.html` | Static file passthrough |
| `POST` | `/api/rebuild?trip=<name>` | Calls `build_html()` from `build_trip.py`, returns `{ok, message}` |
| `POST` | `/api/new-trip` | Body: `{park, start, end, participants}` — derives slug, copies template, writes frontmatter, returns `{ok, trip_dir}` or `{ok: false, error}` if slug exists |
| `GET` | `/api/availability?park=<slug>&start=YYYY-MM-DD&end=YYYY-MM-DD` | Calls `check_park()` from `ontario_parks.py`, returns JSON results |

### New-trip slug rule

`<park>-<YYYY-MM>` derived from `park` + `start_date` (e.g. `killarney-2026-05`). If the directory already exists, return an error rather than overwriting — user must pick a different name (future enhancement: append `-2`, `-3`, etc.).

---

## Implementation Notes

- **No new dependencies** — stdlib only: `http.server`, `socketserver`, `threading`, `webbrowser`, `json`
- **Threading**: use `http.server.ThreadingHTTPServer`, not the default blocking `TCPServer`. Rebuild and availability calls hit external APIs and would otherwise freeze the UI.
- **Bind to `127.0.0.1`**, not `0.0.0.0` — POST endpoints touch disk and external APIs; no reason to expose them to the LAN.
- **chdir to script parent on startup** so `SimpleHTTPRequestHandler` serves static files correctly regardless of where `launch.py` is invoked from.
- Imports `build_html` from `build_trip.py` and `check_park` from `ontario_parks.py` directly.
- Index HTML is rendered in-memory and served; never written to disk.
- "New Trip" copies `templates/trip-template/`, then overwrites the frontmatter in `trip.md`.
- Park dropdown source: `parks.json`.
- Branch: `feature/ui_fix`.

---

## Out of scope

- Tests for `launch.py` (thin shim over already-tested code)
- Delete / archive trip actions
- Auto-numbering duplicate trip slugs

## Cleanup

Delete `ui_fix.md` (or move to `docs/`) when the feature ships — it's a planning doc, not long-lived documentation.
