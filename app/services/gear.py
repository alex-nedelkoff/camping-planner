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
