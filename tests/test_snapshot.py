"""DB rows → markdown is deterministic and byte-stable."""

import pytest

from app.services import auth, db, food_repo, gear_repo, snapshot


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "x.sqlite3"
    db.init_schema(p)
    auth.upsert_user("alex@example.com", path=p)
    return p


def test_render_food_md_grouped_by_day_then_meal(dbpath):
    food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                     item="Pasta", assigned_to="Alex", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    food_repo.insert(trip_slug="t", day_index=1, meal="breakfast",
                     item="Coffee", assigned_to="shared", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    food_repo.insert(trip_slug="t", day_index=2, meal="lunch",
                     item="Wraps", assigned_to="Thomas", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    md = snapshot.render_food_markdown("t", path=dbpath)
    assert "## Day 1" in md
    assert "## Day 2" in md
    assert md.index("## Day 1") < md.index("## Day 2")
    assert "Breakfast" in md and "Dinner" in md
    assert md.index("Breakfast") < md.index("Dinner")


def test_render_food_md_is_byte_stable_across_two_runs(dbpath):
    food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                     item="Pasta", assigned_to="Alex", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    a = snapshot.render_food_markdown("t", path=dbpath)
    b = snapshot.render_food_markdown("t", path=dbpath)
    assert a == b


def test_render_escapes_pipe_in_item_text(dbpath):
    food_repo.insert(trip_slug="t", day_index=1, meal="lunch",
                     item="Chips | salsa", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    md = snapshot.render_food_markdown("t", path=dbpath)
    assert "Chips \\| salsa" in md


def test_render_gear_md_grouped_by_category(dbpath):
    gear_repo.insert(trip_slug="t", category="shelter", item="Tent",
                     quantity="1", assigned_to="Alex", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    gear_repo.insert(trip_slug="t", category="kitchen", item="Stove",
                     quantity="1", assigned_to="Thomas", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    md = snapshot.render_gear_markdown("t", path=dbpath)
    assert "## kitchen" in md
    assert "## shelter" in md


def test_write_snapshot_creates_files_and_updates_state(tmp_path, monkeypatch):
    from app.services import auth, db, food_repo, snapshot
    dbp = tmp_path / "x.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    trip_dir = tmp_path / "trips" / "t"
    trip_dir.mkdir(parents=True)
    food_repo.insert(trip_slug="t", day_index=1, meal="lunch",
                     item="Wraps", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbp)
    paths = snapshot.write_snapshot("t", trip_dir, run_build_trip=False,
                                    path=dbp)
    assert (trip_dir / "food.md").read_text().startswith("# Food Plan")
    assert (trip_dir / "gear.md").exists()
    assert paths["food"].endswith("food.md")
    # last_snapshotted_at recorded
    with db.connect(dbp) as conn:
        row = conn.execute(
            "SELECT last_snapshotted_at FROM section_state "
            "WHERE trip_slug = ? AND section = 'food'", ("t",),
        ).fetchone()
    assert row and row["last_snapshotted_at"]


def test_snapshot_endpoint_writes_files(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import auth, db, food_repo

    dbp = tmp_path / "x.sqlite3"
    trips = tmp_path / "trips"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    monkeypatch.setattr("app.config.TRIPS_DIR", trips)
    monkeypatch.setattr("app.routes.trips.TRIPS_DIR", trips)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="owner", path=dbp)
    (trips / "t").mkdir(parents=True)
    food_repo.insert(trip_slug="t", day_index=1, meal="lunch",
                     item="Wraps", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbp)
    # mint session
    import secrets
    import time
    from datetime import datetime, timezone
    sid = secrets.token_urlsafe(32)
    with db.connect(dbp) as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, 1, ?, ?)",
            (sid, datetime.now(timezone.utc).isoformat(),
             datetime.fromtimestamp(time.time() + 3600,
                                    tz=timezone.utc).isoformat()),
        )
    client = TestClient(app, cookies={"cp_session": sid})
    r = client.post("/api/trips/t/snapshot",
                    json={"run_build_trip": False})
    assert r.status_code == 200
    assert (trips / "t" / "food.md").exists()
