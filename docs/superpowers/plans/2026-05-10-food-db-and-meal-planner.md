# Food DB & Per-Trip Meal Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a git-tracked foods catalog (`foods.json`), a per-trip structured meal planner stored as YAML frontmatter in `food.md`, a `/foods` master-detail UI for catalog management, and a trip-page meal-planner UI with calorie totals against an activity-level target.

**Architecture:** Foods catalog is a single git-tracked JSON file (same pattern as `parks.json`), loaded once and cached in-memory with mtime invalidation. Per-trip meal plans live as YAML frontmatter in `trips/<slug>/food.md`; the markdown body is regenerated on every save. SQLite remains operational-only (caches + checklist). Two new SPA pages (`/foods` master-detail; trip-page food section overhauled) communicate via FastAPI JSON routes.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, PyYAML (already in `requirements.txt`), Jinja2, vanilla JS (no framework — matches existing SPA), pytest.

**Reference spec:** `docs/superpowers/specs/2026-05-10-food-db-and-meal-planner-design.md`

---

## File structure

**Created:**
- `foods.json` — repo root, git-tracked catalog seed
- `app/services/foods.py` — load/search/upsert/delete; in-memory cache
- `app/services/meal_plan.py` — frontmatter I/O, compute totals, render md body
- `app/routes/foods.py` — `/api/foods` CRUD + `/api/trip/{slug}/meals`
- `app/static/css/foods.css` — `/foods` page styles
- `app/static/js/foods.js` — `/foods` master-detail UI
- `app/static/js/meal-plan.js` — trip-page meal-planner section
- `tests/test_foods_service.py`
- `tests/test_meal_plan_service.py`
- `tests/test_foods_routes.py`
- `tests/test_meal_plan_routes.py`

**Modified:**
- `app/main.py` — register `foods` router
- `app/routes/pages.py` — add `/foods` route
- `app/templates/index.html` — sidebar "Foods" link, foods.css/foods.js includes
- `app/services/trips.py` — `load_trip_payload` marks food section with `kind: "meal-plan"` and includes the meal-plan payload
- `app/models.py` — Pydantic schemas for foods + meals
- `app/static/js/trip.js` — dispatch food section to `meal-plan.js`
- `app/static/css/trip.css` — meal-planner section styles
- `templates/trip-template/food.md` — empty-frontmatter template
- `CLAUDE.md` — document the new feature

---

## Task 1: Seed `foods.json`

**Files:**
- Create: `foods.json`

- [ ] **Step 1: Create the seed catalog**

Create `foods.json` at the repo root:

```json
{
  "version": 1,
  "categories": ["meal", "snack", "drink", "condiment", "other"],
  "foods": [
    {"id": "mountain-house-lasagna", "name": "Mountain House Lasagna with Meat Sauce", "category": "meal", "kcal_per_serving": 570, "serving_size": "1 pouch (113 g)", "url": "https://mountainhouse.com/products/lasagna-with-meat-sauce"},
    {"id": "mountain-house-beef-stew", "name": "Mountain House Beef Stew", "category": "meal", "kcal_per_serving": 540, "serving_size": "1 pouch (110 g)", "url": null},
    {"id": "backpackers-pantry-pad-thai", "name": "Backpacker's Pantry Pad Thai", "category": "meal", "kcal_per_serving": 670, "serving_size": "1 pouch (170 g)", "url": null},
    {"id": "instant-mash", "name": "Instant mashed potatoes", "category": "meal", "kcal_per_serving": 160, "serving_size": "1/2 cup dry (~30 g)", "url": null},
    {"id": "instant-oatmeal-pkt", "name": "Instant oatmeal packet", "category": "meal", "kcal_per_serving": 120, "serving_size": "1 packet (43 g)", "url": null},
    {"id": "instant-rice", "name": "Instant rice (cup)", "category": "meal", "kcal_per_serving": 200, "serving_size": "1 cup dry (~50 g)", "url": null},
    {"id": "clif-bar-chocolate-chip", "name": "Clif Bar — Chocolate Chip", "category": "snack", "kcal_per_serving": 250, "serving_size": "1 bar (68 g)", "url": null},
    {"id": "gorp", "name": "GORP (trail mix)", "category": "snack", "kcal_per_serving": 280, "serving_size": "1/2 cup (~50 g)", "url": null},
    {"id": "peanut-butter-single", "name": "Peanut butter (single-serve)", "category": "snack", "kcal_per_serving": 190, "serving_size": "1 packet (32 g)", "url": null},
    {"id": "tuna-pouch", "name": "Tuna pouch", "category": "snack", "kcal_per_serving": 110, "serving_size": "1 pouch (74 g)", "url": null},
    {"id": "canned-chicken", "name": "Canned chicken", "category": "snack", "kcal_per_serving": 120, "serving_size": "1/2 can (~60 g)", "url": null},
    {"id": "instant-coffee-pkt", "name": "Instant coffee packet", "category": "drink", "kcal_per_serving": 5, "serving_size": "1 packet (2 g)", "url": null},
    {"id": "hot-chocolate-pkt", "name": "Hot chocolate packet", "category": "drink", "kcal_per_serving": 110, "serving_size": "1 packet (28 g)", "url": null},
    {"id": "olive-oil-small", "name": "Olive oil (small bottle)", "category": "condiment", "kcal_per_serving": 120, "serving_size": "1 tbsp (14 g)", "url": null}
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add foods.json
git commit -m "feat(foods): seed foods.json catalog"
```

---

## Task 2: `foods` service — load / search / get (read-only)

**Files:**
- Create: `app/services/foods.py`
- Create: `tests/test_foods_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_foods_service.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_foods_service.py -v
```

Expected: ImportError / ModuleNotFoundError for `app.services.foods`.

- [ ] **Step 3: Implement read-only service**

Create `app/services/foods.py`:

```python
"""Foods catalog service.

The catalog is a single git-tracked JSON file at the repo root. Loaded once
and cached in-memory; reload on mtime change. Mutations rewrite the file
atomically (see Task 3).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import REPO_ROOT

FOODS_JSON: Path = REPO_ROOT / "foods.json"
_KNOWN_VERSIONS = {1}

_cache: dict | None = None
_cache_mtime: float | None = None


def _reset_cache_for_tests() -> None:
    """Clear the in-memory cache. Tests call this when swapping FOODS_JSON."""
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None


def load_catalog() -> dict:
    """Return the full catalog. Cached; reloaded if foods.json mtime changes."""
    global _cache, _cache_mtime
    mtime = FOODS_JSON.stat().st_mtime
    if _cache is not None and _cache_mtime == mtime:
        return _cache
    raw = json.loads(FOODS_JSON.read_text(encoding="utf-8"))
    version = raw.get("version")
    if version not in _KNOWN_VERSIONS:
        raise RuntimeError(
            f"foods.json has unknown schema version {version!r}; "
            f"known: {sorted(_KNOWN_VERSIONS)}"
        )
    _cache = raw
    _cache_mtime = mtime
    return _cache


def get(food_id: str) -> dict | None:
    """Return one food by id, or None."""
    for f in load_catalog()["foods"]:
        if f["id"] == food_id:
            return f
    return None


def search(query: str, category: str | None) -> list[dict]:
    """Filter the catalog by case-insensitive name substring + optional category."""
    q = (query or "").strip().lower()
    foods = load_catalog()["foods"]
    if category:
        foods = [f for f in foods if f["category"] == category]
    if q:
        foods = [f for f in foods if q in f["name"].lower()]
    return list(foods)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_foods_service.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/foods.py tests/test_foods_service.py
git commit -m "feat(foods): catalog service load/get/search with mtime cache"
```

---

## Task 3: `foods` service — upsert / delete / find_references

**Files:**
- Modify: `app/services/foods.py`
- Modify: `tests/test_foods_service.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_foods_service.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_foods_service.py -v
```

Expected: AttributeErrors for `foods_svc.upsert`, `foods_svc.delete`, `foods_svc.find_references`.

- [ ] **Step 3: Implement mutations**

Modify `app/services/foods.py` — add to imports and end of file:

```python
import os
import re
import tempfile

from app.config import TRIPS_DIR

_REQUIRED_FIELDS = ("name", "category", "kcal_per_serving", "serving_size")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return s or "food"


def _next_unique_slug(base: str, existing_ids: set[str]) -> str:
    if base not in existing_ids:
        return base
    n = 2
    while f"{base}-{n}" in existing_ids:
        n += 1
    return f"{base}-{n}"


def _validate(food: dict, categories: list[str]) -> None:
    for field in _REQUIRED_FIELDS:
        if field not in food or food[field] in (None, ""):
            raise ValueError(f"foods: missing required field '{field}'")
    if not isinstance(food["name"], str) or not food["name"].strip():
        raise ValueError("foods: name must be a non-empty string")
    if food["category"] not in categories:
        raise ValueError(
            f"foods: category {food['category']!r} not in {categories!r}"
        )
    if not isinstance(food["kcal_per_serving"], int) or food["kcal_per_serving"] < 0:
        raise ValueError("foods: kcal_per_serving must be a non-negative integer")
    if not isinstance(food["serving_size"], str) or not food["serving_size"].strip():
        raise ValueError("foods: serving_size must be a non-empty string")
    url = food.get("url")
    if url not in (None, "") and not (
        isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))
    ):
        raise ValueError("foods: url must start with http:// or https://")


def _atomic_write(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix="foods-", suffix=".json", dir=str(path.parent))
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


def upsert(food: dict) -> str:
    """Create or update a food. Returns the id."""
    cat = load_catalog()
    categories = cat["categories"]
    foods_list = cat["foods"]
    food_id = (food.get("id") or "").strip()
    cleaned = {
        "name": food["name"].strip() if isinstance(food.get("name"), str) else None,
        "category": food.get("category"),
        "kcal_per_serving": food.get("kcal_per_serving"),
        "serving_size": (
            food["serving_size"].strip() if isinstance(food.get("serving_size"), str) else None
        ),
        "url": food.get("url") or None,
    }
    _validate(cleaned, categories)
    existing_ids = {f["id"] for f in foods_list}
    if food_id:
        # Update
        for i, existing in enumerate(foods_list):
            if existing["id"] == food_id:
                foods_list[i] = {"id": food_id, **cleaned}
                break
        else:
            raise KeyError(f"foods: no food with id {food_id!r}")
    else:
        # Create
        food_id = _next_unique_slug(_slugify(cleaned["name"]), existing_ids)
        foods_list.append({"id": food_id, **cleaned})
    _atomic_write(FOODS_JSON, cat)
    _reset_cache_for_tests()
    return food_id


def delete(food_id: str) -> None:
    cat = load_catalog()
    foods_list = cat["foods"]
    for i, f in enumerate(foods_list):
        if f["id"] == food_id:
            del foods_list[i]
            _atomic_write(FOODS_JSON, cat)
            _reset_cache_for_tests()
            return
    raise KeyError(f"foods: no food with id {food_id!r}")


def find_references(food_id: str) -> list[str]:
    """Scan trips/*/food.md frontmatter for occurrences of food_id."""
    if not TRIPS_DIR.exists():
        return []
    pattern = re.compile(r"food_id:\s*['\"]?" + re.escape(food_id) + r"['\"]?")
    refs: list[str] = []
    for trip_dir in sorted(TRIPS_DIR.iterdir()):
        if not trip_dir.is_dir():
            continue
        food_md = trip_dir / "food.md"
        if not food_md.exists():
            continue
        text = food_md.read_text(encoding="utf-8")
        if not text.lstrip().startswith("---"):
            continue
        if pattern.search(text):
            refs.append(trip_dir.name)
    return refs
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_foods_service.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/foods.py tests/test_foods_service.py
git commit -m "feat(foods): catalog mutations + reference scan"
```

