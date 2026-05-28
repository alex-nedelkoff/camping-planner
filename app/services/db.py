"""SQLite persistence for operational state.

The DB holds **caches and per-trip toggles only** — it is never the source of
truth for trip content. If `camping.sqlite3` is deleted, the app re-creates the
schema empty on next startup; nothing in `trips/` is affected. See
FastAPI-refactor.md "Phase 2" for the design rationale.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.config import DATABASE_PATH
from app import config

# _BASE_SCHEMA removed: availability/weather/route cache tables dropped (Task 8)
# Cache is now in-memory (app/services/cache.py)

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


_FEEDBACK_DDL = """
CREATE TABLE IF NOT EXISTS feedback (
    id         TEXT PRIMARY KEY,
    author     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    body       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open',
    image      BLOB,
    image_mime TEXT,
    created_at REAL NOT NULL
);
"""

_TRIP_COMMENTS_DDL = """
CREATE TABLE IF NOT EXISTS trip_comments (
    id         TEXT PRIMARY KEY,
    trip_slug  TEXT NOT NULL,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS trip_comments_slug_idx ON trip_comments (trip_slug, created_at);
"""

_RECIPES_DDL = """
CREATE TABLE IF NOT EXISTS recipes (
    id           TEXT PRIMARY KEY,
    author       TEXT NOT NULL,
    name         TEXT NOT NULL,
    style        TEXT NOT NULL,
    meal         TEXT NOT NULL,
    servings     INTEGER NOT NULL DEFAULT 1,
    prep_minutes INTEGER,
    cook_minutes INTEGER,
    ingredients  TEXT NOT NULL DEFAULT '[]',
    steps        TEXT NOT NULL DEFAULT '',
    prep_at_home TEXT,
    gear         TEXT,
    tags         TEXT NOT NULL DEFAULT '[]',
    notes        TEXT,
    image        BLOB,
    image_mime   TEXT,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS recipes_style_idx ON recipes (style);
CREATE INDEX IF NOT EXISTS recipes_meal_idx  ON recipes (meal);
"""


def init_schema(path: Path | None = None) -> None:
    """Create / migrate tables. Idempotent — safe to call on every boot."""
    with connect(path) as conn:
        _ensure_checklist_state(conn)
        conn.executescript(_FEEDBACK_DDL)
        conn.executescript(_TRIP_COMMENTS_DDL)
        conn.executescript(_RECIPES_DDL)


def _ensure_checklist_state(conn: sqlite3.Connection) -> None:
    """Bring `checklist_state` to the v1 schema. Handles fresh + Phase 2 DBs."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(checklist_state)")}
    if not cols:
        conn.executescript(_CHECKLIST_V1_DDL)
    elif "user" not in cols:
        conn.executescript(_CHECKLIST_V0_TO_V1)



# ---------------------------------------------------------------------------
# Checklist state
# ---------------------------------------------------------------------------


def checklist_load(
    trip_slug: str,
    user: str = "",
    path: Path | None = None,
) -> dict[str, bool]:
    """Return {item_key: checked} for a trip and user. Empty user='' = shared."""
    if config.STORAGE_BACKEND == "postgres":
        from app.services import pg
        with pg.connection() as conn:
            rows = conn.execute(
                "select item_key, checked from checklist_state "
                "where trip_slug = %s and app_user = %s", (trip_slug, user)).fetchall()
        return {r[0]: bool(r[1]) for r in rows}
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
            "INSERT INTO checklist_state "
            "(trip_slug, item_key, user, checked, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(trip_slug, item_key, user) DO UPDATE SET "
            "checked = excluded.checked, updated_at = excluded.updated_at",
            (trip_slug, item_key, user, 1 if checked else 0, time.time()),
        )
