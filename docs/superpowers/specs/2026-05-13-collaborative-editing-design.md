# Collaborative Editing — Design

**Status:** Draft for review
**Topic:** Multi-user live editing of trip food and gear plans, hosted publicly.

## Goal

Let Alex and Thomas (plus 2–4 other trip friends) live-edit a Killarney trip's food and gear plans from anywhere, with changes propagating to other connected viewers within ~1 second. Keep the existing markdown-as-source-of-truth + `build_trip.py` pipeline intact: hosting adds a live editing layer on top, it does not replace the git story.

## Non-goals

- Multi-machine horizontal scaling. Single Fly machine, in-process SSE fan-out.
- Per-cell presence ("Thomas is editing this row right now"). Whole-trip presence only.
- Real-time CRDT-style collaborative typing in a single textarea.
- Automatic server-side git commits / pushes. Snapshots write files to the volume; commits happen out-of-band from the developer's local machine.
- Mobile-app wrapper. The web app is responsive; that's enough.
- Push notifications. Updates are visible to users who have the page open.

## Architecture

### Runtime

- **Fly.io** single `shared-cpu-1x` machine, 256MB RAM, `auto_stop_machines = "suspend"` and `min_machines_running = 0` so it sleeps when idle.
- **SQLite** on a 1GB Fly volume mounted at `/data`, holding both `camping.sqlite3` and a writable copy of `trips/` (the markdown files snapshot writes to).
- **FastAPI + uvicorn** — same app as today, packaged in a Dockerfile.

### Auth

Email magic-link, per-trip allowlist. The trip owner adds an email to the allowlist; that user then logs in by entering their email, receiving a one-time link, and clicking it. The link sets a signed session cookie (30-day expiry).

The existing cookie-based `cp_user` identity is replaced by a proper `sessions` cookie. The per-user checklist table already keys on a user identifier, so migration maps the old free-text `cp_user` string to a real `user_id` row on first boot.

### Sync

Server-Sent Events. One stream per trip, scoped to trip membership.

```
GET /trips/<slug>/events   →   text/event-stream
```

Edits flow client → REST POST → DB → in-process broadcast to all SSE subscribers for that trip. Heartbeat (`: ping`) every 20 seconds keeps proxies from culling idle connections. EventSource handles reconnect on the client side; on reconnect the client does a one-shot GET of the food + gear endpoints to catch up on missed events.

SSE was chosen over WebSockets because we only need server → client push (edits go through plain REST), `EventSource` is built into every browser with automatic reconnect, and Fly's edge proxy is happier with long-lived SSE than WebSockets.

### Component layout

```
app/
  routes/
    auth.py        ← NEW: magic-link issue + verify + logout
    sse.py         ← NEW: /trips/<slug>/events streaming endpoint
    food.py        ← NEW: structured food row CRUD
    gear.py        ← NEW: structured gear row CRUD
    trips.py       ← extend: snapshot-to-git endpoint
  services/
    auth.py        ← NEW: magic-link tokens + session management
    mailer.py      ← NEW: Resend transport for magic-link emails
    broadcast.py   ← NEW: in-process SSE pub/sub (asyncio.Queue per client)
    snapshot.py   ← NEW: DB rows → markdown → build_trip.py → write
    db.py          ← extend: new tables (see Data Model)
  templates/
    _macros.jinja        ← NEW: render_row, render_presence, render_avatar
    trip_food.jinja      ← NEW: full food editor
    trip_gear.jinja      ← NEW: full gear editor (replaces existing inline)
    login.jinja          ← NEW
    trip_members.jinja   ← NEW
  static/
    css/index.css        ← extend: font face, accent palette, edit affordances
    js/live.js           ← NEW: SSE connection, optimistic edit, conflict UI
    js/rows.js           ← NEW: inline editor + drag-reorder
    fonts/Fraunces.woff2 ← NEW: self-hosted variable display font

Dockerfile               ← NEW
fly.toml                 ← NEW
.dockerignore            ← NEW
scripts/
  pull-snapshot.sh       ← NEW: fly ssh sftp helper to pull /data/trips/ → local
  seed-from-markdown.py  ← NEW: idempotent first-boot seed of DB from markdown
```

