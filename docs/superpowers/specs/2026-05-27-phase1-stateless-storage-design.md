# Phase 1 — Stateless Storage (Supabase Postgres) — Design

**Date:** 2026-05-27
**Branch:** local/water-polygon-union
**Status:** Approved (design)

## Context

This is Phase 1 of a 3-phase transition to host the app and share it with friends
(Phase 2 = Supabase Auth + permissions; Phase 3 = deploy). Phase 1 removes the
app's dependence on a writable local disk so it can run on any stateless host,
moving runtime writes into Supabase Postgres.

Today two things are written at runtime:
- **Trip content** — `trips/<slug>/trip.json` (the `Trip` model) plus an optional
  `manual_routes.json` side-file. Addressed everywhere as `TRIPS_DIR / slug` and
  read/written through `app/services/trip_store.py`.
- **SQLite** (`camping.sqlite3`) via `app/services/db.py`: regenerable caches
  (availability/weather/route) and `checklist_state` (per-user packing checkboxes).

Read-only assets (images, site surveys, `parks.json`, etc., ≈2.3 MB) are only ever
read; they ship in the deploy image and are out of scope.

## Goal

Move all runtime writes off the filesystem behind the existing seams, with a
**dual storage backend** selected by environment so local dev and the test suite
stay filesystem-based (fast, DB-free) while production runs on Postgres.

## Decisions (resolved during brainstorming)

- **All Supabase** for the DB (Phase 2 adds its Auth).
- **Dual backend, env-selected** at launch time via `STORAGE_BACKEND`
  (`filesystem` default | `postgres`). No runtime toggle.
- **Caches → in-memory TTL** (regenerable; drop persistent cache tables).
- **Trip content → Postgres JSONB blob** per slug (mirrors the `Trip` model; no
  normalized columns).
- Dev can point at the real Supabase or a local Postgres via `DATABASE_URL`;
  data moves both directions via migrate/export scripts.

## Design

### 1. Trip repository seam (`app/services/trip_repo.py`)

A slug-addressed repository replaces the Path-based `trip_store`:

```
get(slug: str) -> Trip | None
save(slug: str, trip: Trip) -> None
exists(slug: str) -> bool
list_slugs() -> list[str]
delete(slug: str) -> None
get_routes(slug: str) -> dict | None      # manual_routes payload
set_routes(slug: str, data: dict) -> None
```

`SchemaVersionError` and `Trip` (de)serialization live here. A factory
`get_repo()` returns a process-singleton backend chosen by `STORAGE_BACKEND`.

