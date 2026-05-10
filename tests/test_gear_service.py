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


def test_upsert_creates_with_slug_id(tmp_catalog):
    new_id = gear_svc.upsert({
        "name": "Snow Peak Trek 700",
        "category": "Cook",
        "weight_g": 145,
    })
    assert new_id == "snow-peak-trek-700"
    assert gear_svc.get("snow-peak-trek-700")["weight_g"] == 145


def test_upsert_collision_appends_suffix(tmp_catalog):
    gear_svc.upsert({"name": "Compass", "category": "Navigation", "weight_g": 25})
    assert gear_svc.get("compass-2") is not None


def test_upsert_updates_existing_when_id_provided(tmp_catalog):
    gear_svc.upsert({
        "id": "compass",
        "name": "Compass (renamed)",
        "category": "Navigation",
        "weight_g": 35,
    })
    assert gear_svc.get("compass")["weight_g"] == 35
    assert gear_svc.get("compass")["name"] == "Compass (renamed)"


def test_upsert_accepts_null_weight(tmp_catalog):
    new_id = gear_svc.upsert({
        "name": "Custom Tent",
        "category": "Other",
        "weight_g": None,
    })
    assert gear_svc.get(new_id)["weight_g"] is None


def test_upsert_validates_required_fields(tmp_catalog):
    with pytest.raises(ValueError, match="name"):
        gear_svc.upsert({"category": "Cook", "weight_g": 100})


def test_upsert_rejects_unknown_category(tmp_catalog):
    with pytest.raises(ValueError, match="category"):
        gear_svc.upsert({"name": "X", "category": "bogus", "weight_g": 1})


def test_upsert_rejects_negative_weight(tmp_catalog):
    with pytest.raises(ValueError, match="weight"):
        gear_svc.upsert({"name": "X", "category": "Cook", "weight_g": -1})


def test_delete_removes_item(tmp_catalog):
    gear_svc.delete("compass")
    assert gear_svc.get("compass") is None


def test_delete_unknown_id_raises(tmp_catalog):
    with pytest.raises(KeyError):
        gear_svc.delete("nope")


def test_find_references_returns_trip_slugs(tmp_catalog, tmp_path, monkeypatch):
    trips_dir = tmp_path / "trips"
    (trips_dir / "killarney-2026-07").mkdir(parents=True)
    (trips_dir / "killarney-2026-07" / "gear.md").write_text(
        "---\nitems:\n  - item_id: compass\n    qty: 1\n    who: shared\n---\n",
        encoding="utf-8",
    )
    (trips_dir / "killbear-2026-08").mkdir(parents=True)
    (trips_dir / "killbear-2026-08" / "gear.md").write_text(
        "no frontmatter here\n", encoding="utf-8",
    )
    monkeypatch.setattr(gear_svc, "TRIPS_DIR", trips_dir)
    refs = gear_svc.find_references("compass")
    assert refs == ["killarney-2026-07"]
    assert gear_svc.find_references("msr-pocket-rocket") == []


def test_find_references_does_not_prefix_match(tmp_catalog, tmp_path, monkeypatch):
    """`comp` must NOT match `compass` — regression from the foods feature."""
    trips_dir = tmp_path / "trips"
    (trips_dir / "trip-a").mkdir(parents=True)
    (trips_dir / "trip-a" / "gear.md").write_text(
        "---\nitems:\n  - item_id: compass\n    qty: 1\n---\n", encoding="utf-8",
    )
    monkeypatch.setattr(gear_svc, "TRIPS_DIR", trips_dir)
    assert gear_svc.find_references("comp") == []
    assert gear_svc.find_references("compass") == ["trip-a"]


def test_find_references_matches_quoted_form(tmp_catalog, tmp_path, monkeypatch):
    trips_dir = tmp_path / "trips"
    (trips_dir / "trip-q").mkdir(parents=True)
    (trips_dir / "trip-q" / "gear.md").write_text(
        "---\nitems:\n  - item_id: 'compass'\n    qty: 1\n---\n", encoding="utf-8",
    )
    monkeypatch.setattr(gear_svc, "TRIPS_DIR", trips_dir)
    assert gear_svc.find_references("compass") == ["trip-q"]


def test_add_category_appends(tmp_catalog):
    gear_svc.add_category("Photography")
    assert "Photography" in gear_svc.load_catalog()["categories"]


def test_add_category_rejects_duplicate_case_insensitive(tmp_catalog):
    with pytest.raises(ValueError, match="already exists"):
        gear_svc.add_category("cook")  # 'Cook' already exists


def test_add_category_rejects_blank(tmp_catalog):
    with pytest.raises(ValueError, match="empty"):
        gear_svc.add_category("   ")


def test_add_category_rejects_too_long(tmp_catalog):
    with pytest.raises(ValueError, match="too long"):
        gear_svc.add_category("x" * 41)


def test_rename_category_updates_items(tmp_catalog):
    gear_svc.rename_category("Cook", "Cooking")
    cat = gear_svc.load_catalog()
    assert "Cooking" in cat["categories"]
    assert "Cook" not in cat["categories"]
    assert gear_svc.get("msr-pocket-rocket")["category"] == "Cooking"


def test_rename_category_rejects_unknown(tmp_catalog):
    with pytest.raises(KeyError):
        gear_svc.rename_category("Bogus", "X")


def test_rename_category_rejects_collision(tmp_catalog):
    with pytest.raises(ValueError, match="already exists"):
        gear_svc.rename_category("Cook", "Navigation")


def test_rename_category_rejects_protected(tmp_catalog):
    with pytest.raises(ValueError, match="protected"):
        gear_svc.rename_category("Other", "Misc")


def test_delete_category_blocked_when_in_use(tmp_catalog):
    with pytest.raises(ValueError, match="in use"):
        gear_svc.delete_category("Cook", force=False)


def test_delete_category_unused_succeeds(tmp_catalog):
    gear_svc.add_category("Photography")
    gear_svc.delete_category("Photography", force=False)
    assert "Photography" not in gear_svc.load_catalog()["categories"]


def test_delete_category_force_reassigns_to_other(tmp_catalog):
    gear_svc.delete_category("Cook", force=True)
    assert "Cook" not in gear_svc.load_catalog()["categories"]
    assert gear_svc.get("msr-pocket-rocket")["category"] == "Other"


def test_delete_category_protected_other(tmp_catalog):
    with pytest.raises(ValueError, match="protected"):
        gear_svc.delete_category("Other", force=True)


def test_delete_category_unknown_raises(tmp_catalog):
    with pytest.raises(KeyError):
        gear_svc.delete_category("Bogus", force=False)
