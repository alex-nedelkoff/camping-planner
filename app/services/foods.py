"""Foods catalog service.

The catalog is a single git-tracked JSON file at the repo root. Loaded once
and cached in-memory; reload on mtime change. Mutations rewrite the file
atomically (see Task 3).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from app.config import REPO_ROOT, TRIPS_DIR

FOODS_JSON: Path = REPO_ROOT / "foods.json"
_KNOWN_VERSIONS = {1}

_cache: dict | None = None
_cache_mtime: float | None = None


def _invalidate_cache() -> None:
    """Clear the in-memory cache so the next load_catalog() reads from disk.

    In production, mtime invalidation handles this automatically after
    _atomic_write. In tests, monkeypatch.setattr(FOODS_JSON, ...) swaps the
    path entirely, which mtime alone cannot detect — hence this explicit hook.
    """
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


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

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
        # Update existing
        for i, existing in enumerate(foods_list):
            if existing["id"] == food_id:
                foods_list[i] = {"id": food_id, **cleaned}
                break
        else:
            raise KeyError(f"foods: no food with id {food_id!r}")
    else:
        # Create new
        food_id = _next_unique_slug(_slugify(cleaned["name"]), existing_ids)
        foods_list.append({"id": food_id, **cleaned})
    _atomic_write(FOODS_JSON, cat)
    _invalidate_cache()
    return food_id


def delete(food_id: str) -> None:
    """Remove a food by id. Raises KeyError if not found."""
    cat = load_catalog()
    foods_list = cat["foods"]
    for i, f in enumerate(foods_list):
        if f["id"] == food_id:
            del foods_list[i]
            _atomic_write(FOODS_JSON, cat)
            _invalidate_cache()
            return
    raise KeyError(f"foods: no food with id {food_id!r}")


def find_references(food_id: str) -> list[str]:
    """Scan trips/*/food.md frontmatter for occurrences of food_id."""
    if not TRIPS_DIR.exists():
        return []
    pattern = re.compile(
        r"food_id:\s*['\"]?" + re.escape(food_id) + r"['\"]?(?=[\s,\n]|$)"
    )
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
