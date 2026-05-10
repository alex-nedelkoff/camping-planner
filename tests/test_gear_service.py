"""Tests for the gear catalog service."""

import json

import pytest

from app.services import gear as gear_svc


@pytest.fixture
def tmp_catalog(tmp_path, monkeypatch):
    path = tmp_path / "gear.json"
    path.write_text(json.dumps({
        "version": 1,
        "categories": ["Navigation", "Cook", "Other"],
        "items": [
            {"id": "compass", "name": "Compass", "category": "Navigation", "weight_g": 30},
            {"id": "msr-pocket-rocket", "name": "MSR Pocket Rocket stove",
             "category": "Cook", "weight_g": 73},
            {"id": "tent-3-person", "name": "Tent (3-person)", "category": "Other",
             "weight_g": None},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(gear_svc, "GEAR_JSON", path)
    gear_svc._invalidate_cache()
    yield path


def test_load_catalog_returns_full_structure(tmp_catalog):
    cat = gear_svc.load_catalog()
    assert cat["version"] == 1
    assert "Cook" in cat["categories"]
    assert len(cat["items"]) == 3


def test_get_returns_item_by_id(tmp_catalog):
    item = gear_svc.get("compass")
    assert item["name"] == "Compass"
    assert item["weight_g"] == 30


def test_get_returns_none_when_missing(tmp_catalog):
    assert gear_svc.get("nope") is None


def test_get_handles_null_weight(tmp_catalog):
    item = gear_svc.get("tent-3-person")
    assert item["weight_g"] is None


def test_search_filters_by_name_substring(tmp_catalog):
    results = gear_svc.search("rocket", category=None)
    assert len(results) == 1
    assert results[0]["id"] == "msr-pocket-rocket"


def test_search_is_case_insensitive(tmp_catalog):
    results = gear_svc.search("ROCKET", category=None)
    assert len(results) == 1


def test_search_filters_by_category(tmp_catalog):
    results = gear_svc.search("", category="Cook")
    assert len(results) == 1
    assert results[0]["id"] == "msr-pocket-rocket"


def test_search_combines_query_and_category(tmp_catalog):
    results = gear_svc.search("rocket", category="Other")
    assert results == []


def test_load_catalog_rejects_unknown_version(tmp_catalog, tmp_path):
    bad = tmp_path / "gear.json"
    bad.write_text(json.dumps({"version": 99, "categories": [], "items": []}),
                   encoding="utf-8")
    gear_svc._invalidate_cache()
    with pytest.raises(RuntimeError, match="unknown.*version"):
        gear_svc.load_catalog()


def test_load_catalog_caches_and_invalidates_on_mtime(tmp_catalog):
    first = gear_svc.load_catalog()
    second = gear_svc.load_catalog()
    assert first is second
    import time as t
    t.sleep(0.01)
    tmp_catalog.write_text(json.dumps({
        "version": 1, "categories": ["X"],
        "items": [{"id": "x", "name": "X", "category": "X", "weight_g": 1}],
    }), encoding="utf-8")
    third = gear_svc.load_catalog()
    assert third is not first
    assert len(third["items"]) == 1