---

## Task 4: Pydantic schemas + `/api/foods` routes

**Files:**
- Modify: `app/models.py`
- Create: `app/routes/foods.py`
- Modify: `app/main.py`
- Create: `tests/test_foods_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/test_foods_routes.py`:

```python
"""FastAPI tests for /api/foods CRUD."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import foods as foods_svc


@pytest.fixture
def client(tmp_path, monkeypatch):
    catalog_path = tmp_path / "foods.json"
    catalog_path.write_text(json.dumps({
        "version": 1, "categories": ["meal", "snack"], "foods": [
            {"id": "tuna-pouch", "name": "Tuna pouch", "category": "snack",
             "kcal_per_serving": 110, "serving_size": "1 pouch", "url": None},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(foods_svc, "FOODS_JSON", catalog_path)
    foods_svc._reset_cache_for_tests()

    trips_dir = tmp_path / "trips"
    trips_dir.mkdir()
    monkeypatch.setattr(foods_svc, "TRIPS_DIR", trips_dir)
    monkeypatch.setattr(config, "TRIPS_DIR", trips_dir)

    yield TestClient(app)


def test_get_foods_returns_catalog(client):
    r = client.get("/api/foods")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["categories"] == ["meal", "snack"]
    assert len(body["foods"]) == 1
    assert body["foods"][0]["id"] == "tuna-pouch"


def test_post_foods_creates_food(client):
    r = client.post("/api/foods", json={
        "name": "Snickers Bar", "category": "snack",
        "kcal_per_serving": 250, "serving_size": "1 bar", "url": None,
    })
    assert r.status_code == 200
    assert r.json()["id"] == "snickers-bar"


def test_post_foods_validation_error_returns_400(client):
    r = client.post("/api/foods", json={
        "name": "Bad", "category": "bogus",
        "kcal_per_serving": 0, "serving_size": "1", "url": None,
    })
    assert r.status_code == 400
    assert "category" in r.json()["detail"]["error"]


def test_put_foods_updates_existing(client):
    r = client.put("/api/foods/tuna-pouch", json={
        "name": "Tuna pouch", "category": "snack",
        "kcal_per_serving": 120, "serving_size": "1 pouch", "url": None,
    })
    assert r.status_code == 200
    cat = client.get("/api/foods").json()
    assert cat["foods"][0]["kcal_per_serving"] == 120


def test_put_foods_unknown_id_returns_404(client):
    r = client.put("/api/foods/nope", json={
        "name": "X", "category": "snack",
        "kcal_per_serving": 1, "serving_size": "1", "url": None,
    })
    assert r.status_code == 404


def test_delete_foods_blocks_when_referenced(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: tuna-pouch\n"
        "            servings: 2\n---\n", encoding="utf-8",
    )
    r = client.delete("/api/foods/tuna-pouch")
    assert r.status_code == 409
    assert "killarney-2026-07" in r.json()["detail"]["references"]


def test_delete_foods_force_proceeds(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: tuna-pouch\n"
        "            servings: 2\n---\n", encoding="utf-8",
    )
    r = client.delete("/api/foods/tuna-pouch?force=true")
    assert r.status_code == 200
    cat = client.get("/api/foods").json()
    assert cat["foods"] == []


def test_get_foods_refs(client, tmp_path):
    trip_dir = tmp_path / "trips" / "killarney-2026-07"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(
        "---\ndays:\n  - meals:\n      - items:\n          - food_id: tuna-pouch\n"
        "            servings: 2\n---\n", encoding="utf-8",
    )
    r = client.get("/api/foods/refs/tuna-pouch")
    assert r.status_code == 200
    assert r.json()["references"] == ["killarney-2026-07"]
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_foods_routes.py -v
```

Expected: 404 / route-not-found errors.

- [ ] **Step 3: Add Pydantic schemas**

Append to `app/models.py`:

```python
class FoodIn(BaseModel):
    name: str = Field(min_length=1)
    category: str
    kcal_per_serving: int = Field(ge=0)
    serving_size: str = Field(min_length=1)
    url: str | None = None


class FoodOut(FoodIn):
    id: str


class FoodsCatalogResponse(BaseModel):
    ok: bool = True
    categories: list[str]
    foods: list[FoodOut]


class FoodCreatedResponse(BaseModel):
    ok: bool = True
    id: str


class FoodReferencesResponse(BaseModel):
    ok: bool = True
    references: list[str]
```

- [ ] **Step 4: Implement routes**

Create `app/routes/foods.py`:

```python
"""Foods catalog HTTP routes."""

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    FoodCreatedResponse,
    FoodIn,
    FoodReferencesResponse,
    FoodsCatalogResponse,
    OkResponse,
)
from app.services import foods as foods_svc

router = APIRouter(prefix="/api/foods")


@router.get("", response_model=FoodsCatalogResponse)
def get_catalog():
    cat = foods_svc.load_catalog()
    return FoodsCatalogResponse(categories=cat["categories"], foods=cat["foods"])


@router.post("", response_model=FoodCreatedResponse)
def create_food(food: FoodIn):
    try:
        new_id = foods_svc.upsert(food.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return FoodCreatedResponse(id=new_id)


@router.put("/{food_id}", response_model=OkResponse)
def update_food(food_id: str, food: FoodIn):
    try:
        foods_svc.upsert({"id": food_id, **food.model_dump()})
    except KeyError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "food not found"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@router.delete("/{food_id}", response_model=OkResponse)
def delete_food(food_id: str, force: bool = Query(default=False)):
    if foods_svc.get(food_id) is None:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "food not found"})
    if not force:
        refs = foods_svc.find_references(food_id)
        if refs:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": "food is referenced", "references": refs},
            )
    foods_svc.delete(food_id)
    return OkResponse()


@router.get("/refs/{food_id}", response_model=FoodReferencesResponse)
def food_references(food_id: str):
    return FoodReferencesResponse(references=foods_svc.find_references(food_id))
```

- [ ] **Step 5: Register the router**

Modify `app/main.py` — add the import and include the router:

```python
from app.routes import checklist, foods, identity, pages, parks, trips
```

```python
app.include_router(foods.router)
```

(Add the include line near the other `app.include_router(...)` lines.)

- [ ] **Step 6: Run tests — verify they pass**

```bash
pytest tests/test_foods_routes.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/models.py app/routes/foods.py app/main.py tests/test_foods_routes.py
git commit -m "feat(foods): /api/foods CRUD routes + Pydantic schemas"
```

---

## Task 5: `meal_plan` service — load + activity defaults

**Files:**
- Create: `app/services/meal_plan.py`
- Create: `tests/test_meal_plan_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_meal_plan_service.py`:

