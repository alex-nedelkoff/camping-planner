"""food_items CRUD with conflict detection."""

import pytest

from app.services import auth, db, food_repo


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "f.sqlite3"
    db.init_schema(p)
    auth.upsert_user("alex@example.com", path=p)
    return p


def test_insert_returns_row_with_id_and_timestamp(dbpath):
    row = food_repo.insert(
        trip_slug="killarney-2026-05",
        day_index=1, meal="dinner", item="Pasta",
        assigned_to="Alex", notes="extra", sort_order=1.0,
        user_id=1, path=dbpath,
    )
    assert row["id"]
    assert row["updated_at"]
    assert row["item"] == "Pasta"


def test_list_groups_by_day_meal_sort(dbpath):
    food_repo.insert(trip_slug="t", day_index=2, meal="lunch",
                     item="B", assigned_to="", notes="", sort_order=1.0,
                     user_id=1, path=dbpath)
    food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                     item="A", assigned_to="", notes="", sort_order=1.0,
                     user_id=1, path=dbpath)
    rows = food_repo.list_for_trip("t", path=dbpath)
    assert [r["item"] for r in rows] == ["A", "B"]


def test_update_with_correct_expected_updated_at_succeeds(dbpath):
    row = food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                           item="A", assigned_to="", notes="", sort_order=1.0,
                           user_id=1, path=dbpath)
    updated = food_repo.update(
        row["id"], expected_updated_at=row["updated_at"],
        item="A2", user_id=1, path=dbpath,
    )
    assert updated["item"] == "A2"
    assert updated["updated_at"] > row["updated_at"]


def test_update_with_stale_expected_raises_conflict(dbpath):
    row = food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                           item="A", assigned_to="", notes="", sort_order=1.0,
                           user_id=1, path=dbpath)
    food_repo.update(row["id"], expected_updated_at=row["updated_at"],
                     item="A2", user_id=1, path=dbpath)
    # second update with the original stale timestamp
    with pytest.raises(food_repo.Conflict) as exc:
        food_repo.update(row["id"], expected_updated_at=row["updated_at"],
                         item="A3", user_id=1, path=dbpath)
    assert exc.value.current["item"] == "A2"


def test_delete_removes_row(dbpath):
    row = food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                           item="A", assigned_to="", notes="", sort_order=1.0,
                           user_id=1, path=dbpath)
    food_repo.delete(row["id"], path=dbpath)
    assert food_repo.list_for_trip("t", path=dbpath) == []
