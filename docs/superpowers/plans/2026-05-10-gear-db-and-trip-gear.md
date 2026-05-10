# Gear DB & Trip-Page Gear Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a git-tracked gear catalog (`gear.json`) with user-managed categories, a per-trip structured gear plan stored as YAML frontmatter in `gear.md`, a `/gear` master-detail UI, and a trip-page gear table with autocomplete + weight totals + per-person breakdown.

**Architecture:** Mirrors the food-DB feature shipped in the previous cycle. Catalog is a single git-tracked JSON file loaded once and cached in-memory with mtime invalidation. Per-trip gear plans live as YAML frontmatter in `trips/<slug>/gear.md`; the markdown body is regenerated on every save. SQLite remains operational-only. The `/gear` SPA page communicates with FastAPI JSON routes, and the trip pane dispatches the gear section to a new `gear-plan.js` component (parallel to `meal-plan.js`).

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, PyYAML, Jinja2, vanilla JS (no framework — matches existing SPA), pytest.

**Reference spec:** `docs/superpowers/specs/2026-05-10-gear-db-and-trip-gear-design.md`

**Branch convention:** Per project memory, this work runs in a worktree forked off `dev` and merges back to `dev` (not `main`).

---

## File structure

**Created:**
- `gear.json` — repo root, git-tracked catalog seed
- `app/services/gear.py` — load/search/upsert/delete + categories CRUD; in-memory cache
- `app/services/gear_plan.py` — frontmatter I/O, compute totals, render md body
- `app/routes/gear.py` — `/api/gear` CRUD + `/api/gear/categories` + `/api/trip/{slug}/gear-plan`
- `app/static/css/gear.css` — `/gear` page styles
- `app/static/js/gear.js` — `/gear` master-detail UI (incl. Manage Categories modal)
- `app/static/js/gear-plan.js` — trip-page gear section
- `tests/test_gear_service.py`
- `tests/test_gear_plan_service.py`
- `tests/test_gear_routes.py`
- `tests/test_gear_plan_routes.py`

**Modified:**
- `app/main.py` — register `gear` router(s)
- `app/routes/pages.py` — add `/gear` route
- `app/templates/index.html` — sidebar "Gear DB" link, asset includes, `<template id="tpl-gear">`
- `app/services/trips.py` — `load_trip_payload` marks gear section with `kind: "gear-plan"`; remove `"gear"` from `EDITABLE_SECTIONS`; `editable: False` on the gear section payload
- `app/models.py` — Pydantic schemas for gear + gear-plan
- `app/static/js/trip.js` — dispatch `kind: "gear-plan"` to `window.GearPlan.init`
- `app/static/css/trip.css` — gear-plan section styles
- `templates/trip-template/gear.md` — empty-frontmatter template
- `CLAUDE.md` — document the new feature

---

## Task 1: Seed `gear.json`

**Files:**
- Create: `gear.json`

- [ ] **Step 1: Create the seed catalog**

Create `gear.json` at the repo root:

```json
{
  "version": 1,
  "categories": ["Navigation", "Shelter", "Sleep", "Cook", "Water", "Food storage", "Safety", "Lighting", "Tools", "Paddling", "Clothing", "Other"],
  "items": [
    {"id": "canoe-rental", "name": "Canoe (rental)", "category": "Paddling", "weight_g": 24500},
    {"id": "paddle", "name": "Paddle", "category": "Paddling", "weight_g": 800},
    {"id": "pfd", "name": "PFD", "category": "Paddling", "weight_g": 700},
    {"id": "map-waterproof", "name": "Map (waterproof)", "category": "Navigation", "weight_g": 60},
    {"id": "compass", "name": "Compass", "category": "Navigation", "weight_g": 30},
    {"id": "tent-3-person", "name": "Tent (3-person)", "category": "Shelter", "weight_g": null},
    {"id": "tarp-10x10", "name": "Tarp 10x10 + ridgeline", "category": "Shelter", "weight_g": 900},
    {"id": "sleeping-bag", "name": "Sleeping bag", "category": "Sleep", "weight_g": null},
    {"id": "sleeping-pad", "name": "Sleeping pad", "category": "Sleep", "weight_g": null},
    {"id": "msr-pocket-rocket", "name": "MSR Pocket Rocket stove", "category": "Cook", "weight_g": 73},
    {"id": "cookpot-with-lid", "name": "Cookpot + lid", "category": "Cook", "weight_g": 350},
    {"id": "spork", "name": "Spork", "category": "Cook", "weight_g": 15},
    {"id": "water-filter", "name": "Water filter", "category": "Water", "weight_g": 320},
    {"id": "nalgene-1l", "name": "Nalgene 1 L", "category": "Water", "weight_g": 180},
    {"id": "bear-barrel", "name": "Bear barrel", "category": "Food storage", "weight_g": 1500},
    {"id": "first-aid-kit", "name": "First aid kit", "category": "Safety", "weight_g": 400},
    {"id": "headlamp", "name": "Headlamp", "category": "Lighting", "weight_g": 90},
    {"id": "multitool", "name": "Multitool", "category": "Tools", "weight_g": 200},
    {"id": "lighter", "name": "Lighter", "category": "Tools", "weight_g": 20},
    {"id": "dry-bag", "name": "Dry bag", "category": "Other", "weight_g": 120}
  ]
}
```

End the file with a single trailing newline (matches `parks.json` / `foods.json` convention).

- [ ] **Step 2: Verify it's valid JSON**

Run:
```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -c "import json; data=json.load(open('gear.json')); print(len(data['items']),'items,',len(data['categories']),'categories')"
```

Expected: `20 items, 12 categories`

- [ ] **Step 3: Commit**

```bash
git add gear.json
git commit -m "feat(gear): seed gear.json catalog"
```

---

## Task 2: `gear` service — load / search / get (read-only)

**Files:**
- Create: `app/services/gear.py`
- Create: `tests/test_gear_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_gear_service.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_service.py -v
```

Expected: ImportError / ModuleNotFoundError for `app.services.gear`.

- [ ] **Step 3: Implement read-only service**

Create `app/services/gear.py`:

```python
"""Gear catalog service.

The catalog is a single git-tracked JSON file at the repo root. Loaded once
and cached in-memory; reload on mtime change. Mutations rewrite the file
atomically (see Tasks 3 and 4).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import REPO_ROOT

GEAR_JSON: Path = REPO_ROOT / "gear.json"
_KNOWN_VERSIONS = {1}

_cache: dict | None = None
_cache_mtime: float | None = None


def _invalidate_cache() -> None:
    """Clear the in-memory cache. Called after mutations and from test fixtures."""
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None


def load_catalog() -> dict:
    """Return the full catalog. Cached; reloaded if gear.json mtime changes."""
    global _cache, _cache_mtime
    mtime = GEAR_JSON.stat().st_mtime
    if _cache is not None and _cache_mtime == mtime:
        return _cache
    raw = json.loads(GEAR_JSON.read_text(encoding="utf-8"))
    version = raw.get("version")
    if version not in _KNOWN_VERSIONS:
        raise RuntimeError(
            f"gear.json has unknown schema version {version!r}; "
            f"known: {sorted(_KNOWN_VERSIONS)}"
        )
    _cache = raw
    _cache_mtime = mtime
    return _cache


def get(item_id: str) -> dict | None:
    """Return one item by id, or None."""
    for it in load_catalog()["items"]:
        if it["id"] == item_id:
            return it
    return None


def search(query: str, category: str | None) -> list[dict]:
    """Filter the catalog by case-insensitive name substring + optional category."""
    q = (query or "").strip().lower()
    items = load_catalog()["items"]
    if category:
        items = [i for i in items if i["category"] == category]
    if q:
        items = [i for i in items if q in i["name"].lower()]
    return list(items)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_service.py -v
```

Expected: 10/10 pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/gear.py tests/test_gear_service.py
git commit -m "feat(gear): catalog service load/get/search with mtime cache"
```

---

## Task 3: `gear` service — upsert / delete / find_references

**Files:**
- Modify: `app/services/gear.py`
- Modify: `tests/test_gear_service.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_gear_service.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_service.py -v
```

Expected: AttributeError on `gear_svc.upsert`, `gear_svc.delete`, `gear_svc.find_references`.

- [ ] **Step 3: Implement mutations**

Append to imports in `app/services/gear.py`:

```python
import os
import re
import tempfile

from app.config import TRIPS_DIR
```

Then append to the bottom of `app/services/gear.py`:

```python
_REQUIRED_FIELDS = ("name", "category")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return s or "item"


def _next_unique_slug(base: str, existing_ids: set[str]) -> str:
    if base not in existing_ids:
        return base
    n = 2
    while f"{base}-{n}" in existing_ids:
        n += 1
    return f"{base}-{n}"


def _validate(item: dict, categories: list[str]) -> None:
    for field in _REQUIRED_FIELDS:
        if field not in item or item[field] in (None, ""):
            raise ValueError(f"gear: missing required field '{field}'")
    if not isinstance(item["name"], str) or not item["name"].strip():
        raise ValueError("gear: name must be a non-empty string")
    if item["category"] not in categories:
        raise ValueError(
            f"gear: category {item['category']!r} not in {categories!r}"
        )
    weight = item.get("weight_g")
    if weight is not None:
        if not isinstance(weight, int) or weight < 0:
            raise ValueError("gear: weight_g must be a non-negative integer or null")


