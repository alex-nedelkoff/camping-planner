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

import gpx_loader
import requests

DATA_DIR = Path(__file__).parent / "data"
CACHE_PATH = DATA_DIR / "osm_killarney_cache.json"
JEFFS_CACHE_PATH = DATA_DIR / "jeffs_killarney_cache.json"
PATHS_CACHE_PATH = DATA_DIR / "jeffs_canoe_paths.json"
CAMPSITES_GPX_PATH = DATA_DIR / "killarneyCampsites.gpx"
PORTAGES_GPX_PATH = DATA_DIR / "killarneyPortages.gpx"

# Killarney Provincial Park bounding box (south, west, north, east).
KILLARNEY_BBOX = (45.92, -81.60, 46.12, -81.25)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = """
[out:json][timeout:30];
(
  way["natural"="water"]["name"]({s},{w},{n},{e});
  relation["natural"="water"]["name"]({s},{w},{n},{e});
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


def _first_outer_polygon(members: list) -> list:
    """Return the first 'outer'-role member way's geometry as a list of [lat, lon]."""
    for m in members:
        if m.get("type") != "way":
            continue
        if m.get("role") != "outer":
            continue
        geom = m.get("geometry") or []
        return [[p["lat"], p["lon"]] for p in geom]
    return []


def _parse_overpass_response(data: dict) -> dict:
    """Convert raw Overpass JSON into our normalized {lakes, portages} shape."""
    lakes = []
    portages = []
    for el in data.get("elements", []):
        el_type = el.get("type")
        tags = el.get("tags", {})

        if el_type == "way":
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
        elif el_type == "relation" and _is_lake(tags):
            # Multipolygon water relation. Use the first outer member as the polygon.
            outer_points = _first_outer_polygon(el.get("members") or [])
            if not outer_points:
                continue
            lakes.append({
                "name": tags["name"],
                "polygon": outer_points,
                "centroid": _polygon_centroid(outer_points),
            })

    return {"lakes": lakes, "portages": portages}


def refresh_killarney_cache() -> None:
    """Fetch from Overpass and write the cache file. Slow; rate-limit tolerant."""
    import urllib.parse
    s, w, n, e = KILLARNEY_BBOX
    query = OVERPASS_QUERY.format(s=s, w=w, n=n, e=e)
    # Overpass requires an explicitly URL-encoded body with Content-Type header;
    # passing a plain dict triggers a 406 on some Apache front-ends.
    body = urllib.parse.urlencode({"data": query})
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "camping-planner/1.0 (github.com/alex)",
    }
    resp = requests.post(OVERPASS_URL, data=body, headers=headers, timeout=60)
    resp.raise_for_status()
    parsed = _parse_overpass_response(resp.json())
    CACHE_PATH.write_text(json.dumps(parsed, indent=2))
    print(f"Wrote {len(parsed['lakes'])} lakes, {len(parsed['portages'])} "
          f"portages to {CACHE_PATH}")


def _merge_portages(osm_portages: list, gpx_portages: list,
                    spatial_dedup_m: int = 200) -> list:
    """Merge OSM and GPX portages. GPX is canonical for Killarney; OSM
    portages whose midpoint is within spatial_dedup_m of any GPX portage
    midpoint are dropped as duplicates. OSM portages outside that radius
    (other parks, gaps) are kept.

    Returns the union, with GPX portages first.
    """
    def midpoint(portage):
        ep = portage.get("endpoints") or portage.get("line") or []
        if len(ep) < 2:
            return None
        return [(ep[0][0] + ep[-1][0]) / 2.0, (ep[0][1] + ep[-1][1]) / 2.0]

    gpx_mids = [midpoint(p) for p in gpx_portages]
    gpx_mids = [m for m in gpx_mids if m is not None]
    dedup_km = spatial_dedup_m / 1000.0

    kept_osm = []
    for o in osm_portages:
        om = midpoint(o)
        if om is None:
            kept_osm.append(o)
            continue
        too_close = False
        for gm in gpx_mids:
            # Cheap great-circle approximation at ~46° N: 1 deg lat ≈ 111 km;
            # lon scales by cos(lat). Adequate for the 200m gate.
            dlat = (om[0] - gm[0]) * 111.0
            dlon = (om[1] - gm[1]) * 111.0 * math.cos(math.radians(om[0]))
            if (dlat * dlat + dlon * dlon) ** 0.5 <= dedup_km:
                too_close = True
                break
        if not too_close:
            kept_osm.append(o)
    return list(gpx_portages) + kept_osm


def load_killarney_features() -> dict:
    """Read cached features. Merges Jeff's cache when present.

    Lakes: BOTH Jeff's and OSM polygons are kept. Jeff's are first in the list
    so name lookups (`_find_lake`) return Jeff's centroid (typically more
    accurate). OSM polygons remain so point-in-polygon tests (used by the
    portage classifier) still match against OSM-shaped portage endpoints —
    otherwise OSM portages get dropped because Jeff's tighter polygons don't
    contain the OSM-tagged endpoints.

    Portages: OSM only (Phase 1 doesn't extract portages).
    Campsites: Jeff's only (new top-level key; absent OSM-only loads).

    Raises FileNotFoundError if the OSM cache is missing.
    """
    if not CACHE_PATH.exists():
        raise FileNotFoundError(
            f"{CACHE_PATH}: cache missing. "
            "Run `python3 build_trip.py --refresh-osm <trip-dir>` to populate."
        )
    osm = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    out = {
        "lakes": list(osm.get("lakes", [])),
        "portages": list(osm.get("portages", [])),
        "campsites": [],
    }

    if JEFFS_CACHE_PATH.exists():
        jeffs = json.loads(JEFFS_CACHE_PATH.read_text(encoding="utf-8"))
        jeffs_lakes = jeffs.get("lakes", [])
        # Jeff's lakes prepended → name lookup finds Jeff's first.
        # OSM lakes preserved → portage point-in-polygon still resolves.
        out["lakes"] = list(jeffs_lakes) + out["lakes"]
        out["campsites"] = jeffs.get("campsites", [])

    out["paths"] = []
    if PATHS_CACHE_PATH.exists():
        paths_cache = json.loads(PATHS_CACHE_PATH.read_text(encoding="utf-8"))
        out["paths"] = paths_cache.get("paths", [])

    # GPX campsites — canonical, replaces any existing.
    if CAMPSITES_GPX_PATH.exists():
        out["campsites"] = gpx_loader.load_campsites(CAMPSITES_GPX_PATH)

    # GPX portages — merged with OSM via spatial dedup.
    if PORTAGES_GPX_PATH.exists():
        gpx_portages = gpx_loader.load_portages(PORTAGES_GPX_PATH)
        out["portages"] = _merge_portages(out["portages"], gpx_portages,
                                          spatial_dedup_m=200)

    return out


def find_campsite(name: str, campsites: list):
    """Resolve a trip night's `site: <number>` → campsite dict.

    Case-insensitive string match on the `name` field. Returns None if no
    match. Caller should fall back to existing lake-centroid behavior on None.
    """
    if not name:
        return None
    needle = str(name).lower()
    for cs in campsites or []:
        if str(cs.get("name", "")).lower() == needle:
            return cs
    return None


if __name__ == "__main__":
    refresh_killarney_cache()
