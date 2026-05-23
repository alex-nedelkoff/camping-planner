"""Cache rendered route HTML + computed distances per trip.

Key: (trip_slug, sha256(manual_routes.json bytes)). On cache miss, calls
the provider (which wraps build_trip._render_auto_route / route_engine).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Optional

from app.services import db

CACHE_TABLE = "route_cache"
DEFAULT_TTL = 60 * 60 * 24 * 30  # 30 days — invalidate by content hash anyway


def _hash_file(path: Path) -> str:
    if not path.exists():
        return "no-routes"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def get_route_render(routes_path: Path, trip_slug: str,
                     provider: Optional[Callable] = None) -> dict:
    """Return {html, distance_km, ...} for this trip's routes, cached."""
    h = _hash_file(routes_path)
    key = (trip_slug, h)
    cached = db.cache_get_json(CACHE_TABLE, key, DEFAULT_TTL)
    if cached is not None:
        return cached

    if provider is None:
        from app.services import route_provider
        provider = route_provider.render

    routes_payload = (json.loads(routes_path.read_text())
                       if routes_path.exists() else [])
    payload = provider(routes_payload, trip_slug)
    db.cache_set_json(CACHE_TABLE, key, payload)
    return payload


def invalidate(trip_slug: str) -> None:
    """Best-effort invalidation. Drops all cache rows for this trip."""
    db.cache_drop_prefix(CACHE_TABLE, (trip_slug,))