def _atomic_write(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix="gear-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def upsert(item: dict) -> str:
    """Create or update a gear item. Returns the id."""
    cat = load_catalog()
    categories = cat["categories"]
    items_list = cat["items"]
    item_id = (item.get("id") or "").strip()
    cleaned = {
        "name": item["name"].strip() if isinstance(item.get("name"), str) else None,
        "category": item.get("category"),
        "weight_g": item.get("weight_g") if item.get("weight_g") is not None else None,
    }
    _validate(cleaned, categories)
    existing_ids = {i["id"] for i in items_list}
    if item_id:
        for i, existing in enumerate(items_list):
            if existing["id"] == item_id:
                items_list[i] = {"id": item_id, **cleaned}
                break
        else:
            raise KeyError(f"gear: no item with id {item_id!r}")
    else:
        item_id = _next_unique_slug(_slugify(cleaned["name"]), existing_ids)
        items_list.append({"id": item_id, **cleaned})
    _atomic_write(GEAR_JSON, cat)
    _invalidate_cache()
    return item_id


def delete(item_id: str) -> None:
    cat = load_catalog()
    items_list = cat["items"]
    for i, it in enumerate(items_list):
        if it["id"] == item_id:
            del items_list[i]
            _atomic_write(GEAR_JSON, cat)
            _invalidate_cache()
            return
    raise KeyError(f"gear: no item with id {item_id!r}")


def find_references(item_id: str) -> list[str]:
    """Scan trips/*/gear.md frontmatter for occurrences of item_id."""
    if not TRIPS_DIR.exists():
        return []
    pattern = re.compile(
        r"item_id:\s*['\"]?" + re.escape(item_id) + r"['\"]?(?=[\s,\n]|$)"
    )
    refs: list[str] = []
    for trip_dir in sorted(TRIPS_DIR.iterdir()):
        if not trip_dir.is_dir():
            continue
        gear_md = trip_dir / "gear.md"
        if not gear_md.exists():
            continue
        text = gear_md.read_text(encoding="utf-8")
        if not text.lstrip().startswith("---"):
            continue
        if pattern.search(text):
            refs.append(trip_dir.name)
    return refs
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_service.py -v
```

Expected: 22/22 pass (10 + 12 new).

- [ ] **Step 5: Commit**

```bash
git add app/services/gear.py tests/test_gear_service.py
git commit -m "feat(gear): catalog mutations + reference scan"
```

---

## Task 4: `gear` service — category CRUD

**Files:**
- Modify: `app/services/gear.py`
- Modify: `tests/test_gear_service.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_gear_service.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_service.py -v -k category
```

Expected: AttributeErrors on `add_category`, `rename_category`, `delete_category`.

- [ ] **Step 3: Implement category CRUD**

Append to `app/services/gear.py`:

```python
PROTECTED_CATEGORIES = frozenset({"Other"})
_CATEGORY_MAX_LEN = 40


def _categories_lower_set(categories: list[str]) -> set[str]:
    return {c.lower() for c in categories}


def add_category(name: str) -> None:
    name = (name or "").strip()
    if not name:
        raise ValueError("gear: category name is empty")
    if len(name) > _CATEGORY_MAX_LEN:
        raise ValueError(f"gear: category name too long (max {_CATEGORY_MAX_LEN})")
    cat = load_catalog()
    if name.lower() in _categories_lower_set(cat["categories"]):
        raise ValueError(f"gear: category {name!r} already exists")
    cat["categories"].append(name)
    _atomic_write(GEAR_JSON, cat)
    _invalidate_cache()


def rename_category(old: str, new: str) -> None:
    old = (old or "").strip()
    new = (new or "").strip()
    if not new:
        raise ValueError("gear: new category name is empty")
    if len(new) > _CATEGORY_MAX_LEN:
        raise ValueError(f"gear: category name too long (max {_CATEGORY_MAX_LEN})")
    if old in PROTECTED_CATEGORIES:
        raise ValueError(f"gear: category {old!r} is protected and cannot be renamed")
    cat = load_catalog()
    if old not in cat["categories"]:
        raise KeyError(f"gear: no category {old!r}")
    if new.lower() != old.lower() and new.lower() in _categories_lower_set(cat["categories"]):
        raise ValueError(f"gear: category {new!r} already exists")
    cat["categories"] = [new if c == old else c for c in cat["categories"]]
    for it in cat["items"]:
        if it["category"] == old:
            it["category"] = new
    _atomic_write(GEAR_JSON, cat)
    _invalidate_cache()


def delete_category(name: str, force: bool = False) -> None:
    name = (name or "").strip()
    if name in PROTECTED_CATEGORIES:
        raise ValueError(f"gear: category {name!r} is protected and cannot be deleted")
    cat = load_catalog()
    if name not in cat["categories"]:
        raise KeyError(f"gear: no category {name!r}")
    in_use = [it for it in cat["items"] if it["category"] == name]
    if in_use and not force:
        raise ValueError(
            f"gear: category {name!r} is in use by {len(in_use)} item(s)"
        )
    if in_use and force:
        for it in in_use:
            it["category"] = "Other"
    cat["categories"] = [c for c in cat["categories"] if c != name]
    _atomic_write(GEAR_JSON, cat)
    _invalidate_cache()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_service.py -v
```

Expected: 35/35 pass (22 + 13 new).

- [ ] **Step 5: Commit**

```bash
git add app/services/gear.py tests/test_gear_service.py
git commit -m "feat(gear): category add/rename/delete with reassign-to-Other"
```

---

## Task 5: Pydantic schemas + `/api/gear` item routes

**Files:**
- Modify: `app/models.py`
- Create: `app/routes/gear.py`
- Modify: `app/main.py`
- Create: `tests/test_gear_routes.py`

- [ ] **Step 1: Add Pydantic schemas**

Append to `app/models.py`:

```python
class GearItemIn(BaseModel):
    name: str = Field(min_length=1)
    category: str
    weight_g: int | None = Field(default=None, ge=0)


class GearItemOut(GearItemIn):
    id: str


class GearCatalogResponse(BaseModel):
    ok: bool = True
    categories: list[str]
    items: list[GearItemOut]


class GearItemCreatedResponse(BaseModel):
    ok: bool = True
    id: str


class GearReferencesResponse(BaseModel):
    ok: bool = True
    references: list[str]


class CategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class CategoryRenameRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=40)
```

- [ ] **Step 2: Write failing route tests**

Create `tests/test_gear_routes.py`:

```python
"""FastAPI tests for /api/gear CRUD + categories."""

import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import gear as gear_svc


@pytest.fixture
def client(tmp_path, monkeypatch):
    catalog_path = tmp_path / "gear.json"
    catalog_path.write_text(json.dumps({
        "version": 1,
        "categories": ["Navigation", "Cook", "Other"],
        "items": [
            {"id": "compass", "name": "Compass",
             "category": "Navigation", "weight_g": 30},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(gear_svc, "GEAR_JSON", catalog_path)
    gear_svc._invalidate_cache()

    trips_dir = tmp_path / "trips"
    trips_dir.mkdir()
    monkeypatch.setattr(gear_svc, "TRIPS_DIR", trips_dir)
    monkeypatch.setattr(config, "TRIPS_DIR", trips_dir)

    yield TestClient(app)


def test_get_gear_returns_catalog(client):
    r = client.get("/api/gear")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["categories"] == ["Navigation", "Cook", "Other"]
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == "compass"


def test_post_gear_creates_item(client):
    r = client.post("/api/gear", json={
        "name": "Headlamp", "category": "Other", "weight_g": 90,
    })
    assert r.status_code == 200
    assert r.json()["id"] == "headlamp"


def test_post_gear_accepts_null_weight(client):
    r = client.post("/api/gear", json={
        "name": "Custom Tent", "category": "Other", "weight_g": None,
    })
    assert r.status_code == 200


def test_post_gear_validation_error_returns_400(client):
    r = client.post("/api/gear", json={
        "name": "Bad", "category": "bogus", "weight_g": 0,
    })
    assert r.status_code == 400
    assert "category" in r.json()["detail"]["error"]


def test_put_gear_updates_existing(client):
    r = client.put("/api/gear/compass", json={
        "name": "Compass", "category": "Navigation", "weight_g": 35,
    })
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert cat["items"][0]["weight_g"] == 35


def test_put_gear_unknown_id_returns_404(client):
    r = client.put("/api/gear/nope", json={
        "name": "X", "category": "Other", "weight_g": 1,
    })
    assert r.status_code == 404


def test_delete_gear_blocks_when_referenced(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "gear.md").write_text(
        "---\nitems:\n  - item_id: compass\n    qty: 1\n---\n", encoding="utf-8",
    )
    r = client.delete("/api/gear/compass")
    assert r.status_code == 409
    assert "killarney-2026-07" in r.json()["detail"]["references"]


def test_delete_gear_force_proceeds(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "gear.md").write_text(
        "---\nitems:\n  - item_id: compass\n    qty: 1\n---\n", encoding="utf-8",
    )
    r = client.delete("/api/gear/compass?force=true")
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert cat["items"] == []


def test_get_gear_refs(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "gear.md").write_text(
        "---\nitems:\n  - item_id: compass\n    qty: 1\n---\n", encoding="utf-8",
    )
    r = client.get("/api/gear/refs/compass")
    assert r.status_code == 200
    assert r.json()["references"] == ["killarney-2026-07"]
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_routes.py -v
```

Expected: 404s — no route exists.

- [ ] **Step 4: Implement routes**

Create `app/routes/gear.py`:

```python
"""Gear catalog HTTP routes."""

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    GearCatalogResponse,
    GearItemCreatedResponse,
    GearItemIn,
    GearReferencesResponse,
    OkResponse,
)
from app.services import gear as gear_svc

router = APIRouter(prefix="/api/gear")


@router.get("", response_model=GearCatalogResponse)
def get_catalog():
    cat = gear_svc.load_catalog()
    return GearCatalogResponse(categories=cat["categories"], items=cat["items"])


@router.post("", response_model=GearItemCreatedResponse)
def create_item(item: GearItemIn):
    try:
        new_id = gear_svc.upsert(item.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return GearItemCreatedResponse(id=new_id)


# More-specific paths first so they don't get shadowed by /{item_id}.
@router.get("/refs/{item_id}", response_model=GearReferencesResponse)
def item_references(item_id: str):
    return GearReferencesResponse(references=gear_svc.find_references(item_id))


@router.put("/{item_id}", response_model=OkResponse)
def update_item(item_id: str, item: GearItemIn):
    try:
        gear_svc.upsert({"id": item_id, **item.model_dump()})
    except KeyError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "item not found"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@router.delete("/{item_id}", response_model=OkResponse)
def delete_item(item_id: str, force: bool = Query(default=False)):
    if gear_svc.get(item_id) is None:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "item not found"})
    if not force:
        refs = gear_svc.find_references(item_id)
        if refs:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": "item is referenced", "references": refs},
            )
    gear_svc.delete(item_id)
    return OkResponse()
```

- [ ] **Step 5: Register the router**

Modify `app/main.py` — add `gear` to imports:

```python
from app.routes import checklist, foods, gear, identity, pages, parks, trips
```

Add the include (keep alphabetical with the existing `app.include_router(...)` lines):

```python
app.include_router(gear.router)
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_routes.py -v
```

Expected: 9/9 pass.

- [ ] **Step 7: Commit**

```bash
git add app/models.py app/routes/gear.py app/main.py tests/test_gear_routes.py
git commit -m "feat(gear): /api/gear item CRUD routes + Pydantic schemas"
```

---

## Task 6: `/api/gear/categories` routes

**Files:**
- Modify: `app/routes/gear.py`
- Modify: `tests/test_gear_routes.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_gear_routes.py`:

```python
def test_post_category_adds(client):
    r = client.post("/api/gear/categories", json={"name": "Photography"})
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert "Photography" in cat["categories"]


def test_post_category_duplicate_returns_400(client):
    r = client.post("/api/gear/categories", json={"name": "cook"})
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]["error"]


def test_put_category_renames_and_updates_items(client):
    r = client.put("/api/gear/categories/Cook", json={"new_name": "Cooking"})
    # Cook isn't used by any item in our fixture, but Navigation is via compass.
    # Use Navigation instead:
    pass


def test_put_category_renames_navigation_to_orient(client):
    r = client.put("/api/gear/categories/Navigation", json={"new_name": "Orient"})
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert "Orient" in cat["categories"]
    assert "Navigation" not in cat["categories"]
    assert cat["items"][0]["category"] == "Orient"


def test_put_category_unknown_returns_404(client):
    r = client.put("/api/gear/categories/Bogus", json={"new_name": "X"})
    assert r.status_code == 404


def test_put_category_protected_other_returns_400(client):
    r = client.put("/api/gear/categories/Other", json={"new_name": "Misc"})
    assert r.status_code == 400


def test_put_category_collision_returns_400(client):
    r = client.put("/api/gear/categories/Cook", json={"new_name": "Other"})
    assert r.status_code == 400


def test_delete_category_blocked_when_in_use(client):
    r = client.delete("/api/gear/categories/Navigation")
    assert r.status_code == 409


def test_delete_category_force_reassigns_to_other(client):
    r = client.delete("/api/gear/categories/Navigation?force=true")
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert "Navigation" not in cat["categories"]
    assert cat["items"][0]["category"] == "Other"


def test_delete_category_unused_succeeds(client):
    # Cook has no items in fixture
    r = client.delete("/api/gear/categories/Cook")
    assert r.status_code == 200


def test_delete_category_protected_other_returns_400(client):
    r = client.delete("/api/gear/categories/Other?force=true")
    assert r.status_code == 400
```

Also remove the `pass` placeholder in `test_put_category_renames_and_updates_items` — replace its body with:

```python
def test_put_category_renames_and_updates_items(client):
    """Add a category, then rename it (no items use it) — happy path."""
    client.post("/api/gear/categories", json={"name": "Tmp"})
    r = client.put("/api/gear/categories/Tmp", json={"new_name": "Tmp2"})
    assert r.status_code == 200
    cat = client.get("/api/gear").json()
    assert "Tmp2" in cat["categories"]
    assert "Tmp" not in cat["categories"]
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_routes.py -v -k category
```

Expected: 404s — no category routes exist yet.

- [ ] **Step 3: Add category routes**

Append to `app/routes/gear.py`:

```python
from app.models import CategoryRenameRequest, CategoryRequest

categories_router = APIRouter(prefix="/api/gear/categories")


@categories_router.post("", response_model=OkResponse)
def add_category(body: CategoryRequest):
    try:
        gear_svc.add_category(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@categories_router.put("/{old_name}", response_model=OkResponse)
def rename_category(old_name: str, body: CategoryRenameRequest):
    try:
        gear_svc.rename_category(old_name, body.new_name)
    except KeyError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "category not found"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@categories_router.delete("/{name}", response_model=OkResponse)
def delete_category(name: str, force: bool = Query(default=False)):
    try:
        gear_svc.delete_category(name, force=force)
    except KeyError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "category not found"})
    except ValueError as exc:
        # Distinguish "in use" (409) from validation errors (400).
        if "in use" in str(exc):
            raise HTTPException(
                status_code=409, detail={"ok": False, "error": str(exc)},
            )
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()
```

- [ ] **Step 4: Register the categories router**

Modify `app/main.py` — append after `app.include_router(gear.router)`:

```python
app.include_router(gear.categories_router)
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_routes.py -v
```

Expected: all pass (the 9 from Task 5 + 11 new).

- [ ] **Step 6: Commit**

```bash
git add app/routes/gear.py app/main.py tests/test_gear_routes.py
git commit -m "feat(gear): /api/gear/categories routes (add/rename/delete)"
```

---

## Task 7: `gear_plan` service — load + scaffold

**Files:**
- Create: `app/services/gear_plan.py`
- Create: `tests/test_gear_plan_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_gear_plan_service.py`:

```python
"""Tests for the gear-plan service."""

