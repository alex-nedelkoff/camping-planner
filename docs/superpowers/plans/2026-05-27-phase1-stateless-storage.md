# Phase 1 — Stateless Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all runtime writes (trip content + checklist) off the local filesystem into Supabase Postgres behind a dual, env-selected storage backend, with in-memory caches — so the app runs on any stateless host while local dev + tests stay filesystem-based and DB-free.

**Architecture:** A slug-addressed `trip_repo` (filesystem + Postgres impls) replaces the Path-based `trip_store`. Caches move to an in-memory TTL store. `db.py` keeps the checklist API but dispatches SQLite vs Postgres by `STORAGE_BACKEND`. Call sites stop building `TRIPS_DIR / slug` Paths and go through the repo by slug.

**Tech Stack:** FastAPI, Pydantic v2, psycopg 3 + psycopg_pool (Postgres), pytest. Postgres-backed tests are gated on `TEST_DATABASE_URL` (skipped otherwise); the default suite runs filesystem + in-memory.

**Conventions:** Use `python3 -m pytest`. Modules read mutable config as `from app import config` then `config.X` (so tests monkeypatch `app.config.X`). Camis/Open-Meteo always mocked.

---

## File Structure

- `app/config.py` — add `STORAGE_BACKEND`, `DATABASE_URL`.
- `app/services/cache.py` — **new**: in-memory TTL cache (replaces db cache helpers).
- `app/services/trip_repo.py` — **new**: repo interface + `FilesystemTripRepo` + `PostgresTripRepo` + `get_repo()`.
- `app/services/pg.py` — **new**: psycopg pool + `ensure_schema()`.
- `app/services/db.py` — drop cache helpers/tables; checklist dispatches sqlite/postgres.
- `app/services/availability.py`, `weather_cache.py`, `route_cache.py` — use `cache.py`.
- `app/services/trips.py`, `app/routes/{trip_pages,trips,pages,checklist}.py` — call `trip_repo` by slug.
- `app/main.py` — boot wiring per backend.
- `scripts/migrate_to_supabase.py`, `scripts/export_trips.py` — **new**.
- `requirements.txt` — add psycopg.

---

## Task 1: Config — storage backend selection

**Files:** Modify `app/config.py`; Test `tests/test_config_backend.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_backend.py
import importlib
import app.config as config


def test_storage_backend_defaults_to_filesystem(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    importlib.reload(config)
    assert config.STORAGE_BACKEND == "filesystem"
    assert config.DATABASE_URL is None


def test_storage_backend_from_env(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    importlib.reload(config)
    assert config.STORAGE_BACKEND == "postgres"
    assert config.DATABASE_URL == "postgresql://x/y"


def teardown_module(module):
    importlib.reload(config)  # restore defaults for other tests
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config_backend.py -q`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'STORAGE_BACKEND'`.

- [ ] **Step 3: Add config**

Append to `app/config.py`:

```python
import os

# Storage backend: "filesystem" (default, local/dev/tests) or "postgres".
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "filesystem")
# Postgres connection string (Supabase pooled URL or a local Postgres).
DATABASE_URL = os.environ.get("DATABASE_URL") or None
```

(Place the `import os` with the other imports at the top if not already present.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config_backend.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config_backend.py
git commit -m "feat(storage): STORAGE_BACKEND + DATABASE_URL config"
```

---

## Task 2: In-memory TTL cache

**Files:** Create `app/services/cache.py`; Test `tests/test_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cache.py
import time
from app.services import cache


def setup_function(_):
    cache.clear()


def test_set_then_get_returns_payload():
    cache.set("weather_cache", ("balsam", "a", "b"), {"t": 1})
    assert cache.get("weather_cache", ("balsam", "a", "b"), ttl_seconds=100) == {"t": 1}


def test_get_missing_returns_none():
    assert cache.get("weather_cache", ("nope",), ttl_seconds=100) is None


def test_get_expired_returns_none(monkeypatch):
    cache.set("weather_cache", ("k",), {"v": 1})
    monkeypatch.setattr(cache.time, "time", lambda: time.time() + 1000)
    assert cache.get("weather_cache", ("k",), ttl_seconds=10) is None


def test_namespaces_are_isolated():
    cache.set("weather_cache", ("k",), {"v": "w"})
    cache.set("availability_cache", ("k",), {"v": "a"})
    assert cache.get("availability_cache", ("k",), ttl_seconds=100) == {"v": "a"}


def test_drop_prefix_removes_matching_keys():
    cache.set("route_cache", ("trip-1", "h1"), {"v": 1})
    cache.set("route_cache", ("trip-1", "h2"), {"v": 2})
    cache.set("route_cache", ("trip-2", "h1"), {"v": 3})
    cache.drop_prefix("route_cache", ("trip-1",))
    assert cache.get("route_cache", ("trip-1", "h1"), ttl_seconds=100) is None
    assert cache.get("route_cache", ("trip-2", "h1"), ttl_seconds=100) == {"v": 3}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.cache`.

