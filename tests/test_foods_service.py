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
    foods_svc._reset_cache_for_tests()
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
    foods_svc._reset_cache_for_tests()
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