import pytest

from app.services import gear_plan as gp


def write_trip_md(trip_dir, frontmatter_yaml: str | None, body: str = "") -> None:
    gear_md = trip_dir / "gear.md"
    if frontmatter_yaml is None:
        gear_md.write_text(body, encoding="utf-8")
    else:
        gear_md.write_text(f"---\n{frontmatter_yaml}---\n{body}", encoding="utf-8")
    (trip_dir / "trip.md").write_text(
        "---\npark: killarney\n"
        "start_date: 2026-07-10\nend_date: 2026-07-12\n"
        "participants:\n  - Tom\n  - Alex\n  - Jordan\n---\n",
        encoding="utf-8",
    )


@pytest.fixture
def tmp_trips(tmp_path, monkeypatch):
    trips = tmp_path / "trips"
    (trips / "killarney-2026-07").mkdir(parents=True)
    monkeypatch.setattr(gp, "TRIPS_DIR", trips)
    return trips


def test_load_no_frontmatter_returns_empty_plan(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", None,
                  body="## Old gear table\n| A | B |\n")
    plan = gp.load("killarney-2026-07")
    assert plan["items"] == []
    assert plan["participants"] == ["Tom", "Alex", "Jordan"]
    assert "Old gear table" in plan["legacy_body"]


def test_load_with_frontmatter_round_trips(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", (
        "items:\n"
        "  - item_id: compass\n"
        "    qty: 1\n"
        "    who: Tom\n"
        "    notes: ''\n"
        "    override_weight_g: null\n"
    ), body="(generated)\n")
    plan = gp.load("killarney-2026-07")
    assert plan["items"][0]["item_id"] == "compass"
    assert plan["legacy_body"] == ""


def test_load_handles_crlf_line_endings(tmp_trips):
    """Windows-edited gear.md or trip.md may have CRLF line endings."""
    trip_dir = tmp_trips / "killarney-2026-07"
    (trip_dir / "gear.md").write_bytes(
        b"---\r\nitems:\r\n  - item_id: compass\r\n    qty: 1\r\n---\r\n"
    )
    (trip_dir / "trip.md").write_bytes(
        b"---\r\npark: killarney\r\n"
        b"start_date: 2026-07-10\r\nend_date: 2026-07-12\r\n"
        b"participants:\r\n  - Tom\r\n---\r\n"
    )
    plan = gp.load("killarney-2026-07")
    assert plan["items"][0]["item_id"] == "compass"
    assert plan["participants"] == ["Tom"]


def test_load_unknown_trip_raises(tmp_trips):
    with pytest.raises(FileNotFoundError):
        gp.load("nope")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_plan_service.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement load**

Create `app/services/gear_plan.py`:

```python
"""Per-trip gear-plan I/O.

The plan lives as YAML frontmatter in `trips/<slug>/gear.md`. The body below
the frontmatter is regenerated on every save. When a trip's gear.md has no
frontmatter (legacy / fresh trip), `load()` returns an empty plan and exposes
the prose under `legacy_body` so the UI can warn before it overwrites.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.config import TRIPS_DIR

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL,
)


def _trip_dir(slug: str) -> Path:
    d = TRIPS_DIR / slug
    if not d.is_dir():
        raise FileNotFoundError(f"trip not found: {slug}")
    return d


def _read_trip_frontmatter(trip_dir: Path) -> dict:
    text = (trip_dir / "trip.md").read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def load(slug: str) -> dict:
    """Return the gear plan for a trip.

    Shape:
        {
          "items": [{"item_id", "qty", "who", "notes", "override_weight_g"}, ...],
          "participants": [str, ...],
          "legacy_body": str   # populated only when gear.md had no frontmatter
        }
    """
    trip_dir = _trip_dir(slug)
    trip_fm = _read_trip_frontmatter(trip_dir)
    gear_md = trip_dir / "gear.md"
    raw = gear_md.read_text(encoding="utf-8") if gear_md.exists() else ""
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {
            "items": [],
            "participants": list(trip_fm.get("participants") or []),
            "legacy_body": raw.strip(),
        }
    plan_fm = yaml.safe_load(m.group(1)) or {}
    return {
        "items": list(plan_fm.get("items") or []),
        "participants": list(trip_fm.get("participants") or []),
        "legacy_body": "",
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_plan_service.py -v
```

Expected: 4/4 pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/gear_plan.py tests/test_gear_plan_service.py
git commit -m "feat(gear-plan): load() with frontmatter parse + CRLF tolerance"
```

---

## Task 8: `gear_plan` service — compute_totals

**Files:**
- Modify: `app/services/gear_plan.py`
- Modify: `tests/test_gear_plan_service.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_gear_plan_service.py`:

```python
SAMPLE_CATALOG = {
    "version": 1,
    "categories": ["Navigation", "Cook", "Other"],
    "items": [
        {"id": "compass", "name": "Compass", "category": "Navigation", "weight_g": 30},
        {"id": "stove", "name": "Stove", "category": "Cook", "weight_g": 73},
        {"id": "tent", "name": "Tent", "category": "Other", "weight_g": None},
    ],
}

SAMPLE_PLAN = {
    "items": [
        {"item_id": "compass", "qty": 1, "who": "Tom", "notes": "", "override_weight_g": None},
        {"item_id": "stove", "qty": 2, "who": "shared", "notes": "", "override_weight_g": None},
        {"item_id": "tent", "qty": 1, "who": "shared", "notes": "", "override_weight_g": None},
    ],
    "participants": ["Tom", "Alex"],
    "legacy_body": "",
}


def test_compute_totals_per_row():
    totals = gp.compute_totals(SAMPLE_PLAN, SAMPLE_CATALOG)
    rows = totals["items"]
    assert rows[0]["weight_g_each"] == 30
    assert rows[0]["weight_g_total"] == 30
    assert rows[1]["weight_g_each"] == 73
    assert rows[1]["weight_g_total"] == 146   # 73 * 2
    assert rows[2]["weight_g_each"] is None
    assert rows[2]["weight_g_total"] is None
    assert rows[2]["unknown_weight"] is True


def test_compute_totals_by_who_and_trip():
    totals = gp.compute_totals(SAMPLE_PLAN, SAMPLE_CATALOG)
    assert totals["by_who"]["Tom"] == 30
    assert totals["by_who"]["shared"] == 146  # only the stove counts (tent unknown)
    assert totals["trip_g"] == 176
    assert totals["unknown_count"] == 1


def test_compute_totals_override_weight():
    plan = {
        "items": [
            {"item_id": "compass", "qty": 1, "who": "Tom",
             "notes": "", "override_weight_g": 50},
            {"item_id": "tent", "qty": 1, "who": "shared",
             "notes": "", "override_weight_g": 1200},
        ],
        "participants": ["Tom"],
        "legacy_body": "",
    }
    totals = gp.compute_totals(plan, SAMPLE_CATALOG)
    assert totals["items"][0]["weight_g_each"] == 50
    assert totals["items"][1]["weight_g_each"] == 1200
    assert totals["items"][1]["unknown_weight"] is False
    assert totals["trip_g"] == 1250