Existing kept as-is: `build_trip.py`, `route_engine.py`, `route_map.py`, the OSM/Jeff data, `weather.py`, the markdown template skeletons. The snapshot service feeds the same markdown that `build_trip.py` already consumes.

### Backward compat

Local CLI workflow still works: `cp -r templates/trip-template`, edit markdown, run `build_trip.py`. The hosted app reads markdown on first load of a trip and seeds the DB tables (`seed-from-markdown.py`), so trips authored locally still show up correctly when their directory is included in the next deploy.

## Data model

### Auth / identity

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  display_name TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE magic_links (
  token TEXT PRIMARY KEY,        -- random 32-byte hex
  email TEXT NOT NULL,
  expires_at TEXT NOT NULL,      -- 15 min from issue
  consumed_at TEXT                -- nullable; null = unused
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,           -- cookie value
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL       -- 30 days
);

CREATE TABLE trip_members (
  trip_slug TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL CHECK (role IN ('owner','editor','viewer')),
  added_at TEXT NOT NULL,
  PRIMARY KEY (trip_slug, user_id)
);
```

### Structured content

```sql
CREATE TABLE food_items (
  id INTEGER PRIMARY KEY,
  trip_slug TEXT NOT NULL,
  day_index INTEGER NOT NULL,    -- 1, 2, 3...
  meal TEXT NOT NULL,            -- 'breakfast'|'lunch'|'dinner'|'snack'
  item TEXT NOT NULL,
  assigned_to TEXT,              -- free-text name (Alex / Thomas / "shared")
  notes TEXT,
  sort_order REAL NOT NULL,      -- fractional indexing for O(1) reorder
  updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id)
);
CREATE INDEX idx_food_trip ON food_items(trip_slug, day_index, meal, sort_order);