- [ ] **Step 3: Implement**

```python
# app/services/cache.py
"""In-process TTL cache for regenerable data (availability/weather/route).

Replaces the SQLite cache tables. Keyed by (namespace,) + tuple key; values are
(stored_at, payload). Per-process — acceptable for short-TTL, regenerable data.
"""
from __future__ import annotations

import time

_store: dict[tuple, tuple[float, dict]] = {}


def _k(table: str, key: tuple) -> tuple:
    return (table,) + tuple(key)


def get(table: str, key: tuple, ttl_seconds: float) -> dict | None:
    entry = _store.get(_k(table, key))
    if entry is None:
        return None
    stored_at, payload = entry
    if (time.time() - stored_at) > ttl_seconds:
        return None
    return payload


def set(table: str, key: tuple, payload: dict) -> None:
    _store[_k(table, key)] = (time.time(), payload)


def drop_prefix(table: str, key_prefix: tuple) -> None:
    prefix = _k(table, key_prefix)
    n = len(prefix)
    for k in [k for k in _store if k[:n] == prefix]:
        del _store[k]


def clear() -> None:
    _store.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cache.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/cache.py tests/test_cache.py
git commit -m "feat(storage): in-memory TTL cache"
```

---

## Task 3: Point cache wrappers at the in-memory cache

**Files:** Modify `app/services/availability.py`, `app/services/weather_cache.py`, `app/services/route_cache.py`; Test: existing `tests/` for these still pass.

- [ ] **Step 1: Update availability.py**

In `app/services/availability.py`, replace the `from app.services import db` import with `from app.services import cache`, and swap the two calls:
- `db.cache_get(CACHE_TABLE, key, AVAILABILITY_CACHE_TTL)` → `cache.get(CACHE_TABLE, key, AVAILABILITY_CACHE_TTL)`
- `db.cache_set(CACHE_TABLE, key, payload)` → `cache.set(CACHE_TABLE, key, payload)`

- [ ] **Step 2: Update weather_cache.py**

Same swap in `app/services/weather_cache.py`:
- import `cache` instead of `db`
- `db.cache_get(...)` → `cache.get(...)`; `db.cache_set(...)` → `cache.set(...)`

- [ ] **Step 3: Update route_cache.py to use cache + repo routes**

Replace `app/services/route_cache.py` with:

```python
"""Cache rendered route HTML + computed distances per trip (in-memory).

Key: (trip_slug, sha256(routes payload)). Routes come from the trip repo.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable, Optional

from app.services import cache

CACHE_TABLE = "route_cache"
DEFAULT_TTL = 60 * 60 * 24 * 30  # 30 days — invalidated by content hash anyway


def _hash_routes(routes_payload) -> str:
    if not routes_payload:
        return "no-routes"
    blob = json.dumps(routes_payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def get_route_render(slug: str, provider: Optional[Callable] = None) -> dict:
    """Return {html, distance_km, ...} for this trip's routes, cached."""
    from app.services import trip_repo
    routes_payload = trip_repo.get_repo().get_routes(slug) or []
    key = (slug, _hash_routes(routes_payload))
    cached = cache.get(CACHE_TABLE, key, DEFAULT_TTL)
    if cached is not None:
        return cached

    if provider is None:
        from app.services import route_provider
        provider = route_provider.render

    payload = provider(routes_payload, slug)
    cache.set(CACHE_TABLE, key, payload)
    return payload


def invalidate(slug: str) -> None:
    """Best-effort invalidation. Drops all cache rows for this trip."""
    cache.drop_prefix(CACHE_TABLE, (slug,))
```

NOTE: `get_route_render` signature changed from `(routes_path, slug, provider)` to `(slug, provider)` — its caller in `trip_pages.py` is updated in Task 6, and `trip_repo` lands in Task 4. Until then this module imports `trip_repo` lazily inside the function, so import won't break; but route-render tests will fail until Task 4/6. If existing `tests/test_route_cache.py` calls the old signature, mark those updates as part of this step: update them to `get_route_render(slug)` and to seed routes via a `FilesystemTripRepo` — **if Task 4 isn't done yet, do Task 4 before running these.** (Executor: implement Task 4 immediately after, or reorder 3↔4; they are co-dependent. Recommended: do Task 4 first, then return here.)