```python
"""Tests for the meal-plan service."""

import datetime

import pytest

from app.services import meal_plan as mp


def write_trip_md(trip_dir, frontmatter_yaml: str | None, body: str = "") -> None:
    food_md = trip_dir / "food.md"
    if frontmatter_yaml is None:
        food_md.write_text(body, encoding="utf-8")
    else:
        food_md.write_text(f"---\n{frontmatter_yaml}---\n{body}", encoding="utf-8")
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
    monkeypatch.setattr(mp, "TRIPS_DIR", trips)
    return trips


def test_activity_defaults_table():
    assert mp.ACTIVITY_DEFAULTS["backcountry"] == 4000
    assert mp.ACTIVITY_DEFAULTS["bikepacking"] == 4500
    assert mp.ACTIVITY_DEFAULTS["boat-camping"] == 3500
    assert mp.ACTIVITY_DEFAULTS["car-camping"] == 2500


def test_load_no_frontmatter_returns_empty_plan_with_day_scaffold(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", None, body="Old prose here\n")
    plan = mp.load("killarney-2026-07")
    assert plan["calorie_target"]["activity_level"] == "backcountry"
    assert plan["calorie_target"]["kcal_per_person_per_day"] == 4000
    assert plan["participants"] == ["Tom", "Alex", "Jordan"]
    assert [d["date"] for d in plan["days"]] == [
        "2026-07-10", "2026-07-11", "2026-07-12",
    ]
    assert plan["legacy_body"].strip() == "Old prose here"


def test_load_with_frontmatter_round_trips(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", (
        "calorie_target:\n"
        "  activity_level: bikepacking\n"
        "  kcal_per_person_per_day: 4500\n"
        "days:\n"
        "  - date: 2026-07-10\n"
        "    label: Friday\n"
        "    meals:\n"
        "      - meal: dinner\n"
        "        items:\n"
        "          - food_id: tuna-pouch\n"
        "            servings: 2\n"
        "            who: Tom\n"
        "            note: ''\n"
    ), body="(generated)\n")
    plan = mp.load("killarney-2026-07")
    assert plan["calorie_target"]["activity_level"] == "bikepacking"
    assert plan["days"][0]["meals"][0]["items"][0]["food_id"] == "tuna-pouch"
    assert plan["legacy_body"] == ""


def test_load_unknown_trip_raises(tmp_trips):
    with pytest.raises(FileNotFoundError):
        mp.load("nope")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_meal_plan_service.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement load + defaults**

Create `app/services/meal_plan.py`:

```python
"""Per-trip meal-plan I/O.

The plan lives as YAML frontmatter in `trips/<slug>/food.md`. The body below
the frontmatter is regenerated on every save (see Task 7). When a trip's
food.md has no frontmatter (legacy / fresh trip), `load()` returns an empty
plan scaffolded from the trip dates and exposes the legacy prose under
`legacy_body` so the UI can warn before it overwrites.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import yaml

from app.config import TRIPS_DIR

ACTIVITY_DEFAULTS = {
    "backcountry": 4000,
    "bikepacking": 4500,
    "boat-camping": 3500,
    "car-camping": 2500,
}

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def _trip_dir(slug: str) -> Path:
    d = TRIPS_DIR / slug
    if not d.is_dir():
        raise FileNotFoundError(f"trip not found: {slug}")
    return d


def _read_trip_frontmatter(trip_dir: Path) -> dict:
    """Read the YAML frontmatter from trip.md (start_date, end_date, participants)."""
    text = (trip_dir / "trip.md").read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def _scaffold_days(start: str, end: str) -> list[dict]:
    """Return [{date, label, meals: []}, ...] for every day in the range, inclusive."""
    if not start or not end:
        return []
    s = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    days: list[dict] = []
    cur = s
    while cur <= e:
        days.append({
            "date": cur.isoformat(),
            "label": cur.strftime("%A"),
            "meals": [],
        })
        cur += datetime.timedelta(days=1)
    return days


def _empty_plan(trip_fm: dict) -> dict:
    return {
        "calorie_target": {
            "activity_level": "backcountry",
            "kcal_per_person_per_day": ACTIVITY_DEFAULTS["backcountry"],
        },
        "participants": list(trip_fm.get("participants") or []),
        "days": _scaffold_days(
            str(trip_fm.get("start_date") or ""),
            str(trip_fm.get("end_date") or ""),
        ),
    }


def load(slug: str) -> dict:
    """Return the meal plan for a trip.

    Shape:
        {
          "calorie_target": {"activity_level": str, "kcal_per_person_per_day": int},
          "participants": [str, ...],
          "days": [{"date": "YYYY-MM-DD", "label": str, "meals": [{...}]}, ...],
          "legacy_body": str   # populated only when food.md had no frontmatter
        }
    """
    trip_dir = _trip_dir(slug)
    trip_fm = _read_trip_frontmatter(trip_dir)
    food_md = trip_dir / "food.md"
    raw = food_md.read_text(encoding="utf-8") if food_md.exists() else ""
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        plan = _empty_plan(trip_fm)
        plan["legacy_body"] = raw.strip()
        return plan
    plan_fm = yaml.safe_load(m.group(1)) or {}
    plan = {
        "calorie_target": plan_fm.get("calorie_target") or {
            "activity_level": "backcountry",
            "kcal_per_person_per_day": ACTIVITY_DEFAULTS["backcountry"],
        },
        "participants": list(trip_fm.get("participants") or []),
        "days": plan_fm.get("days") or _scaffold_days(
            str(trip_fm.get("start_date") or ""),
            str(trip_fm.get("end_date") or ""),
        ),
        "legacy_body": "",
    }
    return plan
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_meal_plan_service.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/meal_plan.py tests/test_meal_plan_service.py
git commit -m "feat(meal-plan): load() with frontmatter parse + day scaffold"
```

---

## Task 6: `meal_plan` service — compute_totals

**Files:**
- Modify: `app/services/meal_plan.py`
- Modify: `tests/test_meal_plan_service.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_meal_plan_service.py`:

```python
SAMPLE_CATALOG = {
    "version": 1,
    "categories": ["meal", "snack"],
    "foods": [
        {"id": "tuna-pouch", "name": "Tuna pouch", "category": "snack",
         "kcal_per_serving": 110, "serving_size": "1 pouch", "url": None},
        {"id": "instant-mash", "name": "Instant mashed potatoes", "category": "meal",
         "kcal_per_serving": 160, "serving_size": "1/2 cup dry", "url": None},
    ],
}


SAMPLE_PLAN = {
    "calorie_target": {"activity_level": "backcountry", "kcal_per_person_per_day": 4000},
    "participants": ["Tom", "Alex", "Jordan"],
    "days": [
        {"date": "2026-07-10", "label": "Friday", "meals": [
            {"meal": "dinner", "items": [
                {"food_id": "tuna-pouch", "servings": 4, "who": "shared"},
                {"food_id": "instant-mash", "servings": 6, "who": "shared"},
            ]},
        ]},
        {"date": "2026-07-11", "label": "Saturday", "meals": [
            {"meal": "breakfast", "items": [
                {"food_id": "tuna-pouch", "servings": 3, "who": "Tom"},
            ]},
        ]},
    ],
    "legacy_body": "",
}


def test_compute_totals_per_meal_and_day():
    totals = mp.compute_totals(SAMPLE_PLAN, SAMPLE_CATALOG)
    # Day 0 dinner = 4*110 + 6*160 = 440 + 960 = 1400
    assert totals["days"][0]["meals"][0]["kcal"] == 1400
    assert totals["days"][0]["kcal"] == 1400
    # Day 1 breakfast = 3*110 = 330
    assert totals["days"][1]["kcal"] == 330
    assert totals["trip_kcal"] == 1730


def test_compute_totals_target_and_delta():
    totals = mp.compute_totals(SAMPLE_PLAN, SAMPLE_CATALOG)
    # 2 days × 3 ppl × 4000 = 24,000
    assert totals["target_kcal"] == 24_000
    assert totals["delta_kcal"] == 1730 - 24_000


def test_compute_totals_unknown_food_id_marked_as_none():
    plan = {
        "calorie_target": {"activity_level": "backcountry", "kcal_per_person_per_day": 4000},
        "participants": ["X"],
        "days": [{"date": "2026-07-10", "label": "F", "meals": [
            {"meal": "dinner", "items": [{"food_id": "ghost", "servings": 1, "who": "X"}]},
        ]}],
        "legacy_body": "",
    }
    totals = mp.compute_totals(plan, SAMPLE_CATALOG)
    assert totals["days"][0]["meals"][0]["items"][0]["kcal"] is None
    assert totals["days"][0]["meals"][0]["items"][0]["unknown_food"] is True
    assert totals["days"][0]["meals"][0]["kcal"] == 0
    assert totals["trip_kcal"] == 0
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_meal_plan_service.py -v -k compute_totals
```

Expected: AttributeError on `mp.compute_totals`.

- [ ] **Step 3: Implement compute_totals**

Append to `app/services/meal_plan.py`:

```python
def compute_totals(plan: dict, catalog: dict) -> dict:
    """Compute per-meal / per-day / trip kcal + target + delta.

    Returns a parallel structure: {days: [{...meals: [{...items: [{kcal,
    unknown_food}], kcal}], kcal}], trip_kcal, target_kcal, delta_kcal}.
    """
    by_id = {f["id"]: f for f in catalog.get("foods", [])}
    out_days = []
    trip_kcal = 0
    for day in plan.get("days", []):
        out_meals = []
        day_kcal = 0
        for meal in day.get("meals", []):
            out_items = []
            meal_kcal = 0
            for item in meal.get("items", []):
                food = by_id.get(item.get("food_id"))
                if food is None:
                    out_items.append({**item, "kcal": None, "unknown_food": True})
                    continue
                servings = int(item.get("servings") or 0)
                kcal = servings * int(food["kcal_per_serving"])
                meal_kcal += kcal
                out_items.append({**item, "kcal": kcal, "unknown_food": False})
            out_meals.append({**meal, "items": out_items, "kcal": meal_kcal})
            day_kcal += meal_kcal
        out_days.append({**day, "meals": out_meals, "kcal": day_kcal})
        trip_kcal += day_kcal
    target_kcal = (
        len(plan.get("days", []))
        * len(plan.get("participants") or [])
        * int(plan.get("calorie_target", {}).get("kcal_per_person_per_day") or 0)
    )
    return {
        "days": out_days,
        "trip_kcal": trip_kcal,
        "target_kcal": target_kcal,
        "delta_kcal": trip_kcal - target_kcal,
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_meal_plan_service.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/meal_plan.py tests/test_meal_plan_service.py
git commit -m "feat(meal-plan): compute_totals (per-meal/day/trip + target/delta)"
```

---

## Task 7: `meal_plan` service — render_markdown_body + save

**Files:**
- Modify: `app/services/meal_plan.py`
- Modify: `tests/test_meal_plan_service.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_meal_plan_service.py`:

```python
def test_render_markdown_body_lists_days_and_meals():
    body = mp.render_markdown_body(SAMPLE_PLAN, SAMPLE_CATALOG)
    assert "# Food plan" in body
    assert "Calorie target: **4000 kcal/person/day × 3 people × 2 days = 24,000 kcal**" in body
    assert "## Friday (2026-07-10) — 1400 kcal" in body
    assert "**Dinner**" in body
    assert "Tuna pouch" in body
    assert "Instant mashed potatoes" in body
    # Saturday breakfast
    assert "## Saturday (2026-07-11) — 330 kcal" in body


def test_render_markdown_body_marks_unknown_food():
    plan = {
        "calorie_target": {"activity_level": "backcountry", "kcal_per_person_per_day": 4000},
        "participants": ["X"],
        "days": [{"date": "2026-07-10", "label": "F", "meals": [
            {"meal": "dinner", "items": [{"food_id": "ghost", "servings": 1, "who": "X"}]},
        ]}],
        "legacy_body": "",
    }
    body = mp.render_markdown_body(plan, SAMPLE_CATALOG)
    assert "ghost" in body
    assert "?" in body  # unknown kcal marker


def test_save_writes_frontmatter_and_regenerated_body(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", None)
    plan = {
        "calorie_target": {"activity_level": "bikepacking", "kcal_per_person_per_day": 4500},
        "days": [{"date": "2026-07-10", "label": "Friday", "meals": [
            {"meal": "dinner", "items": [
                {"food_id": "tuna-pouch", "servings": 2, "who": "Tom", "note": ""},
            ]},
        ]}],
    }
    mp.save("killarney-2026-07", plan, catalog=SAMPLE_CATALOG)
    written = (tmp_trips / "killarney-2026-07" / "food.md").read_text(encoding="utf-8")
    assert written.startswith("---\n")
    assert "activity_level: bikepacking" in written
    assert "food_id: tuna-pouch" in written
    assert "<!-- generated from frontmatter on save; edit via UI -->" in written
    assert "# Food plan" in written
    assert "Tuna pouch × 2" in written


def test_save_round_trips_through_load(tmp_trips):
    write_trip_md(tmp_trips / "killarney-2026-07", None)
    plan = {
        "calorie_target": {"activity_level": "boat-camping", "kcal_per_person_per_day": 3500},
        "days": [{"date": "2026-07-10", "label": "Friday", "meals": []}],
    }
    mp.save("killarney-2026-07", plan, catalog=SAMPLE_CATALOG)
    reloaded = mp.load("killarney-2026-07")
    assert reloaded["calorie_target"]["activity_level"] == "boat-camping"
    assert reloaded["days"][0]["date"] == "2026-07-10"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_meal_plan_service.py -v -k "render_markdown or save_"
```

Expected: AttributeError on `mp.render_markdown_body` / `mp.save`.

- [ ] **Step 3: Implement render + save**

Append to `app/services/meal_plan.py`:

```python
import os
import tempfile

_MEAL_TITLE_CASE = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snack": "Snack",
}


def _name_for(food_id: str, by_id: dict) -> str:
    food = by_id.get(food_id)
    return food["name"] if food else f"Unknown ({food_id})"


def render_markdown_body(plan: dict, catalog: dict) -> str:
    """Build the human-readable markdown body from a plan + catalog."""
    by_id = {f["id"]: f for f in catalog.get("foods", [])}
    totals = compute_totals(plan, catalog)
    days = len(plan.get("days") or [])
    people = len(plan.get("participants") or [])
    kcd = int(plan.get("calorie_target", {}).get("kcal_per_person_per_day") or 0)
    target = kcd * people * days

    lines: list[str] = ["# Food plan", ""]
    lines.append(
        f"Calorie target: **{kcd} kcal/person/day × {people} people × "
        f"{days} days = {target:,} kcal**"
    )
    lines.append("")
    for day, day_totals in zip(plan.get("days") or [], totals["days"]):
        lines.append(
            f"## {day.get('label', '')} ({day.get('date', '')}) — "
            f"{day_totals['kcal']} kcal"
        )
        for meal in day_totals["meals"]:
            meal_name = _MEAL_TITLE_CASE.get(meal.get("meal", ""), meal.get("meal", "").title())
            for item in meal["items"]:
                kcal_str = "?" if item.get("kcal") is None else str(item["kcal"])
                who = item.get("who") or "shared"
                note = item.get("note") or ""
                note_suffix = f" — {note}" if note else ""
                lines.append(
                    f"- **{meal_name}** — {_name_for(item['food_id'], by_id)} × "
                    f"{item.get('servings', 0)} ({kcal_str} kcal) — {who}{note_suffix}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix="food-", suffix=".md", dir=str(path.parent))
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
    """Rewrite trips/<slug>/food.md with YAML frontmatter + regenerated body."""
    trip_dir = _trip_dir(slug)
    fm_dump = yaml.safe_dump(
        {
            "calorie_target": plan.get("calorie_target") or {
                "activity_level": "backcountry",
                "kcal_per_person_per_day": ACTIVITY_DEFAULTS["backcountry"],
            },
            "days": plan.get("days") or [],
        },
        sort_keys=False,
        allow_unicode=True,
    )
    body = render_markdown_body(plan, catalog)
    text = (
        "---\n"
        f"{fm_dump}"
        "---\n\n"
        "<!-- generated from frontmatter on save; edit via UI -->\n"
        f"{body}"
    )
    _atomic_write(trip_dir / "food.md", text)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_meal_plan_service.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/meal_plan.py tests/test_meal_plan_service.py
git commit -m "feat(meal-plan): render_markdown_body + atomic save"
```

---

## Task 8: `/api/trip/{slug}/meals` routes + load_trip_payload integration

**Files:**
- Modify: `app/models.py`
- Modify: `app/routes/foods.py`
- Modify: `app/services/trips.py`
- Create: `tests/test_meal_plan_routes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_meal_plan_routes.py`:

```python
"""End-to-end tests for the meal-plan routes and trip-payload integration."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, foods as foods_svc, meal_plan as mp_svc, trips as trips_svc

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Catalog
    catalog_path = tmp_path / "foods.json"
    catalog_path.write_text(json.dumps({
        "version": 1, "categories": ["meal", "snack"], "foods": [
            {"id": "tuna-pouch", "name": "Tuna pouch", "category": "snack",
             "kcal_per_serving": 110, "serving_size": "1 pouch", "url": None},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(foods_svc, "FOODS_JSON", catalog_path)
    foods_svc._reset_cache_for_tests()

    # Trips dir from repo
    tmp_trips = tmp_path / "trips"
    if (REPO_ROOT / "trips").exists():
        shutil.copytree(REPO_ROOT / "trips", tmp_trips)
    else:
        tmp_trips.mkdir()
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(mp_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(foods_svc, "TRIPS_DIR", tmp_trips)

    # DB
    tmp_db = tmp_path / "test.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)

    yield TestClient(app)


def test_get_meals_returns_scaffold_for_legacy_trip(client):
    r = client.get("/api/trip/killarney-2026-05/meals")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["plan"]["calorie_target"]["activity_level"] == "backcountry"
    # Killarney trip has 4 days: 2026-05-08..2026-05-11 in the repo fixture
    assert len(body["plan"]["days"]) >= 1
    assert body["totals"]["target_kcal"] >= 0
    # Legacy prose surfaced for the migration banner
    assert body["plan"]["legacy_body"]


def test_post_meals_saves_and_round_trips(client):
    payload = {
        "calorie_target": {"activity_level": "backcountry", "kcal_per_person_per_day": 4000},
        "days": [{"date": "2026-05-08", "label": "Friday", "meals": [
            {"meal": "dinner", "items": [
                {"food_id": "tuna-pouch", "servings": 2, "who": "shared", "note": ""},
            ]},
        ]}],
    }
    r = client.post("/api/trip/killarney-2026-05/meals", json=payload)
    assert r.status_code == 200
    r2 = client.get("/api/trip/killarney-2026-05/meals")
    plan = r2.json()["plan"]
    assert plan["legacy_body"] == ""
    assert plan["days"][0]["meals"][0]["items"][0]["food_id"] == "tuna-pouch"


def test_trip_payload_marks_food_section_as_meal_plan(client):
    r = client.get("/api/trip/killarney-2026-05")
    assert r.status_code == 200
    body = r.json()
    food_section = next(s for s in body["sections"] if s["id"] == "food")
    assert food_section["kind"] == "meal-plan"
```

- [ ] **Step 2: Add Pydantic models**

Append to `app/models.py`:

```python
class MealItem(BaseModel):
    food_id: str
    servings: int = Field(ge=0)
    who: str = ""
    note: str = ""


class MealEntry(BaseModel):
    meal: str
    items: list[MealItem] = Field(default_factory=list)


class DayPlan(BaseModel):
    date: str
    label: str = ""
    meals: list[MealEntry] = Field(default_factory=list)


class CalorieTarget(BaseModel):
    activity_level: str
    kcal_per_person_per_day: int = Field(ge=0)


class MealPlanIn(BaseModel):
    calorie_target: CalorieTarget
    days: list[DayPlan] = Field(default_factory=list)


class MealPlanOut(BaseModel):
    ok: bool = True
    plan: dict
    totals: dict
```

Also extend `TripSection` to allow a `kind`:

```python
class TripSection(BaseModel):
    id: str
    title: str
    html: str
    editable: bool
    kind: str = "html"     # "html" (default) or "meal-plan"
    payload: dict | None = None  # populated when kind == "meal-plan"
```

- [ ] **Step 3: Add meal-plan routes (in foods.py for proximity)**

Append to `app/routes/foods.py`:

```python
from fastapi import HTTPException
from app.models import MealPlanIn, MealPlanOut
from app.services import meal_plan as mp_svc

trip_meals_router = APIRouter(prefix="/api/trip")


@trip_meals_router.get("/{slug}/meals", response_model=MealPlanOut)
def get_meals(slug: str):
    try:
        plan = mp_svc.load(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "trip not found"})
    catalog = foods_svc.load_catalog()
    totals = mp_svc.compute_totals(plan, catalog)
    return MealPlanOut(plan=plan, totals=totals)


@trip_meals_router.post("/{slug}/meals", response_model=OkResponse)
def save_meals(slug: str, body: MealPlanIn):
    try:
        catalog = foods_svc.load_catalog()
        mp_svc.save(slug, body.model_dump(), catalog=catalog)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "trip not found"})
    return OkResponse()
```

Register the new router in `app/main.py`:

```python
app.include_router(foods.router)
app.include_router(foods.trip_meals_router)
```

- [ ] **Step 4: Mark food section in trip payload**

Modify `app/services/trips.py` — replace the section-building loop at the end of `load_trip_payload` (lines roughly 397-403):

```python
    # Build out other editable sections, marking food specially so the SPA can
    # hand it off to the meal-plan UI instead of rendering raw HTML.
    from app.services import foods as foods_svc
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
                "editable": True,
                "kind": "meal-plan",
                "html": "",
                "payload": {"plan": plan, "totals": totals},
            })
        else:
            sections.append({
                "id": section_id,
                "title": section_id.capitalize(),
                "editable": True,
                "kind": "html",
                "html": build_trip.render_section(trip[section_id], section_id),
                "payload": None,
            })
