"""Cache rendered route HTML + computed distances per trip (in-memory).

Key: (trip_slug, sha256(routes payload)). Routes come from the trip repo.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable, Optional

from app.services import cache

CACHE_TABLE = "route_cache"
DEFAULT_TTL = 60 * 60 * 24 * 30  # 30 days — invalidated by content hash anyway


def _hash_routes(routes_payload) -> str:
    if not routes_payload:
        return "no-routes"
    blob = json.dumps(routes_payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def get_route_render(slug: str, provider: Optional[Callable] = None) -> dict:
    """Return {html, distance_km, ...} for this trip's routes, cached."""
    from app.services import trip_repo
    routes_payload = trip_repo.get_repo().get_routes(slug) or []
    key = (slug, _hash_routes(routes_payload))
    cached = cache.get(CACHE_TABLE, key, DEFAULT_TTL)
    if cached is not None:
        return cached

    if provider is None:
        from app.services import route_provider
        provider = route_provider.render

    payload = provider(routes_payload, slug)
    cache.set(CACHE_TABLE, key, payload)
    return payload


def invalidate(slug: str) -> None:
    """Best-effort invalidation. Drops all cache rows for this trip."""
    cache.drop_prefix(CACHE_TABLE, (slug,))