- [ ] **Step 4: Run the affected tests**

Run: `python3 -m pytest tests/test_availability*.py tests/test_weather*.py -q` (and route tests after Task 4).
Expected: availability + weather tests PASS. (These tests mock the Camis/Open-Meteo providers and assert caching; they should pass with the in-memory cache. If a test monkeypatched `db.cache_*`, update it to monkeypatch/clear `cache`.)

- [ ] **Step 5: Commit**

```bash
git add app/services/availability.py app/services/weather_cache.py app/services/route_cache.py tests/
git commit -m "refactor(cache): availability/weather/route use in-memory cache"
```

---

## Task 4: Trip repository — interface + FilesystemTripRepo + factory

**Files:** Create `app/services/trip_repo.py`; Test `tests/test_trip_repo_fs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trip_repo_fs.py
import pytest
from app import config
from app.models_trip import Trip, TripDates
from app.services import trip_repo
from app.services.trip_repo import FilesystemTripRepo, SchemaVersionError


def _trip(slug="balsam-lake-2026-05"):
    return Trip(schema_version=1, name=slug, park="balsam-lake", mode="car_camping",
                dates=TripDates(start="2026-05-30", end="2026-05-31"))


def test_save_get_exists_roundtrip(tmp_path):
    repo = FilesystemTripRepo(tmp_path)
    assert repo.exists("x") is False
    assert repo.get("x") is None
    repo.save("x", _trip("x"))
    assert repo.exists("x") is True
    got = repo.get("x")
    assert got.park == "balsam-lake" and got.mode == "car_camping"


def test_list_slugs_sorted(tmp_path):
    repo = FilesystemTripRepo(tmp_path)
    repo.save("b", _trip("b"))
    repo.save("a", _trip("a"))
    assert repo.list_slugs() == ["a", "b"]


def test_delete(tmp_path):
    repo = FilesystemTripRepo(tmp_path)
    repo.save("x", _trip("x"))
    repo.delete("x")
    assert repo.exists("x") is False


def test_routes_roundtrip(tmp_path):
    repo = FilesystemTripRepo(tmp_path)
    repo.save("x", _trip("x"))
    assert repo.get_routes("x") is None
    repo.set_routes("x", [{"name": "leg1"}])
    assert repo.get_routes("x") == [{"name": "leg1"}]


def test_bad_schema_version_raises(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "trip.json").write_text('{"schema_version": 99, "name": "x", "park": "p",'
                                 ' "dates": {"start": "2026-05-30", "end": "2026-05-31"}}')
    with pytest.raises(SchemaVersionError):
        FilesystemTripRepo(tmp_path).get("x")


def test_get_repo_filesystem_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    repo = trip_repo.get_repo()
    assert isinstance(repo, FilesystemTripRepo)
    repo.save("x", _trip("x"))
    assert trip_repo.get_repo().get("x").park == "balsam-lake"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_trip_repo_fs.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.trip_repo`.

- [ ] **Step 3: Implement**

```python
# app/services/trip_repo.py
"""Slug-addressed trip repository. Source-of-truth gateway for trip content.

Two backends, selected by config.STORAGE_BACKEND:
- FilesystemTripRepo: trips/<slug>/trip.json (+ manual_routes.json). Default.
- PostgresTripRepo:  a `trips` table (added in a later task).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app import config
from app.models_trip import SCHEMA_VERSION, Trip

TRIP_JSON_NAME = "trip.json"
ROUTES_NAME = "manual_routes.json"


class SchemaVersionError(Exception):
    """Raised when stored trip data has an unsupported schema_version."""


def _validate(raw: dict) -> Trip:
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"trip schema_version={version!r}, expected {SCHEMA_VERSION}"
        )
    return Trip.model_validate(raw)


class FilesystemTripRepo:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)

    def _dir(self, slug: str) -> Path:
        return self.base / slug

    def get(self, slug: str) -> Optional[Trip]:
        p = self._dir(slug) / TRIP_JSON_NAME
        if not p.exists():
            return None
        return _validate(json.loads(p.read_text(encoding="utf-8")))

    def save(self, slug: str, trip: Trip) -> None:
        d = self._dir(slug)
        d.mkdir(parents=True, exist_ok=True)
        (d / TRIP_JSON_NAME).write_text(
            json.dumps(trip.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )

    def exists(self, slug: str) -> bool:
        return (self._dir(slug) / TRIP_JSON_NAME).exists()

    def list_slugs(self) -> list[str]:
        if not self.base.exists():
            return []
        return sorted(
            sub.name for sub in self.base.iterdir()
            if sub.is_dir() and (sub / TRIP_JSON_NAME).exists()
        )

    def delete(self, slug: str) -> None:
        import shutil
        d = self._dir(slug)
        if d.exists():
            shutil.rmtree(d)

    def get_routes(self, slug: str) -> Any:
        p = self._dir(slug) / ROUTES_NAME
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def set_routes(self, slug: str, data: Any) -> None:
        d = self._dir(slug)
        d.mkdir(parents=True, exist_ok=True)
        (d / ROUTES_NAME).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_repo():
    """Return the configured repo. Reads config live (test-friendly)."""
    if config.STORAGE_BACKEND == "postgres":
        from app.services.trip_repo_pg import PostgresTripRepo
        return PostgresTripRepo()
    return FilesystemTripRepo(config.TRIPS_DIR)
```