CREATE TABLE gear_items (
  id INTEGER PRIMARY KEY,
  trip_slug TEXT NOT NULL,
  category TEXT NOT NULL,        -- 'shelter','kitchen','navigation', etc.
  item TEXT NOT NULL,
  quantity TEXT,                 -- '2', '1 per person'
  assigned_to TEXT,
  notes TEXT,
  sort_order REAL NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id)
);
CREATE INDEX idx_gear_trip ON gear_items(trip_slug, category, sort_order);
```

`assigned_to` is free-text rather than FK to `users` because not every trip participant gets an account — a friend tagging along can still be assigned dinner duty.

### Live-edit bookkeeping

```sql
CREATE TABLE section_state (
  trip_slug TEXT NOT NULL,
  section TEXT NOT NULL,         -- 'food'|'gear'
  seeded_from_md_at TEXT,        -- when markdown → DB last ran
  last_snapshotted_at TEXT,      -- when DB → markdown last ran
  PRIMARY KEY (trip_slug, section)
);
```

`seeded_from_md_at` tells trip-page load whether to read from markdown (cold) or DB (warm). `last_snapshotted_at` compared against `max(food_items.updated_at)` tells us whether there are unsaved edits to surface in the "Snapshot to git" pip.

### Markdown ↔ DB mapping

`food.md` and `gear.md` become DB-canonical during a trip's active editing life. The "Snapshot to git" action regenerates the markdown from the structured rows. Round-tripping is one-way during normal use: edits go to DB only, and direct edits to `food.md` / `gear.md` in the editor would be overwritten on next snapshot. This is an accepted trade-off of the structured model — the value of multi-user editing, totals, and queryable assignment outweighs the loss of free-form markdown editing for these two sections specifically.

What does **not** move to the DB: `trip.md` (frontmatter + intro), `itinerary.md`, `costs.md`, `route.gpx/.kml`. They stay markdown-canonical and are not live-editable in v1.

## Sync mechanism

### Channel

`GET /trips/<slug>/events` opens an SSE stream. Auth requires a valid session cookie with `trip_members` row for that slug; else 403.

### Server-side broadcast

`app/services/broadcast.py` holds a module-level `subscribers: dict[str, set[asyncio.Queue]]` keyed by trip slug. Each connected client owns one `asyncio.Queue(maxsize=64)`. The route handler yields whatever lands in the queue as SSE-formatted lines.

POST handlers (food/gear edits) call `broadcast(trip_slug, event)`, which puts the event in every subscriber's queue for that trip. If a queue is full (slow or stuck client), drop the event for that subscriber only — they'll catch up on reconnect via the bulk GET. The DB is canonical; missed events are non-fatal.

### Event shapes

```json
{"type": "food.upsert", "row": {"id": 42, "day_index": 1, "meal": "dinner",
                                 "item": "Pasta", "assigned_to": "Alex",
                                 "notes": "", "sort_order": 1.0,
                                 "updated_at": "2026-05-13T..."}}
{"type": "food.delete", "id": 42}
{"type": "gear.upsert", "row": {...}}
{"type": "gear.delete", "id": 17}
{"type": "presence", "users": ["alex@...", "thomas@..."]}
{"type": "snapshot.saved", "by": "alex@...", "at": "2026-05-13T..."}
```

Client merges by `id`: upsert replaces the row in its local state, delete removes it. Whole-row payloads, no diffing — rows are small.

### Conflict handling

Last-write-wins per row, with detection. POSTs include `expected_updated_at` (the timestamp the client last saw for that row). If the server's current `updated_at` is greater than `expected_updated_at`, return `409 Conflict` with the current row body. The client surfaces an inline "Keep yours / Take theirs / Merge…" UI on the affected cell.

Edits are scoped to one row, so two people editing different meals never conflict. Same-cell conflicts within ~1s are rare in practice for food planning.

### Presence

Connect to `/trips/<slug>/events` → server adds you to a presence set keyed by trip slug → user id, broadcasts a `presence` event with the current member list. Disconnect → remove + rebroadcast. UI renders stacked avatar pips in the trip-page header. No per-row presence in v1.

### Single-machine assumption

The in-process subscriber dict means SSE only works correctly on a single Fly machine. If we ever scale out, we'd need Redis pub/sub for cross-machine fan-out. For 2–6 users this is well beyond the horizon; flagging but not designing for it now.

## Editing UI

### Aesthetic direction

Extend the existing voice: deep forest green (`#2d5016`), cream background, white cards, mossy secondary green (`#6b7a5a`), warm amber warnings. Reads like a modern Park-Service field guide — restrained, woodsy, intentional.

Two deliberate refinements:

- **Typography.** Introduce **Fraunces** (variable, with the "soft" axis dialled up for a warm/outdoorsy feel) for `h1` / `h2` / `h3`. Body stays system-stack. One self-hosted woff2, ~40KB.
- **Per-user accent palette.** Eight curated hues drawn from a Killarney palette: white-pine green, granite, lichen sage, birch cream, sumac red, sky-after-rain blue, ochre, plum. Each logged-in user gets a deterministic assignment via `hash(email) % 8` — same colour for that user everywhere: presence dot, "last edited by" stripe, row halo. Not user-pickable; simpler.

### Food editor

One screen per trip, grouped vertically by day, meals as horizontal sub-headers. Inline edit, no modals.

- **Click any cell → instant edit.** No "edit mode" toggle. Borderless input with a 2px focus ring in the editing user's accent colour.
- **Blur or Tab → save.** POST sent; 3px bottom-bar shimmer in the user's accent colour while inflight. Fades on 2xx. On 409: cell turns amber and shows "Keep yours / Take theirs" inline pill.
- **Drag a row's left-edge handle** to reorder within or across meals/days. Fractional `sort_order` so reorders are O(1).
- **`+ row`** opens an inline form (item, who, notes) at the bottom of the day. No modal.
- **`⋯`** → delete with a 5-second undo toast.

### Live update affordances

When another user changes a row you can see, it gets a brief halo: 600ms outline expansion in their accent colour, then fades. One pulse; not an extravagance. A small initial-pip in their colour lingers in the cell corner for ~10s post-edit, hover reveals "edited by Thomas, just now."

