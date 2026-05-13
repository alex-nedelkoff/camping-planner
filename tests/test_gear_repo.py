"""gear_items CRUD."""

import pytest

from app.services import auth, db, gear_repo


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "g.sqlite3"
    db.init_schema(p)
    auth.upsert_user("alex@example.com", path=p)
    return p


def test_insert_returns_row(dbpath):
    row = gear_repo.insert(
        trip_slug="t", category="shelter", item="Tent (3p)",
        quantity="1", assigned_to="Alex", notes="", sort_order=1.0,
        user_id=1, path=dbpath,
    )
    assert row["id"]
    assert row["item"] == "Tent (3p)"


def test_list_orders_by_category_then_sort(dbpath):
    gear_repo.insert(trip_slug="t", category="kitchen", item="Stove",
                     quantity="1", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    gear_repo.insert(trip_slug="t", category="shelter", item="Tent",
                     quantity="1", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    rows = gear_repo.list_for_trip("t", path=dbpath)
    assert [r["category"] for r in rows] == ["kitchen", "shelter"]


def test_update_conflict_detection(dbpath):
    row = gear_repo.insert(trip_slug="t", category="kitchen", item="Stove",
                           quantity="1", assigned_to="", notes="",
                           sort_order=1.0, user_id=1, path=dbpath)
    gear_repo.update(row["id"], expected_updated_at=row["updated_at"],
                     item="Big Stove", user_id=1, path=dbpath)
    with pytest.raises(gear_repo.Conflict):
        gear_repo.update(row["id"], expected_updated_at=row["updated_at"],
                         item="Other", user_id=1, path=dbpath)


def test_delete_removes(dbpath):
    row = gear_repo.insert(trip_slug="t", category="kitchen", item="Stove",
                           quantity="1", assigned_to="", notes="",
                           sort_order=1.0, user_id=1, path=dbpath)
    gear_repo.delete(row["id"], path=dbpath)
    assert gear_repo.list_for_trip("t", path=dbpath) == []