(`PostgresTripRepo` and its module land in Task 8; `get_repo()` only imports it when `STORAGE_BACKEND == "postgres"`, so filesystem mode works now.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_trip_repo_fs.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/trip_repo.py tests/test_trip_repo_fs.py
git commit -m "feat(storage): trip_repo interface + FilesystemTripRepo + factory"
```

---

## Task 5: Route `trips` service through the repo

**Files:** Modify `app/services/trips.py`; Test: update `tests/` that exercise `list_trips_v2`/`create_trip_v2`.

- [ ] **Step 1: Update `list_trips_v2`**

In `app/services/trips.py`, rewrite `list_trips_v2` to use the repo (drop the `trips_dir` Path scan):

```python
def list_trips_v2() -> list[dict]:
    """List trips via the storage repo. Sorted by start date."""
    from app.services import trip_repo
    repo = trip_repo.get_repo()
    entries = []
    for slug in repo.list_slugs():
        t = repo.get(slug)
        if t is None:
            continue
        park_info = parks_svc.load_park_info(t.park) if t.park else {}
        entries.append({
            "slug": slug, "name": t.name, "park": t.park,
            "park_name": park_info.get("name"),
            "start": t.dates.start, "end": t.dates.end,
            "participant_count": len(t.participants),
        })
    entries.sort(key=lambda e: e["start"])
    for i, e in enumerate(entries):
        e["prev_slug"] = entries[i - 1]["slug"] if i > 0 else None
        e["next_slug"] = entries[i + 1]["slug"] if i < len(entries) - 1 else None
    return entries
```

- [ ] **Step 2: Update `create_trip_v2`**

Rewrite the body to use the repo (no `mkdir`, no Path):

```python
def create_trip_v2(park: str, start_date, end_date, participants: list[str], mode: str = "paddle") -> str:
    """Create a new trip via the storage repo. Returns the slug."""
    from datetime import date as _date
    from app.services import trip_repo
    from app.models_trip import Trip, TripDates
    if not park:
        raise ValueError("park required")
    sd = _date.fromisoformat(str(start_date))
    ed = _date.fromisoformat(str(end_date))
    if ed < sd:
        raise ValueError("end date before start")
    slug = f"{park}-{sd.year:04d}-{sd.month:02d}"
    repo = trip_repo.get_repo()
    if repo.exists(slug):
        raise FileExistsError(slug)
    trip = Trip(schema_version=1, name=slug, park=park, mode=mode,
                dates=TripDates(start=sd, end=ed),
                participants=participants or [], access_point="")
    repo.save(slug, trip)
    return slug
```

- [ ] **Step 3: Update the tests that monkeypatched `trips_svc.TRIPS_DIR`**

These tests must now point the filesystem repo's base via `app.config.TRIPS_DIR`. In each affected test (e.g. `tests/test_create_trip_mode.py`, `tests/test_trip_page_modes.py`, any using `monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_path)`), change the target to:

```python
import app.config as config
monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
```

(The repo reads `config.TRIPS_DIR` live, so this redirects it.)

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_create_trip_mode.py -q`
Expected: PASS (the create-trip tests work through the repo). Then `python3 -m pytest -q` and fix any remaining `TRIPS_DIR`-monkeypatch tests the same way.

- [ ] **Step 5: Commit**

```bash
git add app/services/trips.py tests/
git commit -m "refactor(trips): list/create via trip_repo (by slug)"
```

---

## Task 6: Route the request handlers through the repo

**Files:** Modify `app/routes/trip_pages.py`, `app/routes/trips.py`, `app/routes/pages.py`, `app/routes/checklist.py`; Test: `tests/test_trip_page_modes.py`, `tests/test_sites_routes.py`, route tests.

- [ ] **Step 1: trip_pages.py**