Your own edits are optimistic — UI updates before the server confirms; reconcile silently when the SSE echo returns.

### Gear editor

Same row pattern as food, grouped by category instead of day/meal. Replaces the current full-table-modal gear editor in `trips.py`. Categories collapse/expand; collapsed state per-user via localStorage. Per-category add-row at the foot.

### Mobile

On viewports < 720px, tables collapse to **stacked cards per row**: meal label as a pill above, item as primary text, who/notes as secondary lines. Tap to edit any field; opens a single-field inline editor focused where you tapped. Add-row becomes a sticky floating button bottom-right per day. Drag reorder is long-press on touch.

### Conflict resolution UX

On 409 from a save:

- Cell freezes in your edited state (amber border).
- Inline strip below the row: *"Thomas changed this 4s ago: 'Pasta + sausage' → 'Risotto'. Keep yours · Take theirs · Merge…"*
- "Merge…" opens a tiny side-by-side textarea so you can hand-merge.

### Auth / magic-link UI

- **`/login`** — one email input, one "send me a link" button. Submit swaps for a card: "Check your email — link sent to alex@…" with a `Resend` link after 30s.
- **Email** — minimal HTML, Fraunces heading "Killarney trip planner", one paragraph, one button. Inline-styled.
- **`/login/verify?token=…`** — "Welcome back, Alex" briefly, then redirect to `/` or the originally-requested trip page.
- **Trip-settings → members panel** — list with email + role dropdown + remove. Inline "add member" form below.

### Self-contained `trip.html` preserved

The static, offline-friendly `trip.html` produced by `build_trip.py` still renders food and gear from the markdown snapshot (read-only view). Live editing happens at `/trips/<slug>/edit/food` and `/trips/<slug>/edit/gear`, served by FastAPI. The "trip page works offline from disk" property is preserved.

## Save-to-git flow

### Manual snapshot (primary)

Button top-right of the trip page, next to presence pips: `📥 Snapshot to git`, with a subtle pip "N unsaved edits" when DB has changed since the last snapshot (computed from `section_state.last_snapshotted_at` vs `max(updated_at)` across food/gear rows for that trip).

Click → `POST /api/trips/<slug>/snapshot`:

1. `render_food_markdown(slug)` builds a deterministic markdown table from `food_items` rows, grouped day → meal, sorted by `sort_order`.
2. Same for `render_gear_markdown(slug)` from `gear_items`.
3. Write both files to `/data/trips/<slug>/`.
4. Invoke `build_trip.py /data/trips/<slug>/` to regenerate `trip.html`.
5. Update `section_state.last_snapshotted_at` for both sections.
6. Broadcast `snapshot.saved` SSE event — all connected clients flip "N unsaved edits" → "Saved · just now."
7. Return 200 with paths written.

**The server does not git-commit.** It has no git identity, no signing key, no GitHub credentials. Keeps the prod box credential-free.

### Pull-back to local git

`scripts/pull-snapshot.sh <slug>` runs `fly ssh sftp get /data/trips/<slug>/ trips/<slug>/`, then the developer reviews `git diff` locally, commits, pushes.

### Auto-snapshot on inactivity (secondary, off by default)

Background asyncio task per active trip: 30 minutes after the last edit, automatically run the same snapshot flow. Trip owner toggle in trip-settings. Off in v1 to keep behaviour predictable.

### Markdown rendering — deterministic

Same row state always produces byte-identical markdown. Re-snapshotting unchanged data is a no-op diff. Pipe characters in user-entered text are escaped (`\|`) on the way out.

## Deployment — Fly.io

### Dockerfile