def test_compute_totals_unknown_item_id():
    plan = {
        "items": [
            {"item_id": "ghost", "qty": 1, "who": "Tom",
             "notes": "", "override_weight_g": None},
        ],
        "participants": ["Tom"],
        "legacy_body": "",
    }
    totals = gp.compute_totals(plan, SAMPLE_CATALOG)
    row = totals["items"][0]
    assert row["unknown_item"] is True
    assert row["name"] is None
    assert row["category"] is None
    assert row["weight_g_total"] is None
    assert totals["trip_g"] == 0
    assert totals["unknown_count"] == 1
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_plan_service.py -v -k compute_totals
```

Expected: AttributeError on `gp.compute_totals`.

- [ ] **Step 3: Implement compute_totals**

Append to `app/services/gear_plan.py`:

```python
def compute_totals(plan: dict, catalog: dict) -> dict:
    """Compute per-row weights, by_who totals, trip total, unknown count.

    Returns:
        {
          "items": [{**row, "name", "category", "weight_g_each",
                     "weight_g_total", "unknown_weight", "unknown_item"}, ...],
          "by_who": {participant: int, "shared": int, ...},
          "trip_g": int,
          "unknown_count": int,
        }
    """
    by_id = {it["id"]: it for it in catalog.get("items", [])}
    out_rows: list[dict] = []
    by_who: dict[str, int] = {}
    trip_g = 0
    unknown_count = 0
    for row in plan.get("items", []):
        item = by_id.get(row.get("item_id"))
        unknown_item = item is None
        name = None if unknown_item else item["name"]
        category = None if unknown_item else item["category"]
        catalog_weight = None if unknown_item else item.get("weight_g")
        override = row.get("override_weight_g")
        weight_each = override if override is not None else catalog_weight
        qty = int(row.get("qty") or 0)
        if weight_each is None:
            weight_total = None
            unknown_count += 1
        else:
            weight_total = int(weight_each) * qty
            trip_g += weight_total
            who = row.get("who") or "shared"
            by_who[who] = by_who.get(who, 0) + weight_total
        out_rows.append({
            **row,
            "name": name,
            "category": category,
            "weight_g_each": weight_each,
            "weight_g_total": weight_total,
            "unknown_weight": weight_each is None,
            "unknown_item": unknown_item,
        })
    return {
        "items": out_rows,
        "by_who": by_who,
        "trip_g": trip_g,
        "unknown_count": unknown_count,
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_plan_service.py -v
```

Expected: 8/8 pass (4 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add app/services/gear_plan.py tests/test_gear_plan_service.py
git commit -m "feat(gear-plan): compute_totals (per-row, by_who, trip, unknown)"
```

---

## Task 9: `gear_plan` service — render_markdown_body + atomic save

**Files:**
- Modify: `app/services/gear_plan.py`
- Modify: `tests/test_gear_plan_service.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_gear_plan_service.py`:

```python
def test_render_markdown_body_lists_items_and_totals():
    body = gp.render_markdown_body(SAMPLE_PLAN, SAMPLE_CATALOG)
    assert "# Shared gear" in body
    assert "Total: **176 g (~0.2 kg)**" in body
    # Per-who line
    assert "shared 146 g" in body
    assert "Tom 30 g" in body
    # Per-row in the markdown table
    assert "Compass [Navigation]" in body
    assert "Stove [Cook]" in body
    assert "30 g" in body
    assert "146 g" in body
    # Tent has unknown weight
    assert "Tent [Other]" in body
    assert "? g" in body


def test_render_markdown_body_warns_on_unknown_count():
    body = gp.render_markdown_body(SAMPLE_PLAN, SAMPLE_CATALOG)
    assert "1 item with unknown weight" in body or "1 items with unknown weight" in body


def test_save_writes_frontmatter_and_regenerated_body(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", None)
    plan = {
        "items": [
            {"item_id": "compass", "qty": 1, "who": "Tom",
             "notes": "primary nav", "override_weight_g": None},
        ],
    }
    gp.save("killarney-2026-07", plan, catalog=SAMPLE_CATALOG)
    written = (tmp_trips / "killarney-2026-07" / "gear.md").read_text(encoding="utf-8")
    assert written.startswith("---\n")
    assert "item_id: compass" in written
    assert "<!-- generated from frontmatter on save; edit via UI -->" in written
    assert "# Shared gear" in written
    assert "primary nav" in written


def test_save_round_trips_through_load(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", None)
    plan = {
        "items": [
            {"item_id": "stove", "qty": 1, "who": "shared",
             "notes": "", "override_weight_g": None},
        ],
    }
    gp.save("killarney-2026-07", plan, catalog=SAMPLE_CATALOG)
    reloaded = gp.load("killarney-2026-07")
    assert reloaded["items"][0]["item_id"] == "stove"


def test_save_pulls_participants_from_trip_md(tmp_trips):
    """Body must report the correct people from trip.md, even though MealPlanIn-
    style payloads from the route don't carry participants. Regression for
    food-planner bug #2."""
    write_trip_md(tmp_trips / "killarney-2026-07", None)
    # write_trip_md sets participants=[Tom, Alex, Jordan] in trip.md
    plan = {
        "items": [
            {"item_id": "compass", "qty": 1, "who": "Tom",
             "notes": "", "override_weight_g": None},
        ],
    }
    gp.save("killarney-2026-07", plan, catalog=SAMPLE_CATALOG)
    body = (tmp_trips / "killarney-2026-07" / "gear.md").read_text(encoding="utf-8")
    # participants on the per-who line should include Tom (from trip.md)
    assert "Tom 30 g" in body
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_plan_service.py -v -k "render_markdown or save_"
```

Expected: AttributeError on `render_markdown_body` and `save`.

- [ ] **Step 3: Implement render + save**

Append to `app/services/gear_plan.py`:

```python
import os
import tempfile


def _format_weight_g(g: int | None) -> str:
    if g is None:
        return "? g"
    return f"{g:,} g"


def render_markdown_body(plan: dict, catalog: dict) -> str:
    """Build the human-readable markdown body from a plan + catalog."""
    totals = compute_totals(plan, catalog)
    trip_g = totals["trip_g"]
    trip_kg = trip_g / 1000

    lines: list[str] = ["# Shared gear", ""]
    lines.append(f"Total: **{trip_g:,} g (~{trip_kg:.1f} kg)**")

    if totals["by_who"]:
        # Always show "shared" first, then participants alphabetically.
        keys = sorted(totals["by_who"], key=lambda k: (k != "shared", k))
        per_who = "  ".join(f"{k} {totals['by_who'][k]:,} g" for k in keys)
        lines.append(per_who)
    if totals["unknown_count"]:
        n = totals["unknown_count"]
        word = "item" if n == 1 else "items"
        lines.append(f"\n⚠ {n} {word} with unknown weight")
    lines.append("")

    if totals["items"]:
        lines.append("| Item | Qty | Who | Weight | Notes |")
        lines.append("|---|---|---|---|---|")
        for row in totals["items"]:
            if row["unknown_item"]:
                name_disp = f"Unknown ({row['item_id']})"
                cat_disp = "?"
            else:
                name_disp = row["name"] or "?"
                cat_disp = row["category"] or "?"
            weight = _format_weight_g(row["weight_g_total"])
            notes = (row.get("notes") or "").replace("|", "\\|").replace("\n", " ")
            who = row.get("who") or "shared"
            lines.append(
                f"| {name_disp} [{cat_disp}] | {row.get('qty', 0)} | "
                f"{who} | {weight} | {notes} |"
            )

    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix="gear-", suffix=".md", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(slug: str, plan: dict, catalog: dict) -> None:
    """Rewrite trips/<slug>/gear.md with YAML frontmatter + regenerated body."""
    trip_dir = _trip_dir(slug)
    fm_dump = yaml.safe_dump(
        {"items": plan.get("items") or []},
        sort_keys=False,
        allow_unicode=True,
    )
    # Pull participants from trip.md so the rendered body's by_who line is correct,
    # even when callers (route handlers) pass plans that don't carry participants.
    trip_fm = _read_trip_frontmatter(trip_dir)
    plan_with_participants = {
        **plan,
        "participants": list(trip_fm.get("participants") or []),
    }
    body = render_markdown_body(plan_with_participants, catalog)
    text = (
        "---\n"
        f"{fm_dump}"
        "---\n\n"
        "<!-- generated from frontmatter on save; edit via UI -->\n"
        f"{body}"
    )
    _atomic_write(trip_dir / "gear.md", text)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_plan_service.py -v
```

Expected: 13/13 pass (8 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add app/services/gear_plan.py tests/test_gear_plan_service.py
git commit -m "feat(gear-plan): render_markdown_body + atomic save (with participants)"
```

---

## Task 10: `/api/trip/{slug}/gear-plan` routes + load_trip_payload integration

**Files:**
- Modify: `app/models.py`
- Modify: `app/routes/gear.py`
- Modify: `app/main.py`
- Modify: `app/services/trips.py`
- Create: `tests/test_gear_plan_routes.py`

- [ ] **Step 1: Add Pydantic models**

Append to `app/models.py`:

```python
class GearPlanItem(BaseModel):
    item_id: str
    qty: int = Field(default=1, ge=0)
    who: str = ""
    notes: str = ""
    override_weight_g: int | None = Field(default=None, ge=0)


class GearPlanIn(BaseModel):
    items: list[GearPlanItem] = Field(default_factory=list)


class GearPlanOut(BaseModel):
    ok: bool = True
    plan: dict
    totals: dict
```

- [ ] **Step 2: Write failing route tests**

Create `tests/test_gear_plan_routes.py`:

```python
"""End-to-end tests for the gear-plan routes and trip-payload integration."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, gear as gear_svc, gear_plan as gp_svc, trips as trips_svc

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    catalog_path = tmp_path / "gear.json"
    catalog_path.write_text(json.dumps({
        "version": 1,
        "categories": ["Navigation", "Cook", "Other"],
        "items": [
            {"id": "compass", "name": "Compass",
             "category": "Navigation", "weight_g": 30},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(gear_svc, "GEAR_JSON", catalog_path)
    gear_svc._invalidate_cache()

    tmp_trips = tmp_path / "trips"
    if (REPO_ROOT / "trips").exists():
        shutil.copytree(REPO_ROOT / "trips", tmp_trips)
    else:
        tmp_trips.mkdir()
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(gp_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(gear_svc, "TRIPS_DIR", tmp_trips)

    tmp_db = tmp_path / "test.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)

    yield TestClient(app)


def test_get_gear_plan_returns_scaffold_for_legacy_trip(client, tmp_path):
    """Self-contained legacy trip — don't depend on a repo trip's current state."""
    trip_dir = tmp_path / "trips" / "legacy-2026-09"
    trip_dir.mkdir(parents=True)
    (trip_dir / "trip.md").write_text(
        "---\npark: killarney\n"
        "start_date: 2026-09-04\nend_date: 2026-09-06\n"
        "participants:\n  - Sam\n---\n", encoding="utf-8",
    )
    (trip_dir / "gear.md").write_text(
        "## Shared gear\n\n| Item |\n|---|\n| Old | \n", encoding="utf-8",
    )
    r = client.get("/api/trip/legacy-2026-09/gear-plan")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["plan"]["items"] == []
    assert body["plan"]["legacy_body"]
    assert body["totals"]["trip_g"] == 0


def test_post_gear_plan_saves_and_round_trips(client, tmp_path):
    trip_dir = tmp_path / "trips" / "freshtrip-2026-09"
    trip_dir.mkdir(parents=True)
    (trip_dir / "trip.md").write_text(
        "---\npark: killarney\nstart_date: 2026-09-04\n"
        "end_date: 2026-09-06\nparticipants:\n  - Sam\n---\n",
        encoding="utf-8",
    )
    (trip_dir / "gear.md").write_text(
        "---\nitems: []\n---\n\n# Shared gear\n", encoding="utf-8",
    )
    payload = {"items": [
        {"item_id": "compass", "qty": 1, "who": "Sam",
         "notes": "", "override_weight_g": None},
    ]}
    r = client.post("/api/trip/freshtrip-2026-09/gear-plan", json=payload)
    assert r.status_code == 200
    r2 = client.get("/api/trip/freshtrip-2026-09/gear-plan")
    plan = r2.json()["plan"]
    assert plan["items"][0]["item_id"] == "compass"
    assert plan["legacy_body"] == ""


def test_trip_payload_marks_gear_section_as_gear_plan(client):
    r = client.get("/api/trip/killarney-2026-05")
    assert r.status_code == 200
    body = r.json()
    gear_section = next(s for s in body["sections"] if s["id"] == "gear")
    assert gear_section["kind"] == "gear-plan"
    assert gear_section["editable"] is False


def test_gear_section_is_not_legacy_editable(client):
    """Regression: gear section must not accept the legacy save-section API
    (would destroy the YAML frontmatter — same bug we hit on food)."""
    r = client.post(
        "/api/save-section?trip=killarney-2026-05&section=gear",
        json={"markdown": "garbage"},
    )
    assert r.status_code == 400


def test_gear_section_is_not_table_editable(client):
    """save-section-table on gear should also be rejected (was previously
    allowed via the gear table editor)."""
    r = client.post(
        "/api/save-section-table?trip=killarney-2026-05&section=gear",
        json={"rows": [["x", "y", "z"]]},
    )
    assert r.status_code == 400
```

- [ ] **Step 3: Add meal-plan-style routes for gear**

Append to `app/routes/gear.py`:

```python
from app.models import GearPlanIn, GearPlanOut

trip_gear_router = APIRouter(prefix="/api/trip")


@trip_gear_router.get("/{slug}/gear-plan", response_model=GearPlanOut)
def get_gear_plan(slug: str):
    from app.services import gear_plan as gp_svc
    try:
        plan = gp_svc.load(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "trip not found"})
    catalog = gear_svc.load_catalog()
    totals = gp_svc.compute_totals(plan, catalog)
    return GearPlanOut(plan=plan, totals=totals)


@trip_gear_router.post("/{slug}/gear-plan", response_model=OkResponse)
def save_gear_plan(slug: str, body: GearPlanIn):
    from app.services import gear_plan as gp_svc
    try:
        catalog = gear_svc.load_catalog()
        gp_svc.save(slug, body.model_dump(), catalog=catalog)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "trip not found"})
    return OkResponse()
```

- [ ] **Step 4: Register the new router**

Modify `app/main.py` — add after the other gear includes:

```python
app.include_router(gear.trip_gear_router)
```

- [ ] **Step 5: Mark gear section in trip payload + remove from EDITABLE_SECTIONS**

Modify `app/services/trips.py`:

- Find the constant: `EDITABLE_SECTIONS = {"intro", "itinerary", "gear", "packing", "costs"}`. Remove `"gear"`:

```python
EDITABLE_SECTIONS = {"intro", "itinerary", "packing", "costs"}
```

- Find `TABLE_SECTIONS = {"gear", "costs"}`. Remove `"gear"`:

```python
TABLE_SECTIONS = {"costs"}
```

- In `load_trip_payload`, find the existing food-section special-case (which sets `kind: "meal-plan"`). Add a parallel special-case for `gear`. The food-handling block currently looks like:

```python
    for section_id in ("gear", "food", "packing", "costs"):
        if section_id == "food":
            try:
                plan = mp_svc.load(slug)
                catalog = foods_svc.load_catalog()
                totals = mp_svc.compute_totals(plan, catalog)
            except Exception:
                plan, totals = {}, {}
            sections.append({
                "id": "food",
                "title": "Food",
                "editable": False,
                "kind": "meal-plan",
                "html": "",
                "payload": {"plan": plan, "totals": totals},
            })
        else:
            section_html = build_trip.render_section(trip[section_id], section_id)
            if section_id == "costs":
                section_html += costs_summary_html(trip["costs"], participant_count)
            sections.append({
                "id": section_id,
                "title": section_id.capitalize(),
                "editable": True,
                "kind": "html",
                "payload": None,
                "html": section_html,
            })
```

Replace with (adds local imports for gear too, and a `gear` branch that mirrors the `food` branch):

```python
    from app.services import foods as foods_svc
    from app.services import gear as gear_svc
    from app.services import gear_plan as gp_svc
    from app.services import meal_plan as mp_svc

    for section_id in ("gear", "food", "packing", "costs"):
        if section_id == "food":
            try:
                plan = mp_svc.load(slug)
                catalog = foods_svc.load_catalog()
                totals = mp_svc.compute_totals(plan, catalog)
            except Exception:
                plan, totals = {}, {}
            sections.append({
                "id": "food",
                "title": "Food",
                "editable": False,
                "kind": "meal-plan",
                "html": "",
                "payload": {"plan": plan, "totals": totals},
            })
        elif section_id == "gear":
            try:
                plan = gp_svc.load(slug)
                catalog = gear_svc.load_catalog()
                totals = gp_svc.compute_totals(plan, catalog)
            except Exception:
                plan, totals = {}, {}
            sections.append({
                "id": "gear",
                "title": "Shared gear",
                "editable": False,
                "kind": "gear-plan",
                "html": "",
                "payload": {"plan": plan, "totals": totals},
            })
        else:
            section_html = build_trip.render_section(trip[section_id], section_id)
            if section_id == "costs":
                section_html += costs_summary_html(trip["costs"], participant_count)
            sections.append({
                "id": section_id,
                "title": section_id.capitalize(),
                "editable": True,
                "kind": "html",
                "payload": None,
                "html": section_html,
            })
```

(If the existing `mp_svc` / `foods_svc` imports aren't already at the top of `load_trip_payload`, leave them where they are — these new local imports for gear sit alongside whatever's already there.)

- [ ] **Step 6: Run tests — verify they pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/test_gear_plan_routes.py tests/test_routes.py -v
```

Expected: all pass — 5 new gear-plan-route tests + the existing route tests still green.

Then full suite:

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add app/models.py app/routes/gear.py app/main.py app/services/trips.py tests/test_gear_plan_routes.py
git commit -m "feat(gear-plan): /api/trip/{slug}/gear-plan + payload kind=gear-plan"
```

---

## Task 11: SPA `/gear` route + sidebar link + asset stubs

**Files:**
- Modify: `app/routes/pages.py`
- Modify: `app/templates/index.html`
- Create: `app/static/css/gear.css`
- Create: `app/static/js/gear.js`
- Modify: `app/static/js/index.js`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Add the page route**

Modify `app/routes/pages.py` — add after the existing `foods_page`:

```python
@router.get("/gear", response_class=HTMLResponse)
def gear_page(request: Request):
    return _render_shell(request)
```

- [ ] **Step 2: Add sidebar link + asset includes**

Modify `app/templates/index.html`:

In `head_extra` (after the existing `foods.css` include):

```html
<link rel="stylesheet" href="/static/css/gear.css">
<script src="/static/js/gear.js" defer></script>
<script src="/static/js/gear-plan.js" defer></script>
```

In the sidebar nav (after the `Foods DB` button):

```html
<button class="nav-btn" data-route="/gear">Gear DB</button>
```

Add a foods-style template stub at the end of the templates section:

```html
<template id="tpl-gear">
  <section class="gear-page">
    <header class="gear-header">
      <h2>Gear</h2>
      <div class="gear-toolbar">
        <input type="search" id="gear-search" placeholder="Search gear…">
        <select id="gear-category-filter">
          <option value="">All categories</option>
        </select>
        <button id="gear-manage-cats" class="btn secondary">Manage categories…</button>
        <button id="gear-add" class="btn">+ Add item</button>
      </div>
    </header>
    <div class="gear-body">
      <ul id="gear-list" class="gear-list"></ul>
      <div id="gear-detail" class="gear-detail"></div>
    </div>
  </section>
</template>
```

- [ ] **Step 3: Stub the assets**

Create `app/static/css/gear.css`:

```css
.gear-page { display: flex; flex-direction: column; gap: 1rem; }
.gear-header { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
.gear-toolbar { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.gear-toolbar input[type=search] { padding: 0.4rem 0.6rem; min-width: 14rem; }
.gear-toolbar select { padding: 0.4rem; }
.gear-body { display: grid; grid-template-columns: 22rem 1fr; gap: 1rem; min-height: 24rem; }
.gear-list { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border, #d4d4d8); border-radius: 6px; overflow-y: auto; max-height: 70vh; }
.gear-list li { padding: 0.5rem 0.75rem; cursor: pointer; border-bottom: 1px solid var(--border, #eaeaea); display: flex; align-items: center; gap: 0.5rem; }
.gear-list li:hover { background: var(--hover, #f4f4f5); }
.gear-list li.selected { background: var(--accent-light, #dbeafe); font-weight: 600; }
.gear-list .gear-name { flex: 1; }
.gear-list .gear-weight { color: var(--muted, #71717a); font-size: 0.85em; font-variant-numeric: tabular-nums; }
.gear-pill { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.75em; color: white; font-weight: 500; }
.gear-detail { border: 1px solid var(--border, #d4d4d8); border-radius: 6px; padding: 1rem; }
.gear-detail label { display: block; margin-bottom: 0.6rem; font-weight: 500; }
.gear-detail input, .gear-detail select { display: block; width: 100%; padding: 0.4rem; margin-top: 0.2rem; }
.gear-detail .weight-row { display: flex; gap: 0.5rem; align-items: center; }
.gear-detail .weight-row input { flex: 1; }
.gear-detail .weight-row button { padding: 0.3rem 0.5rem; border: 1px solid var(--border, #d4d4d8); border-radius: 4px; background: white; cursor: pointer; }
.gear-detail .actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
.gear-detail .danger { background: #ef4444; color: white; }
.gear-detail .empty { color: var(--muted, #71717a); padding: 2rem; text-align: center; }
.gear-detail .error-banner { background: #fee2e2; color: #991b1b; padding: 0.6rem; border-radius: 4px; margin-bottom: 0.6rem; }

/* Manage categories modal */
.gear-cat-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.gear-cat-modal { background: white; padding: 1.5rem; border-radius: 8px; min-width: 24rem; max-width: 32rem; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
.gear-cat-modal h3 { margin: 0 0 0.8rem; }
.gear-cat-list { list-style: none; margin: 0 0 1rem; padding: 0; max-height: 20rem; overflow-y: auto; }
.gear-cat-list li { display: flex; justify-content: space-between; align-items: center; padding: 0.4rem 0; border-bottom: 1px solid var(--border, #eaeaea); }
.gear-cat-list li.protected { color: var(--muted, #71717a); font-style: italic; }
.gear-cat-list button { padding: 0.2rem 0.5rem; border: 1px solid var(--border, #d4d4d8); border-radius: 4px; background: white; cursor: pointer; font-size: 0.85em; }
.gear-cat-list button.danger { color: #b91c1c; border-color: #fecaca; }
.gear-cat-add { display: flex; gap: 0.5rem; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border, #eaeaea); }
.gear-cat-add input { flex: 1; padding: 0.3rem; }
.gear-cat-add button { padding: 0.3rem 0.8rem; }
```

Create `app/static/js/gear.js` — minimal stub (real UI in Tasks 12-14):

```javascript
/* Gear DB page (master-detail). Mounted by index.js when route is /gear. */
(function (global) {
  'use strict';

  function mount(root) {
    const tpl = document.getElementById('tpl-gear');
    if (!tpl) return;
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    document.getElementById('gear-detail').innerHTML =
      '<div class="empty">Select an item on the left, or click "+ Add item".</div>';
  }

  global.GearPage = { mount };
}(window));
```

- [ ] **Step 4: Wire `/gear` into the SPA router**

Modify `app/static/js/index.js`. The existing food route is wired in `render()` with a branch like:

```javascript
} else if (path === '/foods') {
  if (window.FoodsPage) window.FoodsPage.mount(mainPane);
}
```

Add the `/gear` branch right after the `/foods` branch:

```javascript
} else if (path === '/gear') {
  if (window.GearPage) window.GearPage.mount(mainPane);
}
```

If the existing routing pattern differs slightly (e.g. uses a switch / map), match it. The goal: navigating to `/gear` calls `window.GearPage.mount(mainPane)`.

- [ ] **Step 5: Add a route test**

Append to `tests/test_routes.py` (next to `test_foods_page_serves_shell` if present, otherwise next to `test_trip_slug_url_serves_shell`):

```python
def test_gear_page_serves_shell(client):
    r = client.get("/gear")
    assert r.status_code == 200
    assert 'id="main-pane"' in r.text
    assert "Gear DB" in r.text  # sidebar link
```

- [ ] **Step 6: Run tests**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add app/routes/pages.py app/templates/index.html app/static/css/gear.css app/static/js/gear.js app/static/js/index.js tests/test_routes.py
git commit -m "feat(gear-ui): /gear page scaffold + sidebar link"
```

---

## Task 12: `/gear` page — list + search + filter + detail form

**Files:**
- Modify: `app/static/js/gear.js`

- [ ] **Step 1: Implement the master-detail page**

Replace the contents of `app/static/js/gear.js` with:

```javascript
/* Gear DB page (master-detail). */
(function (global) {
  'use strict';

  let state = {
    catalog: { categories: [], items: [] },
    selectedId: null,
    query: '',
    category: '',
    draft: null,
    weightUnknown: false,
    dirty: false,
    error: '',
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // Deterministic colour for a category — same colour everywhere across reloads.
  function pillColor(category) {
    const palette = ['#2563eb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed',
                     '#0891b2', '#db2777', '#65a30d', '#ea580c', '#475569',
                     '#9333ea', '#0d9488'];
    let h = 0;
    for (let i = 0; i < category.length; i++) h = (h * 31 + category.charCodeAt(i)) >>> 0;
    return palette[h % palette.length];
  }

  function renderCategoryPill(category) {
    return `<span class="gear-pill" style="background:${pillColor(category)}">${escapeHtml(category)}</span>`;
  }

  async function fetchCatalog() {
    const r = await fetch('/api/gear');
    if (!r.ok) throw new Error('failed to load /api/gear');
    return r.json();
  }

  function renderCategoryFilter() {
    const sel = document.getElementById('gear-category-filter');
    sel.innerHTML = '<option value="">All categories</option>'
      + state.catalog.categories.map(c => `<option value="${c}">${c}</option>`).join('');
    sel.value = state.category;
  }

  function filteredItems() {
    const q = state.query.toLowerCase().trim();
    return state.catalog.items.filter(it => {
      if (state.category && it.category !== state.category) return false;
      if (q && !it.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderList() {
    const ul = document.getElementById('gear-list');
    const items = filteredItems();
    if (!items.length) {
      ul.innerHTML = '<li style="cursor:default;color:#999">No matches.</li>';
      return;
    }
    ul.innerHTML = items.map(it => {
      const wt = it.weight_g === null || it.weight_g === undefined
        ? '? g' : `${it.weight_g.toLocaleString()} g`;
      return `<li data-id="${escapeHtml(it.id)}"${state.selectedId === it.id ? ' class="selected"' : ''}>`
        + `<span class="gear-name">${escapeHtml(it.name)}</span>`
        + renderCategoryPill(it.category)
        + `<span class="gear-weight">${wt}</span>`
        + `</li>`;
    }).join('');
    ul.querySelectorAll('li[data-id]').forEach(li => {
      li.addEventListener('click', () => {
        if (state.dirty && !confirm('Discard unsaved changes?')) return;
        select(li.dataset.id);
      });
    });
  }

  function select(id) {
    state.selectedId = id;
    state.error = '';
    if (id === '__new__') {
      state.draft = { id: '', name: '',
                      category: state.catalog.categories[0] || 'Other',
                      weight_g: 0 };
      state.weightUnknown = false;
      state.dirty = true;
    } else {
      const it = state.catalog.items.find(x => x.id === id);
      state.draft = it ? { ...it } : null;
      state.weightUnknown = it && it.weight_g === null;
      state.dirty = false;
    }
    renderList();
    renderDetail();
  }

  function bindDraftField(field, type) {
    return (e) => {
      let v = e.target.value;
      if (type === 'int') v = parseInt(v, 10) || 0;
      state.draft[field] = v;
      state.dirty = true;
    };
  }

  function renderDetail() {
    const el = document.getElementById('gear-detail');
    if (!state.draft) {
      el.innerHTML = '<div class="empty">Select an item on the left, or click "+ Add item".</div>';
      return;
    }
    const d = state.draft;
    const isNew = state.selectedId === '__new__';
    const catOpts = state.catalog.categories
      .map(c => `<option value="${c}"${c === d.category ? ' selected' : ''}>${c}</option>`).join('');
    const errBanner = state.error
      ? `<div class="error-banner">${escapeHtml(state.error)}</div>` : '';
    const weightVal = state.weightUnknown ? '' : (d.weight_g || 0);
    const weightDisabled = state.weightUnknown ? 'disabled' : '';
    const weightToggleLabel = state.weightUnknown ? '↩ set weight' : '✗ unk';
    el.innerHTML = `
      ${errBanner}
      <label>Name <input type="text" id="gd-name" value="${escapeHtml(d.name)}"></label>
      <label>Category <select id="gd-category">${catOpts}</select></label>
      <label>Weight (g)
        <div class="weight-row">
          <input type="number" id="gd-weight" min="0" step="1" value="${weightVal}" ${weightDisabled}>
          <button type="button" id="gd-weight-toggle">${weightToggleLabel}</button>
        </div>
      </label>
      <div class="actions">
        <button class="btn" id="gd-save">${isNew ? 'Create' : 'Save'}</button>
        ${isNew ? '' : '<button class="btn danger" id="gd-delete">× Delete</button>'}
      </div>
    `;
    document.getElementById('gd-name').addEventListener('input', bindDraftField('name'));
    document.getElementById('gd-category').addEventListener('change', bindDraftField('category'));
    document.getElementById('gd-weight').addEventListener('input', bindDraftField('weight_g', 'int'));
    document.getElementById('gd-weight-toggle').addEventListener('click', () => {
      state.weightUnknown = !state.weightUnknown;
      state.dirty = true;
      renderDetail();
    });
    document.getElementById('gd-save').addEventListener('click', save);
    if (!isNew) document.getElementById('gd-delete').addEventListener('click', () => del(d.id));
  }

  async function save() {
    state.error = '';
    const d = state.draft;
    const isNew = state.selectedId === '__new__';
    const payload = {
      name: d.name,
      category: d.category,
      weight_g: state.weightUnknown ? null : (d.weight_g || 0),
    };
    try {
      let res;
      if (isNew) {
        res = await fetch('/api/gear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch(`/api/gear/${encodeURIComponent(d.id)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        state.error = (j.detail && j.detail.error) || `HTTP ${res.status}`;
        renderDetail();
        return;
      }
      const newId = isNew ? (await res.json()).id : d.id;
      state.catalog = await fetchCatalog();
      state.dirty = false;
      select(newId);
    } catch (err) {
      state.error = String(err);
      renderDetail();
    }
  }

  async function del(id) {
    if (!confirm(`Delete "${state.draft.name}"?`)) return;
    let res = await fetch(`/api/gear/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (res.status === 409) {
      const j = await res.json();
      const refs = (j.detail && j.detail.references) || [];
      const msg = `This item is used by ${refs.length} trip(s):\n  ${refs.join('\n  ')}\n\nDelete anyway?`;
      if (!confirm(msg)) return;
      res = await fetch(`/api/gear/${encodeURIComponent(id)}?force=true`, { method: 'DELETE' });
    }
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      state.error = (j.detail && j.detail.error) || `HTTP ${res.status}`;
      renderDetail();
      return;
    }
    state.catalog = await fetchCatalog();
    state.selectedId = null;
    state.draft = null;
    state.dirty = false;
    renderList();
    renderDetail();
  }

  async function mount(root) {
    const tpl = document.getElementById('tpl-gear');
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    state = { catalog: { categories: [], items: [] }, selectedId: null,
              query: '', category: '', draft: null, weightUnknown: false,
              dirty: false, error: '' };
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderDetail();
    document.getElementById('gear-search').addEventListener('input', (e) => {
      state.query = e.target.value;
      renderList();
    });
    document.getElementById('gear-category-filter').addEventListener('change', (e) => {
      state.category = e.target.value;
      renderList();
    });
    document.getElementById('gear-add').addEventListener('click', () => {
      if (state.dirty && !confirm('Discard unsaved changes?')) return;
      select('__new__');
    });
    document.getElementById('gear-manage-cats').addEventListener('click', () => {
      // Implemented in Task 13.
      alert('Manage categories modal added in Task 13.');
    });
  }

  global.GearPage = { mount };
}(window));
```

- [ ] **Step 2: Manual smoke test**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 &
```

Visit http://127.0.0.1:8000/gear:
- 20 seed items in the list with category pills + weights (or `?` for null weight).
- Search filters live; category dropdown filters; clicking a row populates the form.
- Edit weight + Save → list refreshes with new weight.
- "+ Add item" → blank form → fill → Create → row appears in list.
- Delete an item not in any trip → row disappears.
- Toggle "✗ unk" on the weight field → input greys out; on save the weight is saved as null.

- [ ] **Step 3: Verify Python tests still pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add app/static/js/gear.js
git commit -m "feat(gear-ui): list + search + filter + detail form (CRUD)"
```

---

## Task 13: Manage Categories modal

**Files:**
- Modify: `app/static/js/gear.js`

- [ ] **Step 1: Replace the manage-cats button handler with a working modal**

In `app/static/js/gear.js`, find the `mount` function's `gear-manage-cats` handler:

```javascript
    document.getElementById('gear-manage-cats').addEventListener('click', () => {
      // Implemented in Task 13.
      alert('Manage categories modal added in Task 13.');
    });
```

Replace with:

```javascript
    document.getElementById('gear-manage-cats').addEventListener('click', openManageCatsModal);
```

Add (anywhere alongside the other functions in the IIFE, e.g. just before `mount`):

```javascript
  function openManageCatsModal() {
    const overlay = document.createElement('div');
    overlay.className = 'gear-cat-modal-overlay';
    overlay.innerHTML = `
      <div class="gear-cat-modal">
        <h3>Manage categories</h3>
        <div class="gear-cat-error" hidden></div>
        <ul class="gear-cat-list"></ul>
        <div class="gear-cat-add">
          <input type="text" id="gca-new" maxlength="40" placeholder="Add category…">
          <button class="btn" id="gca-add-btn">Add</button>
          <button class="btn secondary" id="gca-close">Close</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector('#gca-close').addEventListener('click', () => overlay.remove());
    overlay.querySelector('#gca-add-btn').addEventListener('click', () => addCategory(overlay));
    renderCategoryList(overlay);
  }

  function showCatError(overlay, msg) {
    const el = overlay.querySelector('.gear-cat-error');
    el.textContent = msg;
    el.hidden = !msg;
    if (msg) el.style.cssText = 'background:#fee2e2;color:#991b1b;padding:0.5rem;border-radius:4px;margin-bottom:0.6rem';
  }

  function renderCategoryList(overlay) {
    const ul = overlay.querySelector('.gear-cat-list');
    ul.innerHTML = state.catalog.categories.map(c => {
      if (c === 'Other') {
        return `<li class="protected"><span>${escapeHtml(c)}  (default — can't remove)</span></li>`;
      }
      return `<li data-cat="${escapeHtml(c)}">
        <span class="gear-cat-name">${escapeHtml(c)}</span>
        <span>
          <button data-act="rename">Rename</button>
          <button class="danger" data-act="delete">× Delete</button>
        </span>
      </li>`;
    }).join('');
    ul.querySelectorAll('li[data-cat]').forEach(li => {
      const cat = li.dataset.cat;
      li.querySelector('[data-act="rename"]').addEventListener('click',
        () => beginRename(overlay, li, cat));
      li.querySelector('[data-act="delete"]').addEventListener('click',
        () => deleteCategory(overlay, cat));
    });
  }

  function beginRename(overlay, li, cat) {
    const span = li.querySelector('.gear-cat-name');
    const actions = li.querySelector('span:last-child');
    span.outerHTML = `<input class="gear-cat-rename" type="text" value="${escapeHtml(cat)}" maxlength="40" style="flex:1;padding:0.2rem">`;
    actions.innerHTML = `
      <button data-act="save">Save</button>
      <button class="secondary" data-act="cancel">Cancel</button>
    `;
    li.querySelector('[data-act="save"]').addEventListener('click', async () => {
      const newName = li.querySelector('.gear-cat-rename').value.trim();
      if (!newName || newName === cat) { renderCategoryList(overlay); return; }
      const r = await fetch(`/api/gear/categories/${encodeURIComponent(cat)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        showCatError(overlay, (j.detail && j.detail.error) || `HTTP ${r.status}`);
        return;
      }
      showCatError(overlay, '');
      state.catalog = await fetchCatalog();
      renderCategoryFilter();
      renderList();
      renderCategoryList(overlay);
    });
    li.querySelector('[data-act="cancel"]').addEventListener('click', () => renderCategoryList(overlay));
  }

  async function deleteCategory(overlay, cat) {
    let r = await fetch(`/api/gear/categories/${encodeURIComponent(cat)}`, { method: 'DELETE' });
    if (r.status === 409) {
      const j = await r.json();
      const msg = (j.detail && j.detail.error) || 'in use';
      if (!confirm(`${msg}\n\nReassign affected items to "Other" and delete?`)) return;
      r = await fetch(`/api/gear/categories/${encodeURIComponent(cat)}?force=true`,
                       { method: 'DELETE' });
    }
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      showCatError(overlay, (j.detail && j.detail.error) || `HTTP ${r.status}`);
      return;
    }
    showCatError(overlay, '');
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderCategoryList(overlay);
  }

  async function addCategory(overlay) {
    const inp = overlay.querySelector('#gca-new');
    const name = inp.value.trim();
    if (!name) return;
    const r = await fetch('/api/gear/categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      showCatError(overlay, (j.detail && j.detail.error) || `HTTP ${r.status}`);
      return;
    }
    showCatError(overlay, '');
    inp.value = '';
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderCategoryList(overlay);
  }
```

- [ ] **Step 2: Smoke test**

Run uvicorn, visit `/gear`, click `Manage categories…`. Try:
- Add a category ("Photography") — appears in the list.
- Rename it inline → list refreshes with the new name.
- Delete it (not in use) → row removed.
- Try to delete an in-use category — confirmation dialog offers reassign-to-Other.
- "Other" shows as protected with no buttons.

- [ ] **Step 3: Verify Python tests still pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add app/static/js/gear.js
git commit -m "feat(gear-ui): manage-categories modal (add/rename/delete + reassign)"
```

---

## Task 14: Trip-page gear plan — shell + header + table rendering

**Files:**
- Create: `app/static/js/gear-plan.js`
- Modify: `app/static/css/trip.css`
- Modify: `app/static/js/trip.js`

- [ ] **Step 1: Create `app/static/js/gear-plan.js`**

```javascript
/* Trip-page gear plan. Mounted by trip.js when a section has kind=gear-plan. */
(function (global) {
  'use strict';

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function pillColor(category) {
    if (!category) return '#9ca3af';
    const palette = ['#2563eb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed',
                     '#0891b2', '#db2777', '#65a30d', '#ea580c', '#475569',
                     '#9333ea', '#0d9488'];
    let h = 0;
    for (let i = 0; i < category.length; i++) h = (h * 31 + category.charCodeAt(i)) >>> 0;
    return palette[h % palette.length];
  }

  function init(sectionEl, slug, payload) {
    let plan = (payload && payload.plan) || { items: [], participants: [], legacy_body: '' };
    let totals = (payload && payload.totals) || { items: [], by_who: {}, trip_g: 0, unknown_count: 0 };
    let catalog = { items: [], categories: [] };

    function recomputeTotals() {
      const byId = Object.fromEntries(catalog.items.map(it => [it.id, it]));
      const out = [];
      const byWho = {};
      let tripG = 0;
      let unknownCount = 0;
      for (const row of plan.items) {
        const item = byId[row.item_id];
        const unknown_item = !item;
        const name = unknown_item ? null : item.name;
        const category = unknown_item ? null : item.category;
        const catalogWeight = unknown_item ? null : (item.weight_g ?? null);
        const override = row.override_weight_g ?? null;
        const eachWeight = override !== null ? override : catalogWeight;
        const qty = parseInt(row.qty, 10) || 0;
        let total = null;
        const unknown_weight = eachWeight === null;
        if (eachWeight === null) {
          unknownCount += 1;
        } else {
          total = eachWeight * qty;
          tripG += total;
          const who = row.who || 'shared';
          byWho[who] = (byWho[who] || 0) + total;
        }
        out.push({ ...row, name, category, weight_g_each: eachWeight,
                   weight_g_total: total, unknown_weight, unknown_item });
      }
      totals = { items: out, by_who: byWho, trip_g: tripG, unknown_count: unknownCount };
    }

    function renderHeader() {
      const tripG = totals.trip_g;
      const tripKg = (tripG / 1000).toFixed(1);
      const whoKeys = Object.keys(totals.by_who)
        .sort((a, b) => (a === 'shared' ? -1 : b === 'shared' ? 1 : a.localeCompare(b)));
      const whoLine = whoKeys.length
        ? whoKeys.map(k => `${escapeHtml(k)} ${totals.by_who[k].toLocaleString()} g`).join('  •  ')
        : '';
      const unkLine = totals.unknown_count
        ? `<span class="gp-warn">⚠ ${totals.unknown_count} item${totals.unknown_count === 1 ? '' : 's'} with unknown weight</span>`
        : '';
      return `
        <div class="gp-header">
          <div class="gp-total"><b>Total: ${tripG.toLocaleString()} g (~${tripKg} kg)</b></div>
          ${whoLine ? `<div class="gp-bywho">${whoLine}</div>` : ''}
          ${unkLine ? `<div>${unkLine}</div>` : ''}
        </div>
      `;
    }

    function renderRow(row, idx) {
      const cat = row.category || '?';
      const eachDisp = row.weight_g_each === null
        ? '?' : row.weight_g_each.toLocaleString();
      const totalDisp = row.weight_g_total === null
        ? '? g' : `${row.weight_g_total.toLocaleString()} g`;
      const isOverride = row.override_weight_g !== null && row.override_weight_g !== undefined;
      const overrideHtml = isOverride
        ? `<input type="number" class="gp-wt-override" min="0" step="1" value="${row.override_weight_g}">
           <a href="#" class="gp-revert">↩ revert</a>`
        : `<span class="gp-wt-each">${eachDisp}</span>
           <a href="#" class="gp-edit-wt">[edit]</a>`;
      const unknownClass = row.unknown_item ? ' gp-unknown' : '';
      const whoOptions = ['shared', ...plan.participants]
        .map(p => `<option value="${escapeHtml(p)}"${row.who === p ? ' selected' : ''}>${escapeHtml(p)}</option>`).join('');
      const itemDisp = row.unknown_item
        ? `<span style="color:#b45309">Unknown: ${escapeHtml(row.item_id || '')}</span>`
        : (row.name ? escapeHtml(row.name) : '');
      const catPill = `<span class="gear-pill" style="background:${pillColor(cat)}">${escapeHtml(cat)}</span>`;
      const warn = row.unknown_weight && !row.unknown_item
        ? `<span class="gp-warn">⚠ unknown weight</span>` : '';
      return `
        <div class="gp-row${unknownClass}" data-idx="${idx}">
          <div class="gp-cell gp-item-cell">
            <input type="text" class="gp-item-input" value="${itemDisp}" placeholder="Type to search gear…" autocomplete="off">
            <div class="gp-item-meta">${catPill} ${warn}</div>
            <ul class="gp-item-suggestions" hidden></ul>
          </div>
          <input type="number" class="gp-qty" min="0" step="1" value="${row.qty || 0}">
          <div class="gp-wt-cell">${overrideHtml}</div>
          <span class="gp-total-wt">${totalDisp}</span>
          <select class="gp-who">${whoOptions}</select>
          <input type="text" class="gp-notes" value="${escapeHtml(row.notes || '')}">
          <button class="gp-remove" title="Remove">×</button>
        </div>
      `;
    }

    function renderTable() {
      if (!totals.items.length) {
        return `<div class="gp-empty">No gear yet. Click + add row to start, or visit Gear DB to populate the catalog first.</div>`;
      }
      const headerRow = `
        <div class="gp-row gp-row-header">
          <span>Item</span><span>Qty</span><span>Wt (each)</span>
          <span>Total</span><span>Who</span><span>Notes</span><span></span>
        </div>
      `;
      return `<div class="gp-table">${headerRow}${totals.items.map((r, i) => renderRow(r, i)).join('')}</div>`;
    }

    function renderLegacyBanner() {
      if (!plan.legacy_body) return '';
      return `
        <div class="gp-legacy-banner">
          This trip has a gear table in <code>gear.md</code> that isn't in the new structured format.
          Saving will replace it — copy anything you want to keep first.
          <button class="gp-view-raw" type="button">View raw</button>
        </div>
      `;
    }

    async function fetchCatalog() {
      const r = await fetch('/api/gear');
      if (r.ok) catalog = await r.json();
    }

    function renderAll() {
      sectionEl.innerHTML = `
        <h2 class="section-title">Shared gear</h2>
        ${renderLegacyBanner()}
        ${renderHeader()}
        ${renderTable()}
        <div class="gp-actions">
          <button class="btn gp-add-row">+ add row</button>
          <button class="btn gp-save">Save</button>
          <span class="gp-status"></span>
        </div>
      `;
      wireBanner();
      wireRows();
      wireFooter();
    }

    function wireBanner() {
      const btn = sectionEl.querySelector('.gp-view-raw');
      if (!btn) return;
      btn.addEventListener('click', () => {
        const w = window.open('', '_blank');
        w.document.body.innerText = plan.legacy_body || '';
      });
    }

    function wireRows() {
      // Row interactivity (autocomplete, qty, who, notes, remove, override-weight)
      // is added in Task 15.
    }

    function wireFooter() {
      const addBtn = sectionEl.querySelector('.gp-add-row');
      if (addBtn) addBtn.addEventListener('click', () => {
        plan.items.push({ item_id: '', qty: 1, who: 'shared', notes: '', override_weight_g: null });
        recomputeTotals();
        renderAll();
      });
      // Save flow added in Task 15.
    }

    fetchCatalog().then(() => {
      recomputeTotals();
      renderAll();
    });
  }

  global.GearPlan = { init };
}(window));
```

- [ ] **Step 2: Append gear-plan styles to `app/static/css/trip.css`**

```css
/* Gear plan */
.gp-header { background: var(--surface, #f4f4f5); padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; }
.gp-total { font-size: 1.05em; }
.gp-bywho { color: var(--muted, #52525b); font-size: 0.9em; margin-top: 0.3rem; }
.gp-warn { color: #b45309; font-size: 0.9em; }
.gp-legacy-banner { background: #fff7ed; border: 1px solid #fed7aa; padding: 0.6rem 0.8rem; border-radius: 4px; margin-bottom: 0.8rem; font-size: 0.9em; }
.gp-legacy-banner button { margin-left: 0.5rem; }
.gp-empty { padding: 2rem; text-align: center; color: var(--muted, #71717a); border: 1px dashed var(--border, #d4d4d8); border-radius: 6px; }
.gp-table { border: 1px solid var(--border, #d4d4d8); border-radius: 6px; overflow: hidden; }
.gp-row { display: grid; grid-template-columns: 2.4fr 4rem 7rem 5.5rem 7rem 2fr 1.6rem; gap: 0.4rem; padding: 0.4rem 0.6rem; align-items: center; border-bottom: 1px solid var(--border, #eaeaea); }
.gp-row:last-child { border-bottom: none; }
.gp-row-header { background: #f9fafb; font-weight: 600; font-size: 0.85em; color: var(--muted, #52525b); }
.gp-row.gp-unknown { background: #fef3c7; }
.gp-item-cell { position: relative; display: flex; flex-direction: column; gap: 0.2rem; }
.gp-item-input { padding: 0.3rem; }
.gp-item-meta { display: flex; gap: 0.4rem; align-items: center; font-size: 0.85em; }
.gp-item-suggestions { position: absolute; top: 100%; left: 0; right: 0; z-index: 10; background: white; border: 1px solid var(--border, #d4d4d8); border-radius: 4px; list-style: none; margin: 0; padding: 0; max-height: 14rem; overflow-y: auto; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.gp-item-suggestions li { padding: 0.3rem 0.5rem; cursor: pointer; display: flex; gap: 0.4rem; align-items: center; }
.gp-item-suggestions li:hover { background: var(--hover, #f4f4f5); }
.gp-item-suggestions li.gp-create { color: var(--accent, #2563eb); font-style: italic; border-top: 1px solid var(--border, #eaeaea); }
.gp-qty, .gp-notes, .gp-who { padding: 0.3rem; }
.gp-wt-cell { display: flex; flex-direction: column; gap: 0.2rem; align-items: flex-start; font-size: 0.9em; }
.gp-wt-cell .gp-edit-wt, .gp-wt-cell .gp-revert { font-size: 0.8em; color: var(--accent, #2563eb); text-decoration: none; }
.gp-wt-override { width: 4rem; padding: 0.2rem; }
.gp-total-wt { font-variant-numeric: tabular-nums; }
.gp-remove { background: transparent; border: none; color: #b91c1c; cursor: pointer; font-size: 1.2em; }
.gp-actions { display: flex; gap: 0.6rem; align-items: center; margin-top: 1rem; }
.gp-status { color: var(--muted, #52525b); font-size: 0.9em; }

/* Gear plan modal (create-new-item) */
.gp-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.gp-modal { background: white; padding: 1.5rem; border-radius: 8px; min-width: 22rem; max-width: 30rem; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
.gp-modal h3 { margin: 0 0 0.8rem; }
.gp-modal label { display: block; margin-bottom: 0.6rem; font-weight: 500; font-size: 0.9em; }
.gp-modal input, .gp-modal select { display: block; width: 100%; padding: 0.4rem; margin-top: 0.2rem; }
.gp-modal-actions { display: flex; gap: 0.5rem; margin-top: 1rem; justify-content: flex-end; }
.gp-modal-error { background: #fee2e2; color: #991b1b; padding: 0.5rem; border-radius: 4px; margin-bottom: 0.8rem; }
```

- [ ] **Step 3: Wire `trip.js` to dispatch gear sections**

Modify `app/static/js/trip.js`. Find where sections are rendered — there's already a dispatch for `kind === 'meal-plan'` (added during the food-DB feature). Add a parallel dispatch for `kind === 'gear-plan'`.

Look for the existing meal-plan dispatch (search for `meal-plan` or `MealPlan.init`). Add right next to it:

```javascript
if (section.kind === 'gear-plan') {
  var sectEl = document.createElement('section');
  sectEl.id = section.id;
  sectEl.className = 'trip-section trip-section-gear-plan';
  parent.appendChild(sectEl);   // adjust to existing parent variable
  if (window.GearPlan) window.GearPlan.init(sectEl, slug, section.payload || {});
  return;   // continue/return depending on loop style
}
```

If the dispatch is in `index.js` (Task 12 of the food feature noted dispatch happens in `index.js:renderTrip`), add the parallel branch there instead. The semantics: when a section's `kind === 'gear-plan'`, the SPA hands the rendered section element to `GearPlan.init` instead of setting innerHTML from `section.html`.

- [ ] **Step 4: Smoke test**

Visit `http://127.0.0.1:8000/trips/killarney-2026-05`. The "Shared gear" section should now render as the gear-plan UI:
- Legacy banner appears (the trip's `gear.md` is prose).
- Header shows "Total: 0 g (~0.0 kg)" (no rows yet).
- Empty state with "+ add row" button.
- Click "+ add row" → blank row appears.

Item input not interactive yet (Task 15). No JS errors in console.

- [ ] **Step 5: Verify Python tests still pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add app/static/js/gear-plan.js app/static/css/trip.css app/static/js/trip.js app/static/js/index.js
git commit -m "feat(gear-plan-ui): shell + header + table render"
```

---

## Task 15: Trip-page gear plan — row interactivity, autocomplete, modal, save

**Files:**
- Modify: `app/static/js/gear-plan.js`

- [ ] **Step 1: Replace the stub `wireRows` and `wireFooter` with full implementations**

In `app/static/js/gear-plan.js`, replace the entire `wireRows` and `wireFooter` placeholder bodies with:

```javascript
    function wireRows() {
      // qty input
      sectionEl.querySelectorAll('.gp-qty').forEach(inp => {
        inp.addEventListener('change', (e) => {
          const idx = parseInt(inp.closest('.gp-row').dataset.idx, 10);
          plan.items[idx].qty = parseInt(e.target.value, 10) || 0;
          recomputeTotals();
          renderAll();
        });
      });
      // who select
      sectionEl.querySelectorAll('.gp-who').forEach(sel => {
        sel.addEventListener('change', (e) => {
          const idx = parseInt(sel.closest('.gp-row').dataset.idx, 10);
          plan.items[idx].who = e.target.value;
          recomputeTotals();
          renderAll();
        });
      });
      // notes input
      sectionEl.querySelectorAll('.gp-notes').forEach(inp => {
        inp.addEventListener('change', (e) => {
          const idx = parseInt(inp.closest('.gp-row').dataset.idx, 10);
          plan.items[idx].notes = e.target.value;
        });
      });
      // remove row
      sectionEl.querySelectorAll('.gp-remove').forEach(btn => {
        btn.addEventListener('click', () => {
          const idx = parseInt(btn.closest('.gp-row').dataset.idx, 10);
          plan.items.splice(idx, 1);
          recomputeTotals();
          renderAll();
        });
      });
      // weight-override toggle: enter override mode
      sectionEl.querySelectorAll('.gp-edit-wt').forEach(a => {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          const idx = parseInt(a.closest('.gp-row').dataset.idx, 10);
          // Seed override with the current effective weight (or 0 if unknown).
          const current = totals.items[idx].weight_g_each;
          plan.items[idx].override_weight_g = current === null ? 0 : current;
          recomputeTotals();
          renderAll();
        });
      });
      // weight-override revert
      sectionEl.querySelectorAll('.gp-revert').forEach(a => {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          const idx = parseInt(a.closest('.gp-row').dataset.idx, 10);
          plan.items[idx].override_weight_g = null;
          recomputeTotals();
          renderAll();
        });
      });
      // weight-override input
      sectionEl.querySelectorAll('.gp-wt-override').forEach(inp => {
        inp.addEventListener('change', (e) => {
          const idx = parseInt(inp.closest('.gp-row').dataset.idx, 10);
          const v = parseInt(e.target.value, 10);
          plan.items[idx].override_weight_g = isNaN(v) ? 0 : v;
          recomputeTotals();
          renderAll();
        });
      });
      // item autocomplete
      sectionEl.querySelectorAll('.gp-item-input').forEach(inp => wireAutocomplete(inp));
    }

    function wireAutocomplete(inp) {
      const row = inp.closest('.gp-row');
      const idx = parseInt(row.dataset.idx, 10);
      const sugs = row.querySelector('.gp-item-suggestions');
      function close() { sugs.hidden = true; sugs.innerHTML = ''; }

      inp.addEventListener('input', () => {
        const q = inp.value.toLowerCase().trim();
        const matches = catalog.items
          .filter(it => it.name.toLowerCase().includes(q))
          .slice(0, 8);
        const exact = catalog.items.some(it => it.name.toLowerCase() === q);
        sugs.innerHTML = matches.map(it => {
          const catPill = `<span class="gear-pill" style="background:${pillColor(it.category)}">${escapeHtml(it.category)}</span>`;
          return `<li data-id="${escapeHtml(it.id)}">${escapeHtml(it.name)} ${catPill}</li>`;
        }).join('');
        if (q && !exact) {
          sugs.innerHTML += `<li class="gp-create" data-create="${escapeHtml(inp.value)}">+ Create "${escapeHtml(inp.value)}" as new item</li>`;
        }
        sugs.hidden = sugs.innerHTML === '';
        sugs.querySelectorAll('li[data-id]').forEach(li => {
          li.addEventListener('click', () => {
            plan.items[idx].item_id = li.dataset.id;
            close();
            recomputeTotals();
            renderAll();
          });
        });
        sugs.querySelectorAll('li.gp-create').forEach(li => {
          li.addEventListener('click', () => openCreateItemModal(li.dataset.create, idx));
        });
      });
      inp.addEventListener('blur', () => setTimeout(close, 150));
    }

    function openCreateItemModal(name, rowIdx) {
      const overlay = document.createElement('div');
      overlay.className = 'gp-modal-overlay';
      const catOpts = catalog.categories
        .map(c => `<option value="${c}">${c}</option>`).join('');
      overlay.innerHTML = `
        <div class="gp-modal">
          <h3>Create new gear item</h3>
          <div class="gp-modal-error" hidden></div>
          <label>Name <input type="text" id="gpf-name" value="${escapeHtml(name)}"></label>
          <label>Category <select id="gpf-category">${catOpts}</select></label>
          <label>Weight (g) <input type="number" id="gpf-weight" min="0" step="1" placeholder="(leave blank for unknown)"></label>
          <div class="gp-modal-actions">
            <button class="btn" id="gpf-create">Create + select</button>
            <button class="btn secondary" id="gpf-cancel">Cancel</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      const close = () => overlay.remove();
      overlay.querySelector('#gpf-cancel').addEventListener('click', close);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
      overlay.querySelector('#gpf-create').addEventListener('click', async () => {
        const wRaw = overlay.querySelector('#gpf-weight').value.trim();
        const payload = {
          name: overlay.querySelector('#gpf-name').value.trim(),
          category: overlay.querySelector('#gpf-category').value,
          weight_g: wRaw === '' ? null : (parseInt(wRaw, 10) || 0),
        };
        const r = await fetch('/api/gear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          const err = overlay.querySelector('.gp-modal-error');
          err.textContent = (j.detail && j.detail.error) || `HTTP ${r.status}`;
          err.hidden = false;
          return;
        }
        const { id: newId } = await r.json();
        const cr = await fetch('/api/gear');
        catalog = await cr.json();
        plan.items[rowIdx].item_id = newId;
        close();
        recomputeTotals();
        renderAll();
      });
    }

    function wireFooter() {
      const addBtn = sectionEl.querySelector('.gp-add-row');
      if (addBtn) addBtn.addEventListener('click', () => {
        plan.items.push({ item_id: '', qty: 1, who: 'shared', notes: '', override_weight_g: null });
        recomputeTotals();
        renderAll();
      });
      const saveBtn = sectionEl.querySelector('.gp-save');
      if (!saveBtn) return;
      const status = sectionEl.querySelector('.gp-status');
      saveBtn.addEventListener('click', async () => {
        status.textContent = 'Saving…';
        const cleanItems = plan.items.map(it => ({
          item_id: it.item_id || '',
          qty: parseInt(it.qty, 10) || 0,
          who: it.who || '',
          notes: it.notes || '',
          override_weight_g: it.override_weight_g === null || it.override_weight_g === undefined
                              ? null : (parseInt(it.override_weight_g, 10) || 0),
        }));
        const payload = { items: cleanItems };
        const r = await fetch(`/api/trip/${encodeURIComponent(slug)}/gear-plan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          status.textContent = 'Error: ' + ((j.detail && j.detail.error) || `HTTP ${r.status}`);
          return;
        }
        status.textContent = 'Saved.';
        plan.legacy_body = '';
        renderAll();
        setTimeout(() => { status.textContent = ''; }, 2000);
      });
    }
```

- [ ] **Step 2: Smoke test**

Visit `/trips/killarney-2026-05`. Workflow:
1. "+ add row" → empty row appears.
2. Type "compass" in Item — autocomplete shows "Compass" with the Navigation pill.
3. Click the suggestion — `item_id` populates, weight + total fill in (30 g).
4. Edit qty → totals update.
5. Click `[edit]` next to weight → input appears with the catalog weight as default; change it → total updates.
6. Click `↩ revert` → weight goes back to catalog value.
7. Type a name not in catalog ("Granola Bar") → "+ Create" appears → modal opens → fill in → Create. Row populates with new item.
8. Click Save → toast "Saved." Refresh the page → data persists. `gear.md` on disk has YAML frontmatter + regenerated body.

- [ ] **Step 3: Verify Python tests still pass**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add app/static/js/gear-plan.js
git commit -m "feat(gear-plan-ui): row interactivity, autocomplete, create-item modal, save"
```

---

## Task 16: Trip template + CLAUDE.md docs

**Files:**
- Modify: `templates/trip-template/gear.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the trip-template gear.md**

Replace the entire contents of `templates/trip-template/gear.md` with:

```markdown
---
items: []
---

<!-- generated from frontmatter on save; edit via UI -->
# Shared gear

Open this section in the trip pane to plan shared gear.
```

This makes new trips start with a valid empty gear-plan. The UI scaffolds rows from there.

- [ ] **Step 2: Update CLAUDE.md**

Read the current `CLAUDE.md` to understand its structure before editing.

In the **Project files** bullet list, add:

```
- `gear.json` — git-tracked gear catalog (name, category, optional weight in grams). Edited via the `/gear` page; loaded once and cached in-memory by `app/services/gear.py`.
- `app/services/gear.py` — load/search/upsert/delete + category management; mtime-invalidated cache.
- `app/services/gear_plan.py` — read/write the YAML gear plan in `trips/<slug>/gear.md`; compute weight totals.
- `app/static/js/gear.js` — `/gear` master-detail UI (incl. Manage Categories modal).
- `app/static/js/gear-plan.js` — trip-page gear section.
```

Update the **Source of truth** paragraph to mention `gear.json`:

```
**Source of truth:** markdown files in `trips/<slug>/` for trip *content*. `parks.json` for park metadata. `foods.json` for the foods catalog. `gear.json` for the gear catalog. SQLite (`camping.sqlite3`) holds operational state only — caches and per-user checklist toggles. Disaster-recovery story: git restores trip content + foods/gear catalogs; the DB is rebuildable on demand.
```

In the **Section files (per trip)** table, update the `gear.md` row:

```
| `gear.md`     | YAML frontmatter for structured gear list (item refs from `gear.json`); markdown body regenerated on save. Edit via the in-pane gear planner. |
```

Add a new subsection after the existing "Foods catalog & meal planner" subsection:

```
### Gear catalog & per-trip gear plan

`gear.json` (repo root) is the catalog of camping gear — name, category, and optional weight in grams. Edit via the `/gear` page (master-detail UI: search/filter/categories on the left, edit form on the right; click Manage Categories… to add/rename/delete categories with reassign-to-Other on delete).

Each trip's `gear.md` holds a structured gear plan as YAML frontmatter — items reference the catalog by id. The trip page renders an interactive table with autocomplete, optional per-row weight overrides, per-person + grand-total weight aggregation, and a warning when items have unknown weights. Categories show as coloured pills (deterministic colour per name).

The body of `gear.md` is regenerated on every save; hand-edit only the YAML frontmatter (or, better, edit via the UI).
```

- [ ] **Step 3: Run the full test suite**

```bash
C:/Users/Wolsk/PycharmProjects/camping-planner/venv/Scripts/python.exe -m pytest tests/ -q
```

All tests should pass.

- [ ] **Step 4: Commit**

```bash
git add templates/trip-template/gear.md CLAUDE.md
git commit -m "docs(gear): update trip template + CLAUDE.md for gear DB feature"
```

---

## Self-review checklist

After completing all tasks, run through this:

1. **Spec coverage:**
   - ✅ `gear.json` catalog (Task 1)
   - ✅ Service: load/get/search (Task 2), upsert/delete/find_references (Task 3), categories CRUD (Task 4)
   - ✅ `/api/gear` item routes + Pydantic (Task 5), category routes (Task 6)
   - ✅ `gear_plan.py`: load/scaffold (Task 7), compute_totals (Task 8), render + save (Task 9)
   - ✅ `/api/trip/{slug}/gear-plan` + load_trip_payload integration + EDITABLE_SECTIONS removal (Task 10)
   - ✅ `/gear` page scaffold + sidebar link (Task 11)
   - ✅ `/gear` list/search/filter + detail form (Task 12)
   - ✅ Manage Categories modal (Task 13)
   - ✅ Trip-page gear-plan shell + header + table (Task 14)
   - ✅ Trip-page gear-plan rows + autocomplete + create-item modal + save (Task 15)
   - ✅ Trip template + CLAUDE.md docs (Task 16)
   - ✅ Regression tests for the food-feature bugs (legacy editor, participants in body, route ordering, prefix-match in find_references) — included in Tasks 3, 5, 9, 10
   - ✅ CRLF tolerance in frontmatter regex — included in Task 7

2. **Placeholder scan:** No "TBD"/"TODO"/"implement later" — verify by grep before commit.

3. **Type/name consistency:**
   - `_invalidate_cache()` (matches the rename done during food feature). ✓
   - `gear.json` items use `weight_g` (not `weight`). ✓
   - Trip-side rows use `item_id` (not `gear_id`). ✓
   - `kind` field on `TripSection` extends to `"gear-plan"`. ✓
   - `compute_totals` returns `{items, by_who, trip_g, unknown_count}` consistently in service + JS recompute. ✓
   - `PROTECTED_CATEGORIES = frozenset({"Other"})`. ✓

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-10-gear-db-and-trip-gear.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