In `app/routes/trip_pages.py`: replace the `trip_dir = trips_svc.TRIPS_DIR / slug` + `trip_store.load(trip_dir)` block with repo access, and the route render call:

```python
    from app.services import trip_repo
    trip = trip_repo.get_repo().get(slug)
    if trip is None:
        raise HTTPException(status_code=404, detail="trip not found")
```

and (in the paddle branch) change:

```python
        route_render = route_cache.get_route_render(slug)
```

(remove the `routes_path = trip_dir / "manual_routes.json"` line entirely).

- [ ] **Step 2: trips.py**

In `app/routes/trips.py`, replace every `trip_dir = trips_svc.TRIPS_DIR / slug` + `trip_store.load/exists/save` with repo calls, e.g.:

```python
    from app.services import trip_repo
    repo = trip_repo.get_repo()
    trip = repo.get(slug)
    if trip is None:
        raise HTTPException(status_code=404, detail="trip not found")
    ...
    repo.save(slug, new_trip)
```

For the manual_routes write route, replace `(trip_dir / "manual_routes.json").write_text(...)` with `repo.set_routes(slug, <parsed payload>)`; for reads use `repo.get_routes(slug)`. For the delete route, replace `shutil.rmtree(trip_dir)` with:

```python
    if not repo.exists(slug):
        raise HTTPException(status_code=404, detail="trip not found")
    repo.delete(slug)
```

(Remove now-unused `shutil` import if nothing else uses it.)

- [ ] **Step 3: pages.py**

In `app/routes/pages.py`, replace `trip_store.load(trips_svc.TRIPS_DIR / trip)` with `trip_repo.get_repo().get(trip)` (and handle `None` where it previously caught `FileNotFoundError`).

- [ ] **Step 4: checklist.py**

In `app/routes/checklist.py`, replace `_ensure_trip`:

```python
def _ensure_trip(slug: str) -> None:
    from app.services import trip_repo
    if not slug or not trip_repo.get_repo().exists(slug):
        raise HTTPException(status_code=404,
                            detail={"ok": False, "error": "trip not found"})
```

