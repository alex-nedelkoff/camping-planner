"""SQLite layer: schema init, generic cache, checklist state."""


import pytest

from app.services import db


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "test.sqlite3"
    db.init_schema(p)
    return p


def test_init_schema_is_idempotent(tmp_path):
    p = tmp_path / "x.sqlite3"
    db.init_schema(p)
    db.init_schema(p)
    with db.connect(p) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "checklist_state" in names


def test_checklist_round_trip(dbpath):
    db.checklist_set("trip-a", "gear--tent", True, path=dbpath)
    db.checklist_set("trip-a", "gear--paddles", False, path=dbpath)
    db.checklist_set("trip-b", "gear--tent", True, path=dbpath)
    assert db.checklist_load("trip-a", path=dbpath) == {
        "gear--tent": True, "gear--paddles": False,
    }
    assert db.checklist_load("trip-b", path=dbpath) == {"gear--tent": True}


def test_checklist_set_upserts(dbpath):
    db.checklist_set("t", "k", True, path=dbpath)
    db.checklist_set("t", "k", False, path=dbpath)
    assert db.checklist_load("t", path=dbpath) == {"k": False}


def test_checklist_load_empty_returns_empty_dict(dbpath):
    assert db.checklist_load("never-touched", path=dbpath) == {}


# ---------------------------------------------------------------------------
# Per-user checklist (Phase 3)
# ---------------------------------------------------------------------------


def test_checklist_user_isolation(dbpath):
    db.checklist_set("trip-a", "tent", True, user="Alex", path=dbpath)
    db.checklist_set("trip-a", "tent", False, user="Jordan", path=dbpath)
    assert db.checklist_load("trip-a", user="Alex", path=dbpath) == {"tent": True}
    assert db.checklist_load("trip-a", user="Jordan", path=dbpath) == {"tent": False}


def test_checklist_shared_and_per_user_coexist(dbpath):
    db.checklist_set("trip-a", "canoe", True, path=dbpath)              # shared
    db.checklist_set("trip-a", "canoe", False, user="Alex", path=dbpath)
    assert db.checklist_load("trip-a", path=dbpath) == {"canoe": True}
    assert db.checklist_load("trip-a", user="Alex", path=dbpath) == {"canoe": False}


# ---------------------------------------------------------------------------
# Migration: v0 (Phase 2) → v1 (Phase 3)
# ---------------------------------------------------------------------------


def test_migration_promotes_v0_rows_to_shared(tmp_path):
    """A pre-Phase-3 DB still has its data, exposed under user=''."""
    p = tmp_path / "v0.sqlite3"
    with db.connect(p) as conn:
        conn.executescript("""
            CREATE TABLE checklist_state (
                trip_slug  TEXT NOT NULL,
                item_key   TEXT NOT NULL,
                checked    INTEGER NOT NULL CHECK (checked IN (0, 1)),
                updated_at REAL NOT NULL,
                PRIMARY KEY (trip_slug, item_key)
            );
            INSERT INTO checklist_state VALUES ('trip-a', 'tent',   1, 100.0);
            INSERT INTO checklist_state VALUES ('trip-a', 'paddle', 0, 100.0);
        """)
    db.init_schema(p)
    cols = set()
    with db.connect(p) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(checklist_state)")}
    assert "user" in cols
    assert db.checklist_load("trip-a", path=p) == {"tent": True, "paddle": False}
    # No leakage to a per-user query
    assert db.checklist_load("trip-a", user="Alex", path=p) == {}


def test_migration_idempotent(tmp_path):
    """Running init_schema twice on a v0 DB should not lose data or fail."""
    p = tmp_path / "v0.sqlite3"
    with db.connect(p) as conn:
        conn.executescript("""
            CREATE TABLE checklist_state (
                trip_slug  TEXT NOT NULL, item_key TEXT NOT NULL,
                checked INTEGER NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (trip_slug, item_key)
            );
            INSERT INTO checklist_state VALUES ('t', 'k', 1, 1.0);
        """)
    db.init_schema(p)
    db.init_schema(p)
    assert db.checklist_load("t", path=p) == {"k": True}
