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
from typing import Optional

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


from datetime import datetime


_WEEKDAY_PREFIX = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
                   4: "Fri", 5: "Sat", 6: "Sun"}


def _day_label(date_str: str) -> str:
    """'2026-05-15' -> 'Fri 2026-05-15'. Falls back to raw string if unparseable."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{_WEEKDAY_PREFIX[d.weekday()]} {date_str}"
    except (ValueError, KeyError):
        return date_str


def _find_lake(name: str, lakes: list) -> Optional[dict]:
    """Look up a lake by name (normalized). Returns lake dict or None."""
    target = _norm_lake_name(name)
    for lake in lakes:
        if _norm_lake_name(lake["name"]) == target:
            return lake
    return None


def _classify_portage_endpoints(portage: dict, lakes: list) -> list:
    """Return the lakes (by index) each portage endpoint falls inside.

    Returns [lake_or_None_for_endpoint_0, lake_or_None_for_endpoint_1].
    """
    result = []
    for ep in portage["endpoints"]:
        match = None
        for lake in lakes:
            if _point_in_polygon(ep, lake["polygon"]):
                match = lake
                break
        result.append(match)
    return result


def _find_connecting_portage(lake_a: dict, lake_b: dict, portages: list) -> Optional[dict]:
    """Return a portage whose endpoints fall in lake_a and lake_b (any order)."""
    name_a = lake_a["name"]
    name_b = lake_b["name"]
    for p in portages:
        ends = _classify_portage_endpoints(p, [lake_a, lake_b])
        names_at_ends = {e["name"] if e else None for e in ends}
        if {name_a, name_b}.issubset(names_at_ends):
            return p
    return None


def _segment(day: str, kind: str, frm: str, to: str,
             distance_km: float, geometry: list) -> dict:
    return {
        "day": day,
        "kind": kind,
        "from": frm,
        "to": to,
        "distance_km": round(distance_km, 2),
        "geometry": geometry,
    }


def build_route(nights: list, access_point: str, osm: dict) -> dict:
    """Build per-leg segments + warnings from frontmatter nights + OSM data.

    Each "leg" is the travel between consecutive waypoints. Legs are:
      - Day 1: access_point -> nights[0]
      - Day N: nights[N-1] -> nights[N]
      - Last day: nights[-1] -> access_point

    Returns {"segments": [...], "warnings": [...]}.
    """
    lakes = osm["lakes"]
    portages = osm["portages"]
    segments: list = []
    warnings: list = []

    # Build the ordered list of waypoint dicts: each has {label, location, day_label}.
    waypoints = [{
        "label": access_point,
        "location": access_point,
        "day_label": _day_label(nights[0]["date"]) if nights else "",
    }]
    for night in nights:
        waypoints.append({
            "label": f"{night['location']} (site {night['site']})",
            "location": night["location"],
            "day_label": _day_label(night["date"]),
        })
    # Note: the return leg (nights[-1] -> access_point) is intentionally omitted.
    # Task 5 / callers handle the checkout day separately.

    # Walk leg by leg.
    for i in range(1, len(waypoints)):
        a = waypoints[i - 1]
        b = waypoints[i]
        day_label = b["day_label"]
        lake_a = _find_lake(a["location"], lakes)
        lake_b = _find_lake(b["location"], lakes)

        if lake_a and lake_b and lake_a["name"] == lake_b["name"]:
            # Same lake — straight paddle.
            d_km = _haversine_km(lake_a["centroid"], lake_b["centroid"])
            segments.append(_segment(
                day_label, "paddle", a["label"], b["label"],
                d_km, [lake_a["centroid"], lake_b["centroid"]],
            ))
            continue

        if lake_a and lake_b:
            portage = _find_connecting_portage(lake_a, lake_b, portages)
            if portage:
                ends = _classify_portage_endpoints(portage, [lake_a, lake_b])
                # Ordered entry/exit so entry is in lake_a, exit in lake_b.
                if ends[0] and ends[0]["name"] == lake_a["name"]:
                    entry, exit_ = portage["endpoints"]
                    portage_geom = portage["line"]
                else:
                    exit_, entry = portage["endpoints"]
                    portage_geom = list(reversed(portage["line"]))
                # Paddle in lake_a from centroid to portage entry.
                d1 = _haversine_km(lake_a["centroid"], entry)
                segments.append(_segment(
                    day_label, "paddle", a["label"], f"{lake_a['name']} portage",
                    d1, [lake_a["centroid"], entry],
                ))
                # Portage.
                segments.append(_segment(
                    day_label, "portage", f"{lake_a['name']} portage",
                    f"{lake_b['name']} portage", portage["length_km"],
                    portage_geom,
                ))
                # Paddle in lake_b from portage exit to centroid.
                d2 = _haversine_km(exit_, lake_b["centroid"])
                segments.append(_segment(
                    day_label, "paddle", f"{lake_b['name']} portage", b["label"],
                    d2, [exit_, lake_b["centroid"]],
                ))
                continue

        # No-portage / unmatched-lake fallback: filled in by Task 4.
        # For now, raise so Task 3's tests pass (which only cover happy paths)
        # but failures during Task 4 development are loud.
        raise NotImplementedError(
            f"Cannot route from {a['location']} to {b['location']} "
            "(approximate fallback added in Task 4)"
        )

    return {"segments": segments, "warnings": warnings}