(Remove the now-unused `from app.services.trips import TRIPS_DIR` import.)

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest -q`
Expected: PASS — the full suite (filesystem backend). Fix any remaining direct `trip_store`/`TRIPS_DIR` references the same way (search: `grep -rn "trip_store\|TRIPS_DIR /" app/`). The old `app/services/trip_store.py` should now have no importers; delete it and its test if present:

```bash
grep -rn "trip_store" app/ tests/   # expect no hits
git rm app/services/trip_store.py tests/test_trip_store.py 2>/dev/null || true
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(routes): address trips by slug via trip_repo; drop trip_store"
```

---

## Task 7: Postgres connection + schema (`pg.py`)

**Files:** Modify `requirements.txt`; Create `app/services/pg.py`, `app/services/schema.sql`; Test `tests/test_pg.py`

- [ ] **Step 1: Add dependency**

Append to `requirements.txt`:

```
psycopg[binary]>=3.1
psycopg_pool>=3.2
```

Install: `python3 -m pip install 'psycopg[binary]>=3.1' 'psycopg_pool>=3.2'`

- [ ] **Step 2: Create schema.sql**

```sql
-- app/services/schema.sql
create table if not exists trips (
  slug text primary key,
  data jsonb not null,
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

- [ ] **Step 3: Write the failing test (gated on a real DB)**

```python
# tests/test_pg.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL to run Postgres-backed tests",
)


def test_pool_and_schema(monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    from app.services import pg
    pg.reset_pool()
    pg.ensure_schema()
    with pg.connection() as conn:
        row = conn.execute("select 1 as n").fetchone()
    assert row[0] == 1
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 -m pytest tests/test_pg.py -q`
Expected: SKIPPED if no `TEST_DATABASE_URL` (acceptable); if set, FAIL — `ModuleNotFoundError: app.services.pg`.

- [ ] **Step 5: Implement pg.py**

```python
# app/services/pg.py
"""Postgres connection pool + schema bootstrap (used when STORAGE_BACKEND=postgres)."""
from __future__ import annotations

from pathlib import Path

from app import config

_pool = None
_SCHEMA = Path(__file__).with_name("schema.sql")


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        if not config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is required for STORAGE_BACKEND=postgres")
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=5, open=True)
    return _pool


def reset_pool() -> None:
    """Drop the cached pool (tests / config changes)."""
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = None


def connection():
    """Context manager yielding a pooled connection (autocommit)."""
    return _get_pool().connection()


def ensure_schema() -> None:
    with connection() as conn:
        conn.execute(_SCHEMA.read_text())
```

- [ ] **Step 6: Run test**

Run: `TEST_DATABASE_URL=... python3 -m pytest tests/test_pg.py -q` (if you have a Postgres; else it skips).
Expected: PASS with a DB, SKIPPED without. Also run `python3 -m pytest -q` (full suite still green, pg untouched).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt app/services/pg.py app/services/schema.sql tests/test_pg.py
git commit -m "feat(storage): psycopg pool + schema bootstrap"
```

---

## Task 8: PostgresTripRepo + Postgres checklist

**Files:** Create `app/services/trip_repo_pg.py`; Modify `app/services/db.py`; Test `tests/test_repo_contract.py`

- [ ] **Step 1: Write the failing contract test (parametrized over backends)**

```python
# tests/test_repo_contract.py
import os
import pytest
from app.models_trip import Trip, TripDates
from app.services.trip_repo import FilesystemTripRepo

PG_URL = os.environ.get("TEST_DATABASE_URL")


def _trip(slug):
    return Trip(schema_version=1, name=slug, park="balsam-lake", mode="car_camping",
                dates=TripDates(start="2026-05-30", end="2026-05-31"))


def _make_pg_repo():
    import app.config as config
    config.DATABASE_URL = PG_URL
    from app.services import pg
    from app.services.trip_repo_pg import PostgresTripRepo
    pg.reset_pool(); pg.ensure_schema()
    with pg.connection() as conn:
        conn.execute("truncate trips")
    return PostgresTripRepo()


@pytest.fixture(params=["fs", "pg"])
def repo(request, tmp_path):
    if request.param == "fs":
        return FilesystemTripRepo(tmp_path)
    if not PG_URL:
        pytest.skip("set TEST_DATABASE_URL for the postgres backend")
    return _make_pg_repo()


def test_contract_roundtrip(repo):
    assert repo.get("x") is None and repo.exists("x") is False
    repo.save("x", _trip("x"))
    assert repo.exists("x") and repo.get("x").park == "balsam-lake"
    repo.set_routes("x", [{"leg": 1}])
    assert repo.get_routes("x") == [{"leg": 1}]
    repo.save("a", _trip("a"))
    assert set(repo.list_slugs()) >= {"a", "x"}
    repo.delete("x")
    assert repo.exists("x") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_repo_contract.py -q`
Expected: the `fs` cases FAIL — `ModuleNotFoundError: app.services.trip_repo_pg` (collection import error); `pg` cases skip without a DB.

- [ ] **Step 3: Implement PostgresTripRepo**

```python
# app/services/trip_repo_pg.py
"""Postgres-backed trip repository (STORAGE_BACKEND=postgres)."""
from __future__ import annotations

import json
from typing import Any, Optional

from app.models_trip import Trip
from app.services import pg
from app.services.trip_repo import SchemaVersionError, _validate


class PostgresTripRepo:
    def get(self, slug: str) -> Optional[Trip]:
        with pg.connection() as conn:
            row = conn.execute("select data from trips where slug = %s", (slug,)).fetchone()
        if row is None:
            return None
        data = row[0]
        return _validate(data if isinstance(data, dict) else json.loads(data))

    def save(self, slug: str, trip: Trip) -> None:
        payload = json.dumps(trip.model_dump(mode="json"))
        with pg.connection() as conn:
            conn.execute(
                "insert into trips (slug, data) values (%s, %s::jsonb) "
                "on conflict (slug) do update set data = excluded.data, updated_at = now()",
                (slug, payload),
            )

    def exists(self, slug: str) -> bool:
        with pg.connection() as conn:
            row = conn.execute("select 1 from trips where slug = %s", (slug,)).fetchone()
        return row is not None

    def list_slugs(self) -> list[str]:
        with pg.connection() as conn:
            rows = conn.execute("select slug from trips order by slug").fetchall()
        return [r[0] for r in rows]

    def delete(self, slug: str) -> None:
        with pg.connection() as conn:
            conn.execute("delete from trips where slug = %s", (slug,))

    def get_routes(self, slug: str) -> Any:
        with pg.connection() as conn:
            row = conn.execute("select manual_routes from trips where slug = %s", (slug,)).fetchone()
        if row is None or row[0] is None:
            return None
        return row[0] if not isinstance(row[0], str) else json.loads(row[0])

    def set_routes(self, slug: str, data: Any) -> None:
        with pg.connection() as conn:
            conn.execute("update trips set manual_routes = %s::jsonb, updated_at = now() "
                         "where slug = %s", (json.dumps(data), slug))
```

(`SchemaVersionError` is unused here directly but `_validate` raises it — import kept for clarity; drop if your linter objects.)

- [ ] **Step 4: Add Postgres checklist dispatch to db.py**

In `app/services/db.py`, add `from app import config` and make the two public checklist functions dispatch:

```python
def checklist_load(trip_slug: str, user: str = "", path=None) -> dict[str, bool]:
    if config.STORAGE_BACKEND == "postgres":
        from app.services import pg
        with pg.connection() as conn:
            rows = conn.execute(
                "select item_key, checked from checklist_state "
                "where trip_slug = %s and app_user = %s", (trip_slug, user)).fetchall()
        return {r[0]: bool(r[1]) for r in rows}
    # filesystem/sqlite path (existing implementation below)
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT item_key, checked FROM checklist_state WHERE trip_slug = ? AND user = ?",
            (trip_slug, user)).fetchall()
    return {r["item_key"]: bool(r["checked"]) for r in rows}


