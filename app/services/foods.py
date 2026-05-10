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
