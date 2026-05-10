"""Availability lookup — wraps ontario_parks.check_park into a UI-friendly shape.

Results are cached in the SQLite `availability_cache` table for
`AVAILABILITY_CACHE_TTL` seconds. Caching matters here mainly to avoid the
Camis Azure WAF's IP ban window (~30 min after ~15 rapid requests).
"""

import ontario_parks

from app.config import AVAILABILITY_CACHE_TTL
from app.services import db


CACHE_TABLE = "availability_cache"


def _shape(result: dict) -> dict:
    campgrounds: dict[str, dict] = {}
    for cg_id, cg_info in (result.get("campgrounds") or {}).items():
        if not isinstance(cg_info, dict) or "error" in cg_info:
            continue
        name = ontario_parks.resolve_map_name(cg_id)
        campgrounds[name] = {
            "available": cg_info.get("available_count", 0),
            "total": cg_info.get("total_count", 0),
        }
    return {
        "park_name": result.get("park_name"),
        "total_available": result.get("total_available", 0),
        "campgrounds": campgrounds,
    }


def check(park: str, start: str, end: str, *, force_refresh: bool = False) -> dict:
    """Return cached or fresh availability shaped for the UI."""
    key = (park, start, end)
    if not force_refresh:
        cached = db.cache_get(CACHE_TABLE, key, AVAILABILITY_CACHE_TTL)
        if cached is not None:
            cached["cached"] = True
            return cached
    payload = _shape(ontario_parks.check_park(park, start, end))
    db.cache_set(CACHE_TABLE, key, payload)
    payload["cached"] = False
    return payload