def checklist_set(trip_slug: str, item_key: str, checked: bool, user: str = "", path=None) -> None:
    if config.STORAGE_BACKEND == "postgres":
        from app.services import pg
        with pg.connection() as conn:
            conn.execute(
                "insert into checklist_state (trip_slug, item_key, app_user, checked) "
                "values (%s, %s, %s, %s) "
                "on conflict (trip_slug, item_key, app_user) do update set "
                "checked = excluded.checked, updated_at = now()",
                (trip_slug, item_key, user, checked))
        return
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO checklist_state (trip_slug, item_key, user, checked, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(trip_slug, item_key, user) DO UPDATE SET "
            "checked = excluded.checked, updated_at = excluded.updated_at",
            (trip_slug, item_key, user, 1 if checked else 0, time.time()))
```

Also remove the now-dead cache helpers (`cache_get`, `cache_set`, `cache_get_json`, `cache_set_json`, `cache_drop_prefix`) and the three cache tables from `_BASE_SCHEMA` (leave only the checklist DDL handling in `init_schema`). Confirm nothing imports them: `grep -rn "db.cache_" app/ tests/` (expect none after Task 3).

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_repo_contract.py tests/test_cache.py -q` then full `python3 -m pytest -q`.
Expected: `fs` contract cases PASS; `pg` cases PASS with `TEST_DATABASE_URL` else SKIP; full suite green.

- [ ] **Step 6: Commit**

```bash
git add app/services/trip_repo_pg.py app/services/db.py tests/test_repo_contract.py
git commit -m "feat(storage): PostgresTripRepo + Postgres checklist dispatch"
```

---

## Task 9: Boot wiring

**Files:** Modify `app/main.py`; Test `tests/test_boot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_boot.py
import app.config as config


def test_filesystem_boot_uses_sqlite(monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    from app import main
    main.init_storage()  # must not raise without a DATABASE_URL


def test_postgres_boot_requires_pool(monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(config, "DATABASE_URL", None)
    from app import main
    import pytest
    with pytest.raises(RuntimeError):
        main.init_storage()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_boot.py -q`
Expected: FAIL — `AttributeError: module 'app.main' has no attribute 'init_storage'`.

- [ ] **Step 3: Implement**

In `app/main.py`, replace the current boot `db.init_schema()` call with a backend-aware `init_storage()`:

```python
def init_storage() -> None:
    from app import config
    if config.STORAGE_BACKEND == "postgres":
        from app.services import pg
        pg.ensure_schema()  # raises RuntimeError if DATABASE_URL missing
    else:
        from app.services import db
        db.init_schema()


init_storage()
```

(Keep the existing `TRIPS_DIR.mkdir(exist_ok=True)` only for filesystem mode — guard it with `if config.STORAGE_BACKEND != "postgres":`.)

- [ ] **Step 4: Run test + full suite**

Run: `python3 -m pytest tests/test_boot.py -q` then `python3 -m pytest -q`.
Expected: PASS; full suite green; `python3 -c "import app.main"` still boots (filesystem default).

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_boot.py
git commit -m "feat(storage): backend-aware boot (sqlite vs postgres schema)"
```

---

## Task 10: Migration + export scripts

**Files:** Create `scripts/migrate_to_supabase.py`, `scripts/export_trips.py`; Test `tests/test_migrate_export.py`

- [ ] **Step 1: Write the failing test (gated on a real DB)**

```python
# tests/test_migrate_export.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL to run migration round-trip",
)