Two implementations:
- **`FilesystemTripRepo`** (default) — current behavior: `trips/<slug>/trip.json`
  + `manual_routes.json` under a configurable base dir (so tests can point it at a
  tmp dir, preserving today's `TRIPS_DIR` monkeypatch pattern). `get` raises
  nothing for missing (returns `None`); `SchemaVersionError` on bad version.
- **`PostgresTripRepo`** — backed by the `trips` table; `data`/`manual_routes`
  are JSONB.

### 2. Postgres schema

```sql
create table if not exists trips (
  slug text primary key,
  data jsonb not null,            -- Trip.model_dump(mode="json")
  manual_routes jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists checklist_state (
  trip_slug text not null,
  item_key  text not null,
  app_user  text not null default '',
  checked   boolean not null,
  updated_at timestamptz not null default now(),
  primary key (trip_slug, item_key, app_user)
);
```

No cache tables. `save` upserts (`on conflict (slug) do update`) and bumps
`updated_at`.

### 3. Caches → in-memory (`app/services/cache.py`)

A tiny in-process store: dict keyed by the existing tuple keys, value
`(expires_at, payload)`, honoring the current TTLs in `app/config.py`
(`AVAILABILITY_CACHE_TTL`, `WEATHER_CACHE_TTL`). The wrappers
`availability_cache` / `weather_cache` / `route_cache` switch to it. The three
SQLite cache tables (`availability_cache`, `weather_cache`, `route_cache`) are
removed from the schema. Per-instance caches are acceptable for short-TTL,
regenerable data.

### 4. Checklist (`app/services/db.py`)

Keep the public API unchanged — `checklist_load(trip_slug, user)` and
`checklist_set(trip_slug, item_key, checked, user)`. Internally dispatch on
`STORAGE_BACKEND`: SQLite (`camping.sqlite3`) in filesystem mode, Postgres
`checklist_state` in postgres mode. `db.py` no longer owns cache tables.

### 5. Postgres access (`app/services/pg.py`)

Add **psycopg (v3)**. `pg.py` builds connections from `DATABASE_URL` (a Supabase
pooled connection string, or a local Postgres) using a small `psycopg_pool`
connection pool. Schema is applied by the migration script and re-asserted with
`create … if not exists` on boot when backend = postgres.

### 6. Call-site refactor (Path -> slug)

Update the seams' consumers to address trips by slug via `trip_repo`:
- `app/routes/trip_pages.py`: `trip_store.load(TRIPS_DIR/slug)` -> `trip_repo.get(slug)`;
  `manual_routes.json` read -> `trip_repo.get_routes(slug)`.
- `app/routes/trips.py`: load/exists/save -> repo; `manual_routes` write ->
  `set_routes`; trip delete (`shutil.rmtree`) -> `trip_repo.delete(slug)`.
- `app/routes/pages.py`, `app/routes/checklist.py`: existence/load via repo.
- `app/services/trips.py`: `list_trips_v2` iterates `trip_repo.list_slugs()` +
  `get`; `create_trip_v2` uses `exists`/`save` (no `mkdir`).
- `app/services/route_cache.py`: `get_route_render` takes the routes dict from
  `trip_repo.get_routes(slug)` rather than a filesystem path.

The legacy markdown path (`scan_trips`/`create_trip` reading/writing `trip.md`) is
not used by the server-rendered trip pages (trips carry no `trip.md`); leave it
untouched unless a consumer is found during implementation.

### 7. Config + boot

`app/config.py` gains `STORAGE_BACKEND` (env, default `"filesystem"`) and
`DATABASE_URL` (env). `app/main.py` boot: postgres -> init pool + ensure schema;
filesystem -> current SQLite `init_schema`.

### 8. Migration + export scripts (bidirectional dev sync)

- `scripts/migrate_to_supabase.py` — read each `trips/*/trip.json` (+
  `manual_routes.json`) and upsert into `trips`; optionally copy
  `checklist_state` rows from `camping.sqlite3`. Idempotent. Run with
  `DATABASE_URL` set.
- `scripts/export_trips.py` — dump Postgres `trips` back to `trips/<slug>/trip.json`
  (+ routes), so the filesystem can be hydrated from live data and snapshotted to
  git for backup.

## Testing

- Default suite runs **filesystem backend + in-memory caches**: the existing 182
  tests stay green (no DB), Camis still mocked. Update tests only where they
  reached into `trip_store`/`TRIPS_DIR` directly to use the repo (filesystem) with
  a tmp base dir.
- New unit tests: `cache.py` TTL set/get/expiry/drop-prefix; `FilesystemTripRepo`
  CRUD + routes + `SchemaVersionError`.
- **Backend contract test** parametrized over backends: filesystem always;
  Postgres only when `TEST_DATABASE_URL` is set (otherwise skipped), so CI stays
  DB-free while the Postgres SQL is coverable on demand.
- Migration/export: unit-tested with a tmp filesystem repo against a
  `TEST_DATABASE_URL` Postgres when present (else skipped).

## Trade-offs / risks

- **Trip content stops being git-tracked** (DB becomes truth) — disaster recovery
  shifts to Supabase backups + `export_trips.py`. Biggest behavioral change.
- **In-memory caches are per-instance** — fine for short-TTL regenerable data.
- **Concurrent trip edits remain last-write-wins**; `updated_at` is recorded but
  optimistic locking is deferred.
- **Supabase free DB pauses after ~7 days idle** and the pooler has connection
  limits — acceptable at this scale.

## Non-goals (Phase 1)

- No auth (Phase 2). Cookie identity stays.
- No normalized trip columns (JSONB blob only).
- No moving read-only bundled assets (images/surveys/config) off disk.
- No runtime backend toggle (launch-time env only).
- No deploy/hosting work (Phase 3).
