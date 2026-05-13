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
