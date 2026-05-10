"""Gear catalog service.

The catalog is a single git-tracked JSON file at the repo root. Loaded once
and cached in-memory; reload on mtime change. Mutations rewrite the file
atomically (see Tasks 3 and 4).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from app.config import REPO_ROOT, TRIPS_DIR

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
