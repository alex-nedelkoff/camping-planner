"""Idempotent markdown → DB seed."""

import pytest

from app.services import auth, db, food_repo, gear_repo, seed


FOOD_MD = """\
# Food Plan

## Day 1 — Friday

| Meal | Item | Who | Notes |
|---|---|---|---|
| Breakfast | Pancakes + bacon | Alex | extra syrup |
| Breakfast | Coffee | shared | |
| Dinner | Pasta | Alex | |

## Day 2 — Saturday

| Meal | Item | Who | Notes |
|---|---|---|---|
| Lunch | Wraps | Thomas | |
"""

GEAR_MD = """\
# Gear

## shelter

| Item | Qty | Who | Notes |
|---|---|---|---|
| Tent (3p) | 1 | Alex | |
| Tarp | 1 | shared | |

## kitchen

| Item | Qty | Who | Notes |
|---|---|---|---|
| Stove | 1 | Thomas | |
"""


def test_seed_food_parses_two_days(tmp_path):
    dbp = tmp_path / "s.sqlite3"
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="owner", path=dbp)
    trip_dir = tmp_path / "trips" / "t"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(FOOD_MD)
    seed.seed_trip("t", trip_dir, owner_email="alex@example.com", path=dbp)
    rows = food_repo.list_for_trip("t", path=dbp)
    items = [(r["day_index"], r["meal"], r["item"]) for r in rows]
    assert (1, "breakfast", "Pancakes + bacon") in items
    assert (2, "lunch", "Wraps") in items


def test_seed_gear_parses_categories(tmp_path):
    dbp = tmp_path / "s.sqlite3"
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="owner", path=dbp)
    trip_dir = tmp_path / "trips" / "t"
    trip_dir.mkdir(parents=True)
    (trip_dir / "gear.md").write_text(GEAR_MD)
    seed.seed_trip("t", trip_dir, owner_email="alex@example.com", path=dbp)
    rows = gear_repo.list_for_trip("t", path=dbp)
    cats = {r["category"] for r in rows}
    assert {"shelter", "kitchen"} == cats


def test_seed_is_idempotent(tmp_path):
    dbp = tmp_path / "s.sqlite3"
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    trip_dir = tmp_path / "trips" / "t"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(FOOD_MD)
    seed.seed_trip("t", trip_dir, owner_email="alex@example.com", path=dbp)
    seed.seed_trip("t", trip_dir, owner_email="alex@example.com", path=dbp)
    rows = food_repo.list_for_trip("t", path=dbp)
    # Should not double-insert
    assert len(rows) == 4  # 3 from day 1, 1 from day 2