def test_migrate_then_export_roundtrip(tmp_path, monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    # seed one filesystem trip
    d = tmp_path / "balsam-lake-2026-05"; d.mkdir()
    (d / "trip.json").write_text('{"schema_version":1,"name":"balsam-lake-2026-05",'
        '"park":"balsam-lake","mode":"car_camping",'
        '"dates":{"start":"2026-05-30","end":"2026-05-31"}}')
    from app.services import pg
    pg.reset_pool(); pg.ensure_schema()
    with pg.connection() as conn:
        conn.execute("truncate trips")
    import scripts.migrate_to_supabase as mig
    mig.run(tmp_path)
    # export into a fresh dir
    out = tmp_path / "out"; out.mkdir()
    import scripts.export_trips as exp
    exp.run(out)
    assert (out / "balsam-lake-2026-05" / "trip.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_migrate_export.py -q`
Expected: SKIP without `TEST_DATABASE_URL`; with it, FAIL (`ModuleNotFoundError: scripts.migrate_to_supabase`).

- [ ] **Step 3: Implement migrate_to_supabase.py**

```python
# scripts/migrate_to_supabase.py
"""Push filesystem trips (trips/<slug>/trip.json + manual_routes.json) into Postgres.

Usage: DATABASE_URL=... python3 -m scripts.migrate_to_supabase [trips_dir]
Idempotent (upsert).
"""
from __future__ import annotations

import sys
from pathlib import Path

from app import config
from app.services.trip_repo import FilesystemTripRepo
from app.services.trip_repo_pg import PostgresTripRepo
from app.services import pg


def run(trips_dir: Path) -> int:
    pg.ensure_schema()
    fs = FilesystemTripRepo(Path(trips_dir))
    dst = PostgresTripRepo()
    n = 0
    for slug in fs.list_slugs():
        trip = fs.get(slug)
        if trip is None:
            continue
        dst.save(slug, trip)
        routes = fs.get_routes(slug)
        if routes is not None:
            dst.set_routes(slug, routes)
        n += 1
        print(f"  migrated {slug}")
    print(f"done: {n} trips")
    return n


if __name__ == "__main__":
    trips_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.TRIPS_DIR
    run(trips_dir)
```

- [ ] **Step 4: Implement export_trips.py**

```python
# scripts/export_trips.py
"""Dump Postgres trips back to filesystem JSON (backup / hydrate dev).

Usage: DATABASE_URL=... python3 -m scripts.export_trips [out_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

from app import config
from app.services.trip_repo import FilesystemTripRepo
from app.services.trip_repo_pg import PostgresTripRepo


def run(out_dir: Path) -> int:
    src = PostgresTripRepo()
    fs = FilesystemTripRepo(Path(out_dir))
    n = 0
    for slug in src.list_slugs():
        trip = src.get(slug)
        if trip is None:
            continue
        fs.save(slug, trip)
        routes = src.get_routes(slug)
        if routes is not None:
            fs.set_routes(slug, routes)
        n += 1
        print(f"  exported {slug}")
    print(f"done: {n} trips")
    return n


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.TRIPS_DIR
    run(out_dir)
```

- [ ] **Step 5: Run test**

Run: `python3 -m pytest tests/test_migrate_export.py -q` (skips without DB; with `TEST_DATABASE_URL`, PASS). Full suite: `python3 -m pytest -q` green.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_to_supabase.py scripts/export_trips.py tests/test_migrate_export.py
git commit -m "feat(storage): migrate + export scripts (filesystem <-> postgres)"
```

---

## Self-Review Notes

- **Spec coverage:** trip_repo seam + FS/PG impls (T4, T8); Postgres schema (T7); in-memory caches replacing the 3 SQLite cache tables (T2, T3, T8 removes helpers); checklist dispatch (T8); call-site Path→slug refactor (T5, T6); psycopg/pg.py (T7); config + dual backend (T1); boot wiring (T9); migrate + export bidirectional dev sync (T10); env-selected launch-time switch (T1 + get_repo reading config live). Read-only assets untouched (non-goal). Auth/deploy excluded (Phases 2/3).
- **Verification caveat:** Postgres-path tests are gated on `TEST_DATABASE_URL` (skipped in DB-free CI). To exercise the Postgres backend, run with a local Postgres or the Supabase URL set; otherwise it's verified during the Phase 3 deploy. The filesystem backend keeps the full suite green at every task.
- **Type consistency:** repo method names/signatures (`get/save/exists/list_slugs/delete/get_routes/set_routes`) are identical across `FilesystemTripRepo` (T4), `PostgresTripRepo` (T8), the contract test (T8), and call sites (T5, T6). `cache.get/set/drop_prefix/clear` consistent across T2/T3. `route_cache.get_route_render(slug, provider=None)` matches its T6 caller. `get_repo()` reads `config.STORAGE_BACKEND`/`config.TRIPS_DIR` live (T4), which T5/T6 tests rely on by monkeypatching `app.config`.