```

Also update earlier `sections.append(...)` blocks in this function to include `"kind": "html", "payload": None` so the response model is consistent:

```python
    sections.append({
        "id": "intro", "title": "Overview", "editable": True,
        "kind": "html", "payload": None,
        "html": build_trip.render_section(trip["intro"], "intro") if trip["intro"] else "",
    })
    sections.append({
        "id": "itinerary", "title": "Itinerary", "editable": True,
        "kind": "html", "payload": None,
        "html": build_trip.render_section(trip["itinerary"], "itinerary"),
    })
```

(And similarly for the route + weather sections — add `"kind": "html", "payload": None`.)

- [ ] **Step 5: Run tests — verify they pass**

```bash
pytest tests/test_meal_plan_routes.py tests/test_routes.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/routes/foods.py app/main.py app/services/trips.py tests/test_meal_plan_routes.py
git commit -m "feat(meal-plan): /api/trip/{slug}/meals + payload kind=meal-plan"
```

---

## Task 9: SPA `/foods` route + sidebar link + assets included

**Files:**
- Modify: `app/routes/pages.py`
- Modify: `app/templates/index.html`
- Create: `app/static/css/foods.css`
- Create: `app/static/js/foods.js`

- [ ] **Step 1: Add the page route**

Modify `app/routes/pages.py` — add after `availability_page`:

```python
@router.get("/foods", response_class=HTMLResponse)
def foods_page(request: Request):
    return _render_shell(request)
```

- [ ] **Step 2: Add sidebar link + asset includes**

Modify `app/templates/index.html` — in `head_extra`:

```html
<link rel="stylesheet" href="/static/css/foods.css">
<script src="/static/js/foods.js" defer></script>
<script src="/static/js/meal-plan.js" defer></script>
```

In the sidebar nav (after the `Check Availability` button):

```html
<button class="nav-btn" data-route="/foods">Foods DB</button>
```

Add a foods template stub at the end of the templates section in `index.html`:

```html
<template id="tpl-foods">
  <section class="foods-page">
    <header class="foods-header">
      <h2>Foods</h2>
      <div class="foods-toolbar">
        <input type="search" id="foods-search" placeholder="Search foods…">
        <select id="foods-category-filter">
          <option value="">All categories</option>
        </select>
        <button id="foods-add" class="btn">+ Add food</button>
      </div>
    </header>
    <div class="foods-body">
      <ul id="foods-list" class="foods-list"></ul>
      <div id="foods-detail" class="foods-detail"></div>
    </div>
  </section>
