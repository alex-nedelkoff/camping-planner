"""
Build per-day paddle/portage segments and time estimates from a trip's
`nights` frontmatter using cached OpenStreetMap features for Killarney.

Public API:
  build_route(nights, access_point, osm) -> dict
  estimate_minutes(paddle_km, portage_km) -> int
  format_human_time(minutes) -> str
"""
import math
import re

# Conservative pace defaults — see spec for rationale.
PADDLE_KMH = 4.0
PORTAGE_KMH = 2.0
# "2 carries" = walk loaded, walk back empty, walk loaded again =
# 3 traversals of the portage trail per portage segment.
PORTAGE_TRAVERSALS = 3
BUFFER_PCT = 0.15


def _norm_lake_name(name: str) -> str:
    """Normalize a lake name for case-insensitive, punctuation-insensitive matching.

    Examples: "OSA Lake" -> "OSA", "O.S.A. Lake" -> "OSA",
    "Baie Fine" -> "BAIE FINE", "Baie-Fine" -> "BAIEFINE".
    """
    s = name.upper()
    s = re.sub(r"[._,\-]", "", s)
    s = re.sub(r"\s+LAKE$", "", s)
    return s.strip()


def _haversine_km(a: list, b: list) -> float:
    """Distance in km between [lat, lon] points."""
    R = 6371.0
    p1 = math.radians(a[0])
    p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


def _point_in_polygon(point: list, polygon: list) -> bool:
    """Ray-casting point-in-polygon test. Polygon is a closed ring of [lat, lon]."""
    x, y = point[0], point[1]
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside
