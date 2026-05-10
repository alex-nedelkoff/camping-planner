"""Tests for the foods catalog service."""

import json

import pytest

from app.services import foods as foods_svc


@pytest.fixture
def tmp_catalog(tmp_path, monkeypatch):
    path = tmp_path / "foods.json"
    path.write_text(json.dumps({
        "version": 1,
        "categories": ["meal", "snack"],
        "foods": [
            {"id": "tuna-pouch", "name": "Tuna pouch", "category": "snack",
             "kcal_per_serving": 110, "serving_size": "1 pouch", "url": None},
            {"id": "instant-mash", "name": "Instant mashed potatoes", "category": "meal",
             "kcal_per_serving": 160, "serving_size": "1/2 cup dry", "url": None},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(foods_svc, "FOODS_JSON", path)
    foods_svc._invalidate_cache()
    yield path


def test_load_catalog_returns_full_structure(tmp_catalog):
    cat = foods_svc.load_catalog()
    assert cat["version"] == 1
    assert "snack" in cat["categories"]
    assert len(cat["foods"]) == 2


def test_get_returns_food_by_id(tmp_catalog):
    food = foods_svc.get("tuna-pouch")
    assert food["name"] == "Tuna pouch"


def test_get_returns_none_when_missing(tmp_catalog):
    assert foods_svc.get("nope") is None


def test_search_filters_by_name_substring(tmp_catalog):
    results = foods_svc.search("mash", category=None)
    assert len(results) == 1
    assert results[0]["id"] == "instant-mash"


def test_search_filters_by_category(tmp_catalog):
    results = foods_svc.search("", category="snack")
    assert len(results) == 1
    assert results[0]["id"] == "tuna-pouch"


def test_search_combines_query_and_category(tmp_catalog):
    results = foods_svc.search("tuna", category="meal")
    assert results == []


def test_load_catalog_rejects_unknown_version(tmp_catalog, tmp_path):
    bad = tmp_path / "foods.json"
    bad.write_text(json.dumps({"version": 99, "categories": [], "foods": []}), encoding="utf-8")
    foods_svc._invalidate_cache()
    with pytest.raises(RuntimeError, match="unknown.*version"):
        foods_svc.load_catalog()


def test_load_catalog_caches_and_invalidates_on_mtime(tmp_catalog):
    first = foods_svc.load_catalog()
    second = foods_svc.load_catalog()
    assert first is second  # same in-memory object
    # Mutate file → mtime changes → next call reloads
    import time as t
    t.sleep(0.01)
    tmp_catalog.write_text(json.dumps({
        "version": 1, "categories": ["snack"],
        "foods": [{"id": "x", "name": "X", "category": "snack",
                   "kcal_per_serving": 1, "serving_size": "1", "url": None}],
    }), encoding="utf-8")
    third = foods_svc.load_catalog()
    assert third is not first
    assert len(third["foods"]) == 1


def test_upsert_creates_with_slug_id(tmp_catalog):
    new_id = foods_svc.upsert({
        "name": "Snickers Bar",
        "category": "snack",
        "kcal_per_serving": 250,
        "serving_size": "1 bar",
        "url": None,
    })
    assert new_id == "snickers-bar"
    assert foods_svc.get("snickers-bar")["name"] == "Snickers Bar"


def test_upsert_collision_appends_suffix(tmp_catalog):
    foods_svc.upsert({"name": "Tuna pouch", "category": "snack",
                      "kcal_per_serving": 100, "serving_size": "1", "url": None})
    # Catalog already has tuna-pouch, so the new one becomes tuna-pouch-2
    assert foods_svc.get("tuna-pouch-2") is not None


def test_upsert_updates_existing_when_id_provided(tmp_catalog):
    foods_svc.upsert({
        "id": "tuna-pouch",
        "name": "Tuna pouch (renamed)",
        "category": "snack",
        "kcal_per_serving": 115,
        "serving_size": "1 pouch",
        "url": None,
    })
    assert foods_svc.get("tuna-pouch")["kcal_per_serving"] == 115
    assert foods_svc.get("tuna-pouch")["name"] == "Tuna pouch (renamed)"


def test_upsert_validates_required_fields(tmp_catalog):
    with pytest.raises(ValueError, match="name"):
        foods_svc.upsert({"category": "snack", "kcal_per_serving": 1,
                          "serving_size": "1", "url": None})


def test_upsert_rejects_unknown_category(tmp_catalog):
    with pytest.raises(ValueError, match="category"):
        foods_svc.upsert({"name": "X", "category": "bogus",
                          "kcal_per_serving": 1, "serving_size": "1", "url": None})


def test_upsert_rejects_negative_kcal(tmp_catalog):
    with pytest.raises(ValueError, match="kcal"):
        foods_svc.upsert({"name": "X", "category": "snack",
                          "kcal_per_serving": -1, "serving_size": "1", "url": None})


def test_delete_removes_food(tmp_catalog):
    foods_svc.delete("tuna-pouch")
    assert foods_svc.get("tuna-pouch") is None


def test_delete_unknown_id_raises(tmp_catalog):
    with pytest.raises(KeyError):
        foods_svc.delete("nope")


def test_find_references_returns_trip_slugs(tmp_catalog, tmp_path, monkeypatch):
    trips_dir = tmp_path / "trips"
    (trips_dir / "killarney-2026-07").mkdir(parents=True)
    (trips_dir / "killarney-2026-07" / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: tuna-pouch\n"
        "            servings: 2\n---\n", encoding="utf-8",
    )
    (trips_dir / "killbear-2026-08").mkdir(parents=True)
    (trips_dir / "killbear-2026-08" / "food.md").write_text("no frontmatter\n", encoding="utf-8")
    monkeypatch.setattr(foods_svc, "TRIPS_DIR", trips_dir)
    refs = foods_svc.find_references("tuna-pouch")
    assert refs == ["killarney-2026-07"]
    assert foods_svc.find_references("instant-mash") == []


def test_find_references_does_not_prefix_match(tmp_catalog, tmp_path, monkeypatch):
    """`tuna` must NOT match `tuna-pouch` — a previous bug."""
    trips_dir = tmp_path / "trips"
    (trips_dir / "trip-a").mkdir(parents=True)
    (trips_dir / "trip-a" / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: tuna-pouch\n"
        "            servings: 2\n---\n", encoding="utf-8",
    )
    monkeypatch.setattr(foods_svc, "TRIPS_DIR", trips_dir)
    # `tuna` is a prefix of `tuna-pouch` but is not the same id
    assert foods_svc.find_references("tuna") == []
    # Confirm the full id still matches
    assert foods_svc.find_references("tuna-pouch") == ["trip-a"]


def test_find_references_matches_quoted_form(tmp_catalog, tmp_path, monkeypatch):
    """Frontmatter with quoted food_id values should still match."""
    trips_dir = tmp_path / "trips"
    (trips_dir / "trip-q").mkdir(parents=True)
    (trips_dir / "trip-q" / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: 'tuna-pouch'\n"
        "            servings: 1\n---\n", encoding="utf-8",
    )
    monkeypatch.setattr(foods_svc, "TRIPS_DIR", trips_dir)
    assert foods_svc.find_references("tuna-pouch") == ["trip-q"]