`python:3.12-slim` base. Install `requirements.txt`. Copy app source. No system packages beyond `ca-certificates` — the snapshot pipeline writes files and invokes `build_trip.py`; neither needs git on the server. Entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port 8000`. Image ≈ 150MB.

### fly.toml highlights

- App name: `camping-planner` (or similar).
- One `shared-cpu-1x` machine, 256MB RAM.
- `auto_stop_machines = "suspend"`, `min_machines_running = 0` — scales to zero.
- Volume `cp_data`, 1GB, mounted at `/data`. Holds `camping.sqlite3` and `/data/trips/`.
- Health check: `GET /healthz` returns `{"ok": true}`.
- Public port 443, internal 8000.

### Secrets (`fly secrets set ...`)

- `SESSION_SECRET` — 32-byte random, signs session cookies.
- `MAGIC_LINK_SECRET` — HMAC pepper for magic-link tokens (defence-in-depth on top of random tokens).
- `MAIL_FROM` — sender address.
- `RESEND_API_KEY` — email transport. Resend's free tier (100/day) is wildly enough.
- `BASE_URL` — `https://camping-planner.fly.dev` initially.
- `BOOTSTRAP_OWNER_EMAIL` — email used by `seed-from-markdown.py` to create the initial owner `trip_members` row on first deploy.

### Env vars (non-secret)

- `DATA_DIR=/data` — overrides `TRIPS_DIR` and `DATABASE_PATH` defaults in `app/config.py`.
- `LOG_LEVEL=info`.

`app/config.py` change: read `DATA_DIR` env var, build `TRIPS_DIR` and `DATABASE_PATH` from it, fall back to today's repo-relative defaults when unset. Local CLI workflow unchanged.

### First-time seed

`scripts/seed-from-markdown.py` runs as a one-shot Fly machine task on deploy. Walks `trips/*/` in the image, parses `food.md` and `gear.md` tables into `food_items` / `gear_items` rows. Creates `trip_members` entries pointing at the bootstrap owner email (sourced from a `BOOTSTRAP_OWNER_EMAIL` env var). Idempotent — skips trips already represented in `section_state`.

### Ongoing trip provisioning

To host a trip created locally: include `trips/<slug>/` in the next deploy. Seed script picks it up on the next boot. To pull edits made on the host back to local: `scripts/pull-snapshot.sh <slug>`, then `git diff && git commit && git push`.

### Cost estimate

Fly.io: ~$2-4/month idle (volume only); ~$5-7/month with light active use. Resend: free tier. Domain (optional): ~$10/year.

## Tests

Existing 140 tests stay green. New coverage:

- `tests/test_snapshot.py` — DB rows → markdown is deterministic and byte-stable across re-runs; pipe-escape in item text round-trips.
- `tests/test_conflict.py` — POST with stale `expected_updated_at` returns 409 with current row body.
- `tests/test_sse.py` — `httpx.AsyncClient` opens the stream; a POST elsewhere triggers an event delivered to the stream within a small timeout.
- `tests/test_auth.py` — magic-link issue, verify, expire, double-consume rejected.
- `tests/test_seed.py` — `seed-from-markdown.py` parses an existing trip's food.md and gear.md into the expected rows.

The Camis API is still always mocked. No Fly-specific tests; the Dockerfile is verified by `docker build` locally before each deploy.

## Out of scope for v1

- Multi-machine SSE fan-out (Redis pub/sub).
- Per-cell presence indicators.
- Real-time CRDT collaborative typing in freeform textareas.
- Server-side automatic git commits / pushes.
- Mobile-app wrapper.
- Push notifications.
- Live-editable `itinerary.md`, `costs.md`, `trip.md`. These remain markdown-canonical and edit-via-CLI.

## Migration / rollout plan

1. Land schema + auth backend changes locally; existing tests stay green.
2. Add structured food/gear endpoints + SSE; cover with new tests.
3. Build editor UI; verify on local uvicorn.
4. Build snapshot service; verify round-trip on a real Killarney trip directory.
5. Add Dockerfile + fly.toml; verify `docker build` locally.
6. Provision Fly app, volume, secrets. Deploy.
7. Seed bootstrap owner (Alex), add Thomas as editor for the active Killarney trip.
8. Real-use shakedown: Alex + Thomas plan food for `killarney-2026-05` together, hit edge cases, file issues.
9. Pull snapshot back, commit to git, retire any one-off seed paths.
