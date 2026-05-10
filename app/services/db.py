"""SQLite persistence for operational state.

The DB holds **caches and per-trip toggles only** — it is never the source of
truth for trip content. If `camping.sqlite3` is deleted, the app re-creates the
schema empty on next startup; nothing in `trips/` is affected. See
FastAPI-refactor.md "Phase 2" for the design rationale.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from app.config import DATABASE_PATH

_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS availability_cache (
    park       TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (park, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS weather_cache (
    park       TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (park, start_date, end_date)
);
"""

_CHECKLIST_V1_DDL = """
CREATE TABLE checklist_state (
    trip_slug  TEXT NOT NULL,
    item_key   TEXT NOT NULL,
    user       TEXT NOT NULL DEFAULT '',
    checked    INTEGER NOT NULL CHECK (checked IN (0, 1)),
    updated_at REAL NOT NULL,
    PRIMARY KEY (trip_slug, item_key, user)
);
"""

# v0 (Phase 2) → v1 (Phase 3): add `user` to PK. Old rows become "shared" (user='').
_CHECKLIST_V0_TO_V1 = """
ALTER TABLE checklist_state RENAME TO checklist_state_v0;
""" + _CHECKLIST_V1_DDL + """
INSERT INTO checklist_state (trip_slug, item_key, user, checked, updated_at)
    SELECT trip_slug, item_key, '', checked, updated_at FROM checklist_state_v0;
DROP TABLE checklist_state_v0;
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection. One per request is fine at this scale."""
    if path is None:
        path = DATABASE_PATH
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(path: Path | None = None) -> None:
    """Create / migrate tables. Idempotent — safe to call on every boot."""
    with connect(path) as conn:
        conn.executescript(_BASE_SCHEMA)
        _ensure_checklist_state(conn)


def _ensure_checklist_state(conn: sqlite3.Connection) -> None:
    """Bring `checklist_state` to the v1 schema. Handles fresh + Phase 2 DBs."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(checklist_state)")}
    if not cols:
        conn.executescript(_CHECKLIST_V1_DDL)
    elif "user" not in cols:
        conn.executescript(_CHECKLIST_V0_TO_V1)


# ---------------------------------------------------------------------------
# Generic JSON-blob cache helpers (used by availability + weather)
# ---------------------------------------------------------------------------


def cache_get(
    table: str,
    key: tuple[str, str, str],
    ttl_seconds: float,
    path: Path | None = None,
) -> dict | None:
    """Return cached payload if a fresh row exists, else None."""
    park, start, end = key
    with connect(path) as conn:
        row = conn.execute(
            f"SELECT fetched_at, payload FROM {table} "
            "WHERE park = ? AND start_date = ? AND end_date = ?",
            (park, start, end),
        ).fetchone()
    if row is None:
        return None
    if (time.time() - row["fetched_at"]) > ttl_seconds:
        return None
    return json.loads(row["payload"])


def cache_set(
    table: str,
    key: tuple[str, str, str],
    payload: dict,
    path: Path | None = None,
) -> None:
    """Upsert a payload into a cache table."""
    park, start, end = key
    with connect(path) as conn:
        conn.execute(
            f"INSERT INTO {table} (park, start_date, end_date, fetched_at, payload) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(park, start_date, end_date) DO UPDATE SET "
            "fetched_at = excluded.fetched_at, payload = excluded.payload",
            (park, start, end, time.time(), json.dumps(payload)),
        )


# ---------------------------------------------------------------------------
# Checklist state
# ---------------------------------------------------------------------------


def checklist_load(
    trip_slug: str,
    user: str = "",
    path: Path | None = None,
) -> dict[str, bool]:
    """Return {item_key: checked} for a trip and user. Empty user='' = shared."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT item_key, checked FROM checklist_state "
            "WHERE trip_slug = ? AND user = ?",
            (trip_slug, user),
        ).fetchall()
    return {r["item_key"]: bool(r["checked"]) for r in rows}


def checklist_set(
    trip_slug: str,
    item_key: str,
    checked: bool,
    user: str = "",
    path: Path | None = None,
) -> None:
    """Upsert a single checklist item state for a user."""
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO checklist_state "
            "(trip_slug, item_key, user, checked, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(trip_slug, item_key, user) DO UPDATE SET "
            "checked = excluded.checked, updated_at = excluded.updated_at",
            (trip_slug, item_key, user, 1 if checked else 0, time.time()),
        )
