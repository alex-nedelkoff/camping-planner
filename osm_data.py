"""
Fetch and cache OpenStreetMap features for Killarney Provincial Park.

Public API:
  load_killarney_features() -> dict
    Returns {'lakes': [...], 'portages': [...]} from the cached JSON.

  refresh_killarney_cache() -> None
    Hits Overpass and writes osm_killarney_cache.json.

The cache is committed to the repo so collaborators don't need to refetch.
Refresh with `python3 build_trip.py --refresh-osm`.
"""
import json
import math
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).parent / "osm_killarney_cache.json"

# Killarney Provincial Park bounding box (south, west, north, east).
KILLARNEY_BBOX = (45.92, -81.60, 46.12, -81.25)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = """
[out:json][timeout:30];
(
  way["natural"="water"]["name"]({s},{w},{n},{e});
  way["portage"]({s},{w},{n},{e});
  way["canoe"="portage"]({s},{w},{n},{e});
  way["highway"="path"]["name"~"[Pp]ortage"]({s},{w},{n},{e});
);
out geom;
""".strip()


def _haversine_km(a: list, b: list) -> float:
    """Distance in km between [lat, lon] points."""
    lat1, lon1, lat2, lon2 = a[0], a[1], b[0], b[1]
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


def _polygon_centroid(points: list) -> list:
    """Centroid of a closed polygon (averaged vertices, ignoring duplicate close)."""
    pts = points[:-1] if points and points[0] == points[-1] else points
    n = len(pts)
    if n == 0:
        return [0.0, 0.0]
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    return [cx, cy]


def _line_length_km(points: list) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += _haversine_km(points[i - 1], points[i])
    return total


def _is_lake(tags: dict) -> bool:
    return tags.get("natural") == "water" and bool(tags.get("name"))


def _is_portage(tags: dict) -> bool:
    if tags.get("portage"):
        return True
    if tags.get("canoe") == "portage":
        return True
    if tags.get("highway") == "path":
        name = tags.get("name", "")
        if "portage" in name.lower():
            return True
    return False


def _parse_overpass_response(data: dict) -> dict:
    """Convert raw Overpass JSON into our normalized {lakes, portages} shape."""
    lakes = []
    portages = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        geom = el.get("geometry") or []
        points = [[p["lat"], p["lon"]] for p in geom]
        if not points:
            continue

        if _is_lake(tags):
            lakes.append({
                "name": tags["name"],
                "polygon": points,
                "centroid": _polygon_centroid(points),
            })
        elif _is_portage(tags):
            portages.append({
                "name": tags.get("name") or None,
                "line": points,
                "length_km": round(_line_length_km(points), 3),
                "endpoints": [points[0], points[-1]],
            })
    return {"lakes": lakes, "portages": portages}


def refresh_killarney_cache() -> None:
    """Fetch from Overpass and write the cache file. Slow; rate-limit tolerant."""
    s, w, n, e = KILLARNEY_BBOX
    query = OVERPASS_QUERY.format(s=s, w=w, n=n, e=e)
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=60)
    resp.raise_for_status()
    parsed = _parse_overpass_response(resp.json())
    CACHE_PATH.write_text(json.dumps(parsed, indent=2))
    print(f"Wrote {len(parsed['lakes'])} lakes, {len(parsed['portages'])} "
          f"portages to {CACHE_PATH}")


def load_killarney_features() -> dict:
    """Read the cached features. Raises FileNotFoundError if cache is missing."""
    if not CACHE_PATH.exists():
        raise FileNotFoundError(
            f"{CACHE_PATH}: cache missing. "
            "Run `python3 build_trip.py --refresh-osm <trip-dir>` to populate."
        )
    return json.loads(CACHE_PATH.read_text())


if __name__ == "__main__":
    refresh_killarney_cache()