</template>
```

- [ ] **Step 3: Stub the assets**

Create `app/static/css/foods.css`:

```css
.foods-page { display: flex; flex-direction: column; gap: 1rem; }
.foods-header { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
.foods-toolbar { display: flex; gap: 0.5rem; align-items: center; }
.foods-toolbar input[type=search] { padding: 0.4rem 0.6rem; min-width: 14rem; }
.foods-toolbar select { padding: 0.4rem; }
.foods-body { display: grid; grid-template-columns: 18rem 1fr; gap: 1rem; min-height: 24rem; }
.foods-list { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border, #d4d4d8); border-radius: 6px; overflow-y: auto; max-height: 70vh; }
.foods-list li { padding: 0.5rem 0.75rem; cursor: pointer; border-bottom: 1px solid var(--border, #eaeaea); }
.foods-list li:hover { background: var(--hover, #f4f4f5); }
.foods-list li.selected { background: var(--accent-light, #dbeafe); font-weight: 600; }
.foods-list .cat-tag { font-size: 0.75em; color: var(--muted, #71717a); margin-left: 0.5rem; }
.foods-detail { border: 1px solid var(--border, #d4d4d8); border-radius: 6px; padding: 1rem; }
.foods-detail label { display: block; margin-bottom: 0.6rem; font-weight: 500; }
.foods-detail input, .foods-detail select { display: block; width: 100%; padding: 0.4rem; margin-top: 0.2rem; }
.foods-detail .url-row { display: flex; gap: 0.5rem; align-items: center; }
.foods-detail .url-row a { white-space: nowrap; }
.foods-detail .actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
.foods-detail .danger { background: #ef4444; color: white; }
.foods-detail .empty { color: var(--muted, #71717a); padding: 2rem; text-align: center; }
.foods-detail .error-banner { background: #fee2e2; color: #991b1b; padding: 0.6rem; border-radius: 4px; margin-bottom: 0.6rem; }
```

Create `app/static/js/foods.js` — minimal stub for now:

```javascript
/* Foods DB page (master-detail). Mounted by index.js when the route is /foods. */
(function (global) {
  'use strict';

  function mount(root) {
    const tpl = document.getElementById('tpl-foods');
    if (!tpl) return;
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    // Detail/list wiring is added in Tasks 10-11.
    document.getElementById('foods-detail').innerHTML =
      '<div class="empty">Select a food on the left, or click "+ Add food".</div>';
  }

  global.FoodsPage = { mount };
}(window));
```

- [ ] **Step 4: Wire `/foods` into the SPA router**

Modify `app/static/js/index.js` — the existing router likely has a switch on `pathname`. Find the route handler block (search for `data-route` or `routeTo`) and add a case for `/foods`:

```javascript
} else if (path === '/foods') {
  if (window.FoodsPage) window.FoodsPage.mount(mainPane);
}
```

(Adjust to match the surrounding routing style; the rest of the routes — `/`, `/new`, `/availability`, `/trips/<slug>` — already exist.)

- [ ] **Step 5: Manual smoke test**

```bash
uvicorn app.main:app --reload --port 8000
```

Visit http://127.0.0.1:8000/foods — should show the empty Foods DB page with sidebar link highlighted.

- [ ] **Step 6: Commit**

```bash
git add app/routes/pages.py app/templates/index.html app/static/css/foods.css app/static/js/foods.js app/static/js/index.js
git commit -m "feat(foods-ui): /foods page scaffold + sidebar link"
```

---

## Task 10: `/foods` page — list + search + filter

**Files:**
- Modify: `app/static/js/foods.js`

- [ ] **Step 1: Implement list rendering and search**

Replace `app/static/js/foods.js` with:

```javascript
/* Foods DB page (master-detail). */
(function (global) {
  'use strict';

  let state = {
    catalog: { categories: [], foods: [] },
    selectedId: null,
    query: '',
    category: '',
    dirty: false,
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function fetchCatalog() {
    const r = await fetch('/api/foods');
    if (!r.ok) throw new Error('failed to load /api/foods');
    return r.json();
  }

  function renderCategoryFilter() {
    const sel = document.getElementById('foods-category-filter');
    sel.innerHTML = '<option value="">All categories</option>'
      + state.catalog.categories.map(c => `<option value="${c}">${c}</option>`).join('');
    sel.value = state.category;
  }

  function filteredFoods() {
    const q = state.query.toLowerCase().trim();
    return state.catalog.foods.filter(f => {
      if (state.category && f.category !== state.category) return false;
      if (q && !f.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderList() {
    const ul = document.getElementById('foods-list');
    const items = filteredFoods();
    if (!items.length) {
      ul.innerHTML = '<li style="cursor:default;color:#999">No matches.</li>';
      return;
    }
    ul.innerHTML = items.map(f =>
      `<li data-id="${escapeHtml(f.id)}"${state.selectedId === f.id ? ' class="selected"' : ''}>`
      + `${escapeHtml(f.name)}<span class="cat-tag">${escapeHtml(f.category)}</span>`
      + `</li>`
    ).join('');
    ul.querySelectorAll('li[data-id]').forEach(li => {
      li.addEventListener('click', () => {
        if (state.dirty && !confirm('Discard unsaved changes?')) return;
        state.selectedId = li.dataset.id;
        state.dirty = false;
        renderList();
        renderDetail();
      });
    });
  }

  function renderDetail() {
    // Implemented in Task 11. For now, just show a placeholder.
    const el = document.getElementById('foods-detail');
    if (!state.selectedId) {
      el.innerHTML = '<div class="empty">Select a food on the left, or click "+ Add food".</div>';
      return;
    }
    const food = state.catalog.foods.find(f => f.id === state.selectedId);
    el.innerHTML = `<pre>${escapeHtml(JSON.stringify(food, null, 2))}</pre>`;
  }

  async function mount(root) {
    const tpl = document.getElementById('tpl-foods');
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    state = { catalog: { categories: [], foods: [] }, selectedId: null, query: '', category: '', dirty: false };
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderDetail();
    document.getElementById('foods-search').addEventListener('input', (e) => {
      state.query = e.target.value;
      renderList();
    });
    document.getElementById('foods-category-filter').addEventListener('change', (e) => {
      state.category = e.target.value;
      renderList();
    });
    document.getElementById('foods-add').addEventListener('click', () => {
      if (state.dirty && !confirm('Discard unsaved changes?')) return;
      state.selectedId = '__new__';
      state.dirty = true;
      renderList();
      renderDetail();
    });
  }

  global.FoodsPage = { mount };
}(window));
```

- [ ] **Step 2: Manual smoke test**

```bash
uvicorn app.main:app --reload --port 8000
```

Visit http://127.0.0.1:8000/foods — list should populate with seed foods. Search filters live; category dropdown filters; clicking a row shows JSON in detail pane.

- [ ] **Step 3: Commit**

```bash
git add app/static/js/foods.js
git commit -m "feat(foods-ui): list + search + category filter"
```

---

## Task 11: `/foods` page — detail form (create / edit / delete)

**Files:**
- Modify: `app/static/js/foods.js`

- [ ] **Step 1: Implement the detail form**

Replace the `renderDetail` function in `app/static/js/foods.js` and add helpers. Replace the entire file contents (now containing the full implementation):

```javascript
/* Foods DB page (master-detail). */
(function (global) {
  'use strict';

  let state = {
    catalog: { categories: [], foods: [] },
    selectedId: null,
    query: '',
    category: '',
    draft: null,        // current edit buffer when a row is selected
    dirty: false,
    error: '',
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function fetchCatalog() {
    const r = await fetch('/api/foods');
    if (!r.ok) throw new Error('failed to load /api/foods');
    return r.json();
  }

  function renderCategoryFilter() {
    const sel = document.getElementById('foods-category-filter');
    sel.innerHTML = '<option value="">All categories</option>'
      + state.catalog.categories.map(c => `<option value="${c}">${c}</option>`).join('');
    sel.value = state.category;
  }

  function filteredFoods() {
    const q = state.query.toLowerCase().trim();
    return state.catalog.foods.filter(f => {
      if (state.category && f.category !== state.category) return false;
      if (q && !f.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderList() {
    const ul = document.getElementById('foods-list');
    const items = filteredFoods();
    if (!items.length) {
      ul.innerHTML = '<li style="cursor:default;color:#999">No matches.</li>';
      return;
    }
    ul.innerHTML = items.map(f =>
      `<li data-id="${escapeHtml(f.id)}"${state.selectedId === f.id ? ' class="selected"' : ''}>`
      + `${escapeHtml(f.name)}<span class="cat-tag">${escapeHtml(f.category)}</span>`
      + `</li>`
    ).join('');
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
      state.draft = { id: '', name: '', category: state.catalog.categories[0] || 'other',
                      kcal_per_serving: 0, serving_size: '', url: '' };
      state.dirty = true;
    } else {
      const food = state.catalog.foods.find(f => f.id === id);
      state.draft = food ? { ...food } : null;
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
    const el = document.getElementById('foods-detail');
    if (!state.draft) {
      el.innerHTML = '<div class="empty">Select a food on the left, or click "+ Add food".</div>';
      return;
    }
    const d = state.draft;
    const isNew = state.selectedId === '__new__';
    const catOpts = state.catalog.categories
      .map(c => `<option value="${c}"${c === d.category ? ' selected' : ''}>${c}</option>`).join('');
    const errBanner = state.error
      ? `<div class="error-banner">${escapeHtml(state.error)}</div>` : '';
    el.innerHTML = `
      ${errBanner}
      <label>Name
        <input type="text" id="fd-name" value="${escapeHtml(d.name)}">
      </label>
      <label>Category
        <select id="fd-category">${catOpts}</select>
      </label>
      <label>kcal per serving
        <input type="number" id="fd-kcal" min="0" step="1" value="${d.kcal_per_serving || 0}">
      </label>
      <label>Serving size
        <input type="text" id="fd-serving" value="${escapeHtml(d.serving_size || '')}">
      </label>
      <label>URL (optional)
        <div class="url-row">
          <input type="url" id="fd-url" value="${escapeHtml(d.url || '')}" placeholder="https://...">
          ${d.url ? `<a href="${escapeHtml(d.url)}" target="_blank" rel="noopener">open ↗</a>` : ''}
        </div>
      </label>
      <div class="actions">
        <button class="btn" id="fd-save">${isNew ? 'Create' : 'Save'}</button>
        ${isNew ? '' : '<button class="btn danger" id="fd-delete">× Delete</button>'}
      </div>
    `;
    document.getElementById('fd-name').addEventListener('input', bindDraftField('name'));
    document.getElementById('fd-category').addEventListener('change', bindDraftField('category'));
    document.getElementById('fd-kcal').addEventListener('input', bindDraftField('kcal_per_serving', 'int'));
    document.getElementById('fd-serving').addEventListener('input', bindDraftField('serving_size'));
    document.getElementById('fd-url').addEventListener('input', bindDraftField('url'));
    document.getElementById('fd-save').addEventListener('click', save);
    if (!isNew) document.getElementById('fd-delete').addEventListener('click', () => del(d.id));
  }

  async function save() {
    state.error = '';
    const d = state.draft;
    const isNew = state.selectedId === '__new__';
    const payload = {
      name: d.name,
      category: d.category,
      kcal_per_serving: d.kcal_per_serving,
      serving_size: d.serving_size,
      url: d.url || null,
    };
    try {
      let res;
      if (isNew) {
        res = await fetch('/api/foods', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch(`/api/foods/${encodeURIComponent(d.id)}`, {
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
    let res = await fetch(`/api/foods/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (res.status === 409) {
      const j = await res.json();
      const refs = (j.detail && j.detail.references) || [];
      const msg = `This food is used by ${refs.length} trip(s):\n  ${refs.join('\n  ')}\n\nDelete anyway?`;
      if (!confirm(msg)) return;
      res = await fetch(`/api/foods/${encodeURIComponent(id)}?force=true`, { method: 'DELETE' });
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
    const tpl = document.getElementById('tpl-foods');
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    state = { catalog: { categories: [], foods: [] }, selectedId: null,
              query: '', category: '', draft: null, dirty: false, error: '' };
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderDetail();
    document.getElementById('foods-search').addEventListener('input', (e) => {
      state.query = e.target.value;
      renderList();
    });
    document.getElementById('foods-category-filter').addEventListener('change', (e) => {
      state.category = e.target.value;
      renderList();
    });
    document.getElementById('foods-add').addEventListener('click', () => {
      if (state.dirty && !confirm('Discard unsaved changes?')) return;
      select('__new__');
    });
  }

  global.FoodsPage = { mount };
}(window));
```

- [ ] **Step 2: Manual smoke test**

```bash
uvicorn app.main:app --reload --port 8000
```

Visit http://127.0.0.1:8000/foods. Verify: create new food, edit existing, delete (with ref check if a trip uses it). Try invalid input (empty name, negative kcal, bad URL) — error banner shows.

- [ ] **Step 3: Commit**

```bash
git add app/static/js/foods.js
git commit -m "feat(foods-ui): detail form (create/edit/delete) + ref-blocked delete"
```

---

## Task 12: Trip-page meal planner — shell, header, day cards (collapsed)

**Files:**
- Create: `app/static/js/meal-plan.js`
- Modify: `app/static/css/trip.css`
- Modify: `app/static/js/trip.js`

- [ ] **Step 1: Create meal-plan.js shell**

Create `app/static/js/meal-plan.js`:

```javascript
/* Trip-page meal planner. Mounted by trip.js when a section has kind=meal-plan. */
(function (global) {
  'use strict';

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const ACTIVITY_DEFAULTS = {
    'backcountry': 4000, 'bikepacking': 4500,
    'boat-camping': 3500, 'car-camping': 2500,
  };

  function init(sectionEl, slug, payload) {
    let plan = (payload && payload.plan) || { calorie_target: { activity_level: 'backcountry', kcal_per_person_per_day: 4000 }, days: [], participants: [], legacy_body: '' };
    let totals = (payload && payload.totals) || { trip_kcal: 0, target_kcal: 0, delta_kcal: 0, days: [] };
    let catalog = { foods: [], categories: [] };

    function recomputeTotals() {
      const byId = Object.fromEntries(catalog.foods.map(f => [f.id, f]));
      const days = plan.days.map(d => {
        const meals = (d.meals || []).map(m => {
          const items = (m.items || []).map(it => {
            const f = byId[it.food_id];
            const kcal = f ? (parseInt(it.servings, 10) || 0) * (f.kcal_per_serving || 0) : null;
            return { ...it, kcal, unknown_food: !f };
          });
          const mk = items.filter(i => i.kcal !== null).reduce((a, b) => a + b.kcal, 0);
          return { ...m, items, kcal: mk };
        });
        const dk = meals.reduce((a, b) => a + b.kcal, 0);
        return { ...d, meals, kcal: dk };
      });
      const trip = days.reduce((a, b) => a + b.kcal, 0);
      const tgt = (plan.days.length || 0) * (plan.participants.length || 0) * (plan.calorie_target.kcal_per_person_per_day || 0);
      totals = { days, trip_kcal: trip, target_kcal: tgt, delta_kcal: trip - tgt };
    }

    function renderHeader() {
      const tgt = totals.target_kcal || 1;
      const pct = Math.round((totals.trip_kcal / tgt) * 100);
      const pctClamped = Math.max(0, Math.min(150, pct));
      const inRange = pct >= 95 && pct <= 110;
      return `
        <div class="mp-header">
          <div class="mp-target-row">
            <label>Activity level
              <select class="mp-activity">
                ${['backcountry','bikepacking','boat-camping','car-camping'].map(k =>
                  `<option value="${k}"${plan.calorie_target.activity_level === k ? ' selected' : ''}>${k}</option>`).join('')}
              </select>
            </label>
            <label>kcal / person / day
              <input type="number" class="mp-kcd" min="0" step="50" value="${plan.calorie_target.kcal_per_person_per_day}">
            </label>
            <span class="mp-summary">
              ${plan.days.length} days × ${plan.participants.length} people ×
              ${plan.calorie_target.kcal_per_person_per_day} = <b>${totals.target_kcal.toLocaleString()} kcal target</b>
            </span>
          </div>
          <div class="mp-progress" data-status="${inRange ? 'ok' : 'warn'}">
            <div class="mp-bar" style="width:${pctClamped}%"></div>
            <span class="mp-progress-label">
              Planned: ${totals.trip_kcal.toLocaleString()} kcal — ${pct}%
              ${totals.delta_kcal >= 0 ? `(surplus ${totals.delta_kcal.toLocaleString()})` : `(short ${Math.abs(totals.delta_kcal).toLocaleString()})`}
            </span>
          </div>
        </div>
      `;
    }

    function renderDayCard(day) {
      // Day cards collapsed by default (`<details>`).
      return `
        <details class="mp-day" data-date="${escapeHtml(day.date)}">
          <summary>
            <span class="mp-day-label">${escapeHtml(day.label || '')} (${escapeHtml(day.date)})</span>
            <span class="mp-day-total">${day.kcal.toLocaleString()} kcal</span>
          </summary>
          <div class="mp-meals" data-date="${escapeHtml(day.date)}">
            ${(day.meals || []).map(m => renderMeal(day.date, m)).join('')}
            <button class="mp-add-meal" data-date="${escapeHtml(day.date)}">+ add meal</button>
          </div>
        </details>
      `;
    }

    function renderMeal(date, meal) {
      // Item rows added in Task 13.
      return `
        <div class="mp-meal" data-meal="${escapeHtml(meal.meal)}">
          <h4>${escapeHtml(meal.meal[0].toUpperCase() + meal.meal.slice(1))}</h4>
          <div class="mp-items"><!-- item rows in Task 13 --></div>
        </div>
      `;
    }

    function renderLegacyBanner() {
      if (!plan.legacy_body) return '';
      return `
        <div class="mp-legacy-banner">
          This trip has notes in <code>food.md</code> that aren't in the new structured format.
          Saving will replace them — copy anything you want to keep first.
          <button class="mp-view-raw" type="button">View raw</button>
        </div>
      `;
    }

    async function fetchCatalog() {
      const r = await fetch('/api/foods');
      if (r.ok) catalog = await r.json();
    }

    function renderAll() {
      sectionEl.innerHTML = `
        <h2 class="section-title">Food</h2>
        ${renderLegacyBanner()}
        ${renderHeader()}
        <div class="mp-days">
          ${totals.days.map(renderDayCard).join('')}
        </div>
        <div class="mp-actions">
          <button class="btn mp-save">Save</button>
          <span class="mp-status"></span>
        </div>
      `;
      wireHeader();
      wireLegacyBanner();
      wireDayChrome();
    }

    function wireHeader() {
      const sel = sectionEl.querySelector('.mp-activity');
      const inp = sectionEl.querySelector('.mp-kcd');
      sel.addEventListener('change', (e) => {
        plan.calorie_target.activity_level = e.target.value;
        plan.calorie_target.kcal_per_person_per_day = ACTIVITY_DEFAULTS[e.target.value] || 4000;
        recomputeTotals();
        renderAll();
      });
      inp.addEventListener('change', (e) => {
        plan.calorie_target.kcal_per_person_per_day = parseInt(e.target.value, 10) || 0;
        recomputeTotals();
        renderAll();
      });
    }

    function wireLegacyBanner() {
      const btn = sectionEl.querySelector('.mp-view-raw');
      if (!btn) return;
      btn.addEventListener('click', () => {
        const w = window.open('', '_blank');
        w.document.body.innerText = plan.legacy_body || '';
      });
    }

    function wireDayChrome() {
      // Item-row + add-meal wiring in Task 13.
    }

    fetchCatalog().then(() => {
      recomputeTotals();
      renderAll();
    });
  }

  global.MealPlan = { init };
}(window));
```

- [ ] **Step 2: Add CSS**

Append to `app/static/css/trip.css`:

```css
/* Meal planner */
.mp-header { background: var(--surface, #f4f4f5); padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; }
.mp-target-row { display: flex; gap: 1rem; align-items: end; flex-wrap: wrap; }
.mp-target-row label { display: flex; flex-direction: column; font-size: 0.85em; gap: 0.2rem; }
.mp-target-row input, .mp-target-row select { padding: 0.3rem; }
.mp-summary { margin-left: auto; font-size: 0.95em; }
.mp-progress { position: relative; height: 1.4rem; background: #e4e4e7; border-radius: 4px; margin-top: 0.6rem; overflow: hidden; }
.mp-progress[data-status=ok] .mp-bar { background: #16a34a; }
.mp-progress[data-status=warn] .mp-bar { background: #f59e0b; }
.mp-bar { height: 100%; transition: width 0.2s; }
.mp-progress-label { position: absolute; left: 0.5rem; top: 0; line-height: 1.4rem; color: #18181b; font-size: 0.85em; }
.mp-days { display: flex; flex-direction: column; gap: 0.5rem; }
.mp-day { border: 1px solid var(--border, #d4d4d8); border-radius: 6px; }
.mp-day summary { padding: 0.6rem 0.8rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
.mp-day summary::-webkit-details-marker { color: var(--muted, #71717a); }
.mp-day-total { font-variant-numeric: tabular-nums; color: var(--muted, #52525b); }
.mp-meals { padding: 0 0.8rem 0.8rem; }
.mp-meal { padding: 0.4rem 0; }
.mp-meal h4 { margin: 0.4rem 0; font-size: 0.95em; }
.mp-add-meal { background: transparent; color: var(--accent, #2563eb); border: 1px dashed var(--accent, #2563eb); padding: 0.3rem 0.6rem; border-radius: 4px; cursor: pointer; }
.mp-actions { display: flex; gap: 0.6rem; align-items: center; margin-top: 1rem; }
.mp-legacy-banner { background: #fff7ed; border: 1px solid #fed7aa; padding: 0.6rem 0.8rem; border-radius: 4px; margin-bottom: 0.8rem; font-size: 0.9em; }
.mp-legacy-banner button { margin-left: 0.5rem; }
```

- [ ] **Step 3: Wire into trip.js**

Modify `app/static/js/trip.js` — find where it iterates trip sections and renders each one. Add a special case before rendering raw HTML. Search for `section.html` usage; somewhere there's a pattern like:

```javascript
sections.forEach(function (section) {
  // ... renders section.html into the page
});
```

Add at the start of that iteration:

```javascript
if (section.kind === 'meal-plan') {
  var sectEl = document.createElement('section');
  sectEl.id = section.id;
  sectEl.className = 'trip-section trip-section-meal-plan';
  parent.appendChild(sectEl);
  if (window.MealPlan) window.MealPlan.init(sectEl, slug, section.payload || {});
  return;
}
// ... existing HTML rendering for other sections
```

(Adjust to the exact loop variable names — the principle is: when `kind==='meal-plan'`, hand the empty section element to `MealPlan.init` instead of setting innerHTML from `section.html`.)

- [ ] **Step 4: Manual smoke test**

```bash
uvicorn app.main:app --reload --port 8000
```

Open a trip with prose-only `food.md` (e.g. `killarney-2026-05`):
- Legacy banner appears.
- Activity/kcal header renders.
- Day cards collapsed by default; expanding shows empty meal area + "+ add meal" button (non-functional yet).
- Save button present (non-functional yet).

- [ ] **Step 5: Commit**

```bash
git add app/static/js/meal-plan.js app/static/css/trip.css app/static/js/trip.js
git commit -m "feat(meal-plan-ui): shell + header + day cards (collapsed)"
```

---

## Task 13: Trip-page meal planner — meal/item rows + autocomplete

**Files:**
- Modify: `app/static/js/meal-plan.js`

- [ ] **Step 1: Implement meal/item editing**

In `app/static/js/meal-plan.js`, replace `renderMeal`, `wireDayChrome` and add helpers. Replace the body of `init` with the version below — the diff is:
- `renderMeal` now renders a row per item.
- `renderItemRow` renders the food autocomplete input + servings + who + kcal + ×.
- `wireDayChrome` wires up the item-row inputs, "+ add item", "+ add meal".

Replace the `renderMeal` function and add new helpers:

```javascript
    function renderMeal(date, meal, mealIdx) {
      return `
        <div class="mp-meal" data-date="${escapeHtml(date)}" data-meal-idx="${mealIdx}">
          <h4>${escapeHtml(meal.meal[0].toUpperCase() + meal.meal.slice(1))}
            <button class="mp-remove-meal" title="Remove this meal">×</button>
          </h4>
          <div class="mp-items">
            ${meal.items.map((it, i) => renderItemRow(date, mealIdx, i, it)).join('')}
          </div>
          <button class="mp-add-item" type="button">+ add item</button>
        </div>
      `;
    }

    function renderItemRow(date, mealIdx, itemIdx, item) {
      const food = catalog.foods.find(f => f.id === item.food_id);
      const display = food ? food.name : (item.food_id || '');
      const kcalDisplay = item.kcal === null || item.kcal === undefined ? '?' : item.kcal;
      const unknownClass = item.unknown_food ? ' mp-unknown' : '';
      const whoOptions = ['shared', ...plan.participants]
        .map(p => `<option value="${escapeHtml(p)}"${item.who === p ? ' selected' : ''}>${escapeHtml(p)}</option>`).join('');
      return `
        <div class="mp-item${unknownClass}" data-date="${escapeHtml(date)}" data-meal-idx="${mealIdx}" data-item-idx="${itemIdx}">
          <div class="mp-food-cell">
            <input type="text" class="mp-food-input" value="${escapeHtml(display)}" placeholder="Type to search foods…" autocomplete="off">
            <ul class="mp-food-suggestions" hidden></ul>
          </div>
          <input type="number" class="mp-servings" min="0" step="1" value="${item.servings || 0}">
          <span class="mp-kcal">${kcalDisplay} kcal</span>
          <select class="mp-who">${whoOptions}</select>
          <button class="mp-remove-item" title="Remove">×</button>
        </div>
      `;
    }
```

Now replace the existing `renderAll` use of `(day.meals || []).map(m => renderMeal(day.date, m))` with one that passes the index — find this line in `renderDayCard`:

```javascript
            ${(day.meals || []).map(m => renderMeal(day.date, m)).join('')}
```

Replace with:

```javascript
            ${(day.meals || []).map((m, i) => renderMeal(day.date, m, i)).join('')}
```

Now replace `wireDayChrome` with a working version:

```javascript
    function wireDayChrome() {
      // + add meal
      sectionEl.querySelectorAll('.mp-add-meal').forEach(btn => {
        btn.addEventListener('click', () => {
          const date = btn.dataset.date;
          const day = plan.days.find(d => d.date === date);
          if (!day) return;
          const choice = prompt('Meal type? (breakfast / lunch / dinner / snack)', 'dinner');
          if (!choice) return;
          day.meals = day.meals || [];
          day.meals.push({ meal: choice, items: [] });
          recomputeTotals();
          renderAll();
        });
      });

      // - remove meal
      sectionEl.querySelectorAll('.mp-remove-meal').forEach(btn => {
        btn.addEventListener('click', () => {
          const mealEl = btn.closest('.mp-meal');
          const date = mealEl.dataset.date;
          const idx = parseInt(mealEl.dataset.mealIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals.splice(idx, 1);
          recomputeTotals();
          renderAll();
        });
      });

      // + add item to meal
      sectionEl.querySelectorAll('.mp-add-item').forEach(btn => {
        btn.addEventListener('click', () => {
          const mealEl = btn.closest('.mp-meal');
          const date = mealEl.dataset.date;
          const idx = parseInt(mealEl.dataset.mealIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals[idx].items = day.meals[idx].items || [];
          day.meals[idx].items.push({ food_id: '', servings: 1, who: 'shared', note: '' });
          recomputeTotals();
          renderAll();
        });
      });

      // remove item
      sectionEl.querySelectorAll('.mp-remove-item').forEach(btn => {
        btn.addEventListener('click', () => {
          const itemEl = btn.closest('.mp-item');
          const date = itemEl.dataset.date;
          const mealIdx = parseInt(itemEl.dataset.mealIdx, 10);
          const itemIdx = parseInt(itemEl.dataset.itemIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals[mealIdx].items.splice(itemIdx, 1);
          recomputeTotals();
          renderAll();
        });
      });

      // servings input
      sectionEl.querySelectorAll('.mp-servings').forEach(inp => {
        inp.addEventListener('change', (e) => {
          const itemEl = inp.closest('.mp-item');
          const date = itemEl.dataset.date;
          const mealIdx = parseInt(itemEl.dataset.mealIdx, 10);
          const itemIdx = parseInt(itemEl.dataset.itemIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals[mealIdx].items[itemIdx].servings = parseInt(e.target.value, 10) || 0;
          recomputeTotals();
          renderAll();
        });
      });

      // who select
      sectionEl.querySelectorAll('.mp-who').forEach(sel => {
        sel.addEventListener('change', (e) => {
          const itemEl = sel.closest('.mp-item');
          const date = itemEl.dataset.date;
          const mealIdx = parseInt(itemEl.dataset.mealIdx, 10);
          const itemIdx = parseInt(itemEl.dataset.itemIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals[mealIdx].items[itemIdx].who = e.target.value;
        });
      });

      // food autocomplete
      sectionEl.querySelectorAll('.mp-food-input').forEach(inp => wireAutocomplete(inp));
    }

    function wireAutocomplete(inp) {
      const itemEl = inp.closest('.mp-item');
      const date = itemEl.dataset.date;
      const mealIdx = parseInt(itemEl.dataset.mealIdx, 10);
      const itemIdx = parseInt(itemEl.dataset.itemIdx, 10);
      const sugs = itemEl.querySelector('.mp-food-suggestions');

      function close() { sugs.hidden = true; sugs.innerHTML = ''; }

      inp.addEventListener('input', () => {
        const q = inp.value.toLowerCase().trim();
        const matches = catalog.foods
          .filter(f => f.name.toLowerCase().includes(q))
          .slice(0, 8);
        const exact = catalog.foods.some(f => f.name.toLowerCase() === q);
        sugs.innerHTML = matches.map(f =>
          `<li data-id="${escapeHtml(f.id)}">${escapeHtml(f.name)} <span class="mp-cat">${escapeHtml(f.category)}</span></li>`
        ).join('');
        if (q && !exact) {
          sugs.innerHTML += `<li class="mp-create" data-create="${escapeHtml(inp.value)}">+ Create "${escapeHtml(inp.value)}" as new food</li>`;
        }
        sugs.hidden = sugs.innerHTML === '';
        sugs.querySelectorAll('li[data-id]').forEach(li => {
          li.addEventListener('click', () => {
            const day = plan.days.find(d => d.date === date);
            day.meals[mealIdx].items[itemIdx].food_id = li.dataset.id;
            close();
            recomputeTotals();
            renderAll();
          });
        });
        sugs.querySelectorAll('li.mp-create').forEach(li => {
          li.addEventListener('click', () => openCreateFoodModal(li.dataset.create, date, mealIdx, itemIdx));
        });
      });
      inp.addEventListener('blur', () => setTimeout(close, 150));
    }

    // openCreateFoodModal added in Task 14.
    function openCreateFoodModal(name, date, mealIdx, itemIdx) {
      alert('Create-food modal added in next task.');
    }
```

- [ ] **Step 2: Add styles for item rows + autocomplete**

Append to `app/static/css/trip.css`:

```css
.mp-item { display: grid; grid-template-columns: 2fr 5rem 5rem 8rem 1.6rem; gap: 0.4rem; align-items: center; padding: 0.3rem 0; }
.mp-item.mp-unknown { background: #fef3c7; }
.mp-food-cell { position: relative; }
.mp-food-input { width: 100%; padding: 0.3rem; }
.mp-food-suggestions { position: absolute; top: 100%; left: 0; right: 0; z-index: 10; background: white;
  border: 1px solid var(--border, #d4d4d8); border-radius: 4px; list-style: none; margin: 0; padding: 0; max-height: 14rem; overflow-y: auto; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.mp-food-suggestions li { padding: 0.3rem 0.5rem; cursor: pointer; }
.mp-food-suggestions li:hover { background: var(--hover, #f4f4f5); }
.mp-food-suggestions li.mp-create { color: var(--accent, #2563eb); font-style: italic; border-top: 1px solid var(--border, #eaeaea); }
.mp-cat { color: var(--muted, #71717a); font-size: 0.85em; }
.mp-servings { padding: 0.3rem; }
.mp-kcal { font-variant-numeric: tabular-nums; color: var(--muted, #52525b); }
.mp-who { padding: 0.3rem; }
.mp-remove-item, .mp-remove-meal { background: transparent; border: none; color: #b91c1c; cursor: pointer; font-size: 1.2em; }
```

- [ ] **Step 3: Manual smoke test**

```bash
uvicorn app.main:app --reload --port 8000
```

Open the killarney trip. Expand a day, "+ add meal" (type "dinner"), "+ add item", type "tuna" → autocomplete appears, click suggestion → kcal updates. Servings input updates totals. Removing an item updates totals.

- [ ] **Step 4: Commit**

```bash
git add app/static/js/meal-plan.js app/static/css/trip.css
git commit -m "feat(meal-plan-ui): meal/item rows + food autocomplete"
```

---

## Task 14: Trip-page meal planner — create-food modal + save

**Files:**
- Modify: `app/static/js/meal-plan.js`
- Modify: `app/static/css/trip.css`

- [ ] **Step 1: Replace `openCreateFoodModal` and add a save handler**

In `app/static/js/meal-plan.js`, replace the stub `openCreateFoodModal` with a working modal, and add a `wireSave()` call inside `renderAll()`:

```javascript
    function openCreateFoodModal(name, date, mealIdx, itemIdx) {
      const overlay = document.createElement('div');
      overlay.className = 'mp-modal-overlay';
      const catOpts = catalog.categories
        .map(c => `<option value="${c}">${c}</option>`).join('');
      overlay.innerHTML = `
        <div class="mp-modal">
          <h3>Create new food</h3>
          <div class="mp-modal-error" hidden></div>
          <label>Name <input type="text" id="mpf-name" value="${escapeHtml(name)}"></label>
          <label>Category <select id="mpf-category">${catOpts}</select></label>
          <label>kcal per serving <input type="number" id="mpf-kcal" min="0" step="1" value="0"></label>
          <label>Serving size <input type="text" id="mpf-serving" placeholder="1 pouch (113 g)"></label>
          <label>URL (optional) <input type="url" id="mpf-url" placeholder="https://..."></label>
          <div class="mp-modal-actions">
            <button class="btn" id="mpf-create">Create + select</button>
            <button class="btn secondary" id="mpf-cancel">Cancel</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      const close = () => overlay.remove();
      overlay.querySelector('#mpf-cancel').addEventListener('click', close);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
      overlay.querySelector('#mpf-create').addEventListener('click', async () => {
        const payload = {
          name: overlay.querySelector('#mpf-name').value.trim(),
          category: overlay.querySelector('#mpf-category').value,
          kcal_per_serving: parseInt(overlay.querySelector('#mpf-kcal').value, 10) || 0,
          serving_size: overlay.querySelector('#mpf-serving').value.trim(),
          url: overlay.querySelector('#mpf-url').value.trim() || null,
        };
        const r = await fetch('/api/foods', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          const err = overlay.querySelector('.mp-modal-error');
          err.textContent = (j.detail && j.detail.error) || `HTTP ${r.status}`;
          err.hidden = false;
          return;
        }
        const { id: newId } = await r.json();
        // Reload catalog, set the item.food_id, recompute, rerender.
        const cr = await fetch('/api/foods');
        catalog = await cr.json();
        const day = plan.days.find(d => d.date === date);
        day.meals[mealIdx].items[itemIdx].food_id = newId;
        close();
        recomputeTotals();
        renderAll();
      });
    }
```

- [ ] **Step 2: Implement save**

Add `wireSave` and call it from `renderAll`:

```javascript
    function wireSave() {
      const btn = sectionEl.querySelector('.mp-save');
      const status = sectionEl.querySelector('.mp-status');
      btn.addEventListener('click', async () => {
        status.textContent = 'Saving…';
        // Strip computed kcal/unknown_food fields before sending
        const cleanDays = plan.days.map(d => ({
          date: d.date, label: d.label || '',
          meals: (d.meals || []).map(m => ({
            meal: m.meal,
            items: (m.items || []).map(it => ({
              food_id: it.food_id || '',
              servings: parseInt(it.servings, 10) || 0,
              who: it.who || '',
              note: it.note || '',
            })),
          })),
        }));
        const payload = {
          calorie_target: plan.calorie_target,
          days: cleanDays,
        };
        const r = await fetch(`/api/trip/${encodeURIComponent(slug)}/meals`, {
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
        // Clear legacy banner state — body has been regenerated.
        plan.legacy_body = '';
        renderAll();
        setTimeout(() => { status.textContent = ''; }, 2000);
      });
    }
```

In `renderAll`, after `wireDayChrome();` add:

```javascript
      wireSave();
```

- [ ] **Step 3: Add modal styles**

Append to `app/static/css/trip.css`:

```css
.mp-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.mp-modal { background: white; padding: 1.5rem; border-radius: 8px; min-width: 22rem; max-width: 30rem; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
.mp-modal h3 { margin: 0 0 0.8rem; }
.mp-modal label { display: block; margin-bottom: 0.6rem; font-weight: 500; font-size: 0.9em; }
.mp-modal input, .mp-modal select { display: block; width: 100%; padding: 0.4rem; margin-top: 0.2rem; }
.mp-modal-actions { display: flex; gap: 0.5rem; margin-top: 1rem; justify-content: flex-end; }
.mp-modal-error { background: #fee2e2; color: #991b1b; padding: 0.5rem; border-radius: 4px; margin-bottom: 0.8rem; }
.mp-status { color: var(--muted, #52525b); font-size: 0.9em; }
```

- [ ] **Step 4: Manual smoke test**

```bash
uvicorn app.main:app --reload --port 8000
```

Open killarney trip → expand day → add meal → add item → type a food name not in catalog → click "+ Create '...'" → modal opens → fill fields → Create. Item row populates with the new food and kcal. Click Save. Refresh page; data persists. `food.md` on disk has YAML frontmatter + regenerated body.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/meal-plan.js app/static/css/trip.css
git commit -m "feat(meal-plan-ui): create-food modal + save flow"
```

---

## Task 15: Update trip template + CLAUDE.md docs

**Files:**
- Modify: `templates/trip-template/food.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the trip-template food.md**

Replace `templates/trip-template/food.md` with empty frontmatter so new trips start with valid structure:

```markdown
---
calorie_target:
  activity_level: backcountry
  kcal_per_person_per_day: 4000
days: []
---

<!-- generated from frontmatter on save; edit via UI -->
# Food plan

Open this section in the trip pane to plan meals.
```

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, under the **Project files** bullet list, add (preserving alphabetical sort within the section):

```
- `foods.json` — git-tracked foods catalog (name, category, kcal/serving, serving size, url). Edited via the `/foods` page; loaded once and cached in-memory by `app/services/foods.py`.
- `app/services/foods.py` — load/search/upsert/delete foods; mtime-invalidated cache.
- `app/services/meal_plan.py` — read/write the YAML meal plan in `trips/<slug>/food.md`; compute calorie totals against an activity-level target.
- `app/static/js/foods.js` — `/foods` master-detail UI.
- `app/static/js/meal-plan.js` — trip-page meal planner section.
```

Under **Source of truth**, change to:

```
**Source of truth:** markdown files in `trips/<slug>/` for trip *content*. `parks.json` for park metadata. `foods.json` for the foods catalog. SQLite (`camping.sqlite3`) holds operational state only — caches and per-user checklist toggles. Disaster-recovery story: git restores trip content + foods catalog; the DB is rebuildable on demand.
```

Under **Trip planning workflow → Section files (per trip)**, update the `food.md` row to:

```
| `food.md`     | YAML frontmatter for structured per-day meal plan; markdown body regenerated on save. Edit via the in-pane meal planner. |
```

After **Route maps (KML/GPX + auto-route)** subsection, add:

```
### Foods catalog & meal planner

`foods.json` (repo root) is the catalog of camping foods. Edit it via the `/foods` page (master-detail UI: search/filter on the left, edit form on the right).

Each trip's `food.md` holds a structured meal plan as YAML frontmatter. The meal planner on the trip page lets you add per-day meals, pick foods from the catalog (autocomplete; create-new opens a modal that updates `foods.json`), and shows live calorie totals against an activity-level target. The four activity levels and their default kcal/person/day:

- backcountry → 4000
- bikepacking → 4500
- boat-camping → 3500
- car-camping → 2500

The body of `food.md` is regenerated on every save; hand-edit only the YAML frontmatter (or, better, edit via the UI).
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add templates/trip-template/food.md CLAUDE.md
git commit -m "docs(food-db): update trip template + CLAUDE.md for meal planner"
```

---

## Self-review checklist

Run through this before handing off:

1. **Spec coverage:**
   - ✅ Foods catalog as `foods.json` (Task 1)
   - ✅ Service: load/get/search (Task 2), upsert/delete/find_references (Task 3)
   - ✅ `/api/foods` CRUD (Task 4) + Pydantic schemas
   - ✅ `meal_plan.py` load + activity defaults (Task 5)
   - ✅ compute_totals (Task 6)
   - ✅ render_markdown_body + atomic save (Task 7)
   - ✅ `/api/trip/{slug}/meals` + load_trip_payload integration (Task 8)
   - ✅ `/foods` page scaffold + sidebar link (Task 9)
   - ✅ Foods list + search + filter (Task 10)
   - ✅ Foods detail form + delete with ref-check (Task 11)
   - ✅ Meal planner shell + header + collapsed day cards (Task 12)
   - ✅ Item rows + autocomplete (Task 13)
   - ✅ Create-food modal + save flow (Task 14)
   - ✅ Trip template + CLAUDE.md (Task 15)

2. **Placeholder scan:** No "TBD"/"TODO"/"implement later" — verified by grep before commit.

3. **Type/name consistency:**
   - `MealItem.who` is a `str`, default `""`. UI sends `who: 'shared'` or a participant name — both strings. ✓
   - `compute_totals` returns `{days, trip_kcal, target_kcal, delta_kcal}` — both server (`render_markdown_body`) and client (`recomputeTotals`) use this shape. ✓
   - `food_id` is the slug everywhere. ✓
   - `kind` field on `TripSection` defaults to `"html"`; food section sets `"meal-plan"`. trip.js dispatches on this. ✓
   - `_reset_cache_for_tests()` is exposed from `foods.py` and called from test fixtures. ✓

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-10-food-db-and-meal-planner.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
