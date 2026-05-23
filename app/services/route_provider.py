"""Default route renderer: wraps build_trip's route section logic.

Kept thin so route_cache can swap it out in tests.
"""

from __future__ import annotations

from typing import Any

import build_trip


def render(routes_payload: list, trip_slug: str) -> dict[str, Any]:
    """Render routes to an HTML block + summary stats."""
    if not routes_payload:
        return {"html": "", "distance_km": 0, "empty": True}
    parts = []
    total_km = 0.0
    for route in routes_payload:
        block = build_trip._render_auto_route(route)
        parts.append(block)
        total_km += float(route.get("distance_km", 0) or 0)
    return {
        "html": "\n".join(parts),
        "distance_km": round(total_km, 1),
        "empty": False,
    }
