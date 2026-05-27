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
CANVEC_CACHE_PATH = DATA_DIR / "canvec_killarney_lakes.json"
MANUAL_PORTAGES_PATH = DATA_DIR / "manual_portages.json"

# When a GPX portage endpoint falls just outside a CanVec/Jeff lake polygon
# (typically because CanVec is tighter than the original OSM polygon the
# endpoint was located against), extend the endpoint to the polygon's
# nearest edge if within this distance.
PORTAGE_SNAP_TOLERANCE_KM = 0.25

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


def _point_in_ring(p, ring) -> bool:
    """Ray-cast point-in-polygon test. Polygon is a closed ring of [lat, lon]."""
    x, y = p[0], p[1]
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside


def _hav_km(a, b) -> float:
    R = 6371.0
    p1 = math.radians(a[0]); p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0]); dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


def _closest_point_on_segment(p, a, b):
    """Closest point on segment a-b to point p, in lat/lon (planar approx)."""
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    px, py = p[0], p[1]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return [ax, ay]
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return [ax + t * dx, ay + t * dy]


def _snap_to_polygon_ring(point, ring):
    """Nearest point on a closed polygon ring (treated as a polyline).
    Returns (snap_point, distance_km)."""
    if len(ring) < 2:
        return point, float("inf")
    closed = list(ring)
    if closed[0] != closed[-1]:
        closed = closed + [closed[0]]
    best = closed[0]
    best_d = _hav_km(point, closed[0])
    for i in range(len(closed) - 1):
        cp = _closest_point_on_segment(point, closed[i], closed[i + 1])
        d = _hav_km(point, cp)
        if d < best_d:
            best_d = d
            best = cp
    return best, best_d


def _extend_portages_to_lakes(portages: list, lakes: list,
                              tolerance_km: float = PORTAGE_SNAP_TOLERANCE_KM
                              ) -> tuple:
    """For each portage endpoint that falls outside all lake polygons but
    within `tolerance_km` of one, snap the endpoint onto that polygon's
    edge so the rendered portage line reaches the lake.

    Mutates a copy of each portage (originals untouched). Returns
    (extended_portages, count_extended).
    """
    extended = 0
    out = []
    for p in portages:
        new_p = dict(p)
        eps_old = p.get("endpoints") or []
        if len(eps_old) != 2:
            out.append(new_p)
            continue
        eps_new = [list(eps_old[0]), list(eps_old[1])]
        for i in (0, 1):
            ep = eps_new[i]
            # Inside any polygon? Leave alone.
            inside = False
            for l in lakes:
                if _point_in_ring(ep, l.get("polygon") or []):
                    inside = True
                    break
            if inside:
                continue
            # Find nearest polygon edge across all lakes.
            best_snap = None
            best_d = float("inf")
            for l in lakes:
                poly = l.get("polygon") or []
                if len(poly) < 3:
                    continue
                snap, d = _snap_to_polygon_ring(ep, poly)
                if d < best_d:
                    best_d = d
                    best_snap = snap
            if best_snap is not None and best_d <= tolerance_km:
                eps_new[i] = best_snap
                extended += 1
        new_p["endpoints"] = eps_new
        # Keep the line geometry consistent with endpoints (preserve any
        # intermediate vertices if the original line had >2 points).
        old_line = p.get("line") or eps_old
        if len(old_line) <= 2:
            new_p["line"] = [list(eps_new[0]), list(eps_new[1])]
        else:
            new_p["line"] = [list(eps_new[0])] + \
                            [list(v) for v in old_line[1:-1]] + \
                            [list(eps_new[1])]
        out.append(new_p)
    return out, extended


def _load_manual_portages() -> list:
    """Synthetic portages added manually to bridge gaps in the GPX dataset.
    Returns empty list if `data/manual_portages.json` is absent."""
    if not MANUAL_PORTAGES_PATH.exists():
        return []
    data = json.loads(MANUAL_PORTAGES_PATH.read_text(encoding="utf-8"))
    return list(data.get("portages") or [])


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


def _polygon_area_sq_m(polygon: list) -> float:
    """Shoelace area in m², projected at the polygon's mean latitude.
    Good enough for the routing/size-filter use case at this scale."""
    if len(polygon) < 3:
        return 0.0
    R = 6371000.0
    mean_lat = sum(p[0] for p in polygon) / len(polygon)
    cos_lat = math.cos(math.radians(mean_lat))
    s = 0.0
    for i in range(len(polygon)):
        x1 = math.radians(polygon[i][1]) * R * cos_lat
        y1 = math.radians(polygon[i][0]) * R
        nx = polygon[(i + 1) % len(polygon)]
        x2 = math.radians(nx[1]) * R * cos_lat
        y2 = math.radians(nx[0]) * R
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


# CanVec polygons smaller than this are dropped IF they're unnamed.
# At ~5 hectares this corresponds to pond/puddle scale — they pollute the
# portage-endpoint classifier (endpoints inside a tiny CanVec pond instead
# of inside the actual destination lake) and aren't routable on their own.
CANVEC_UNNAMED_MIN_AREA_SQ_M = 50_000


def _merge_same_name_canvec(lakes: list) -> list:
    """Union adjacent same-named CanVec polygons (e.g. Lake Huron is split
    across multiple tile-boundary pieces in CanVec). Uses shapely if
    available; falls back to no-op if not.

    A tiny 1e-5° (~1 m) buffer-then-debuffer bridges sub-meter gaps from
    CanVec's tile boundaries. Unnamed polygons are NOT merged (would
    incorrectly group all unnamed ponds into one mega-polygon).
    """
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
    except ImportError:
        return lakes  # shapely not installed — fall back gracefully

    from collections import defaultdict
    by_name: dict = defaultdict(list)
    others: list = []
    for l in lakes:
        name = (l.get("name") or "").strip()
        if name:
            by_name[name].append(l)
        else:
            others.append(l)

    merged: list = []
    for name, group in by_name.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        # Build shapely polygons (shapely uses (x=lon, y=lat) order).
        polys = []
        for l in group:
            ring = l.get("polygon") or []
            if len(ring) < 3:
                continue
            try:
                p = Polygon([(lon, lat) for lat, lon in ring])
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty:
                    polys.append(p)
            except Exception:
                continue
        if not polys:
            merged.extend(group)
            continue
        # Buffer 1e-5° (~1m) → union → debuffer. Bridges hairline gaps from
        # CanVec tile boundaries without growing the polygon noticeably.
        # Then simplify to keep the vertex count sane for routing's
        # point-in-polygon hot loop. 5e-5° ≈ 5m tolerance is sub-pixel at
        # zoom-13 map rendering and well below GPS precision.
        buffered = [p.buffer(1e-5) for p in polys]
        union = unary_union(buffered)
        if hasattr(union, "buffer"):
            union = union.buffer(-1e-5)
        if hasattr(union, "simplify"):
            union = union.simplify(5e-5, preserve_topology=True)
        if union.is_empty:
            merged.extend(group)
            continue
        if union.geom_type == "Polygon":
            geoms = [union]
        elif union.geom_type == "MultiPolygon":
            geoms = list(union.geoms)
        else:
            merged.extend(group)
            continue
        for sub in geoms:
            ring = [[lat, lon] for lon, lat in sub.exterior.coords]
            lats = [p[0] for p in ring]
            lons = [p[1] for p in ring]
            merged.append({
                "name": name,
                "polygon": ring,
                "centroid": [sum(lats) / len(lats), sum(lons) / len(lons)],
                "source": "canvec",
            })
    return merged + others


def _load_canvec_lakes() -> list:
    """Load CanVec 1:50K waterbody polygons (NRCan hydrography).

    Filters out small unnamed polygons (< 50,000 m² ≈ 5 ha) — they're
    pond-scale features that confuse the portage-endpoint classifier
    without adding routing value. Named polygons are kept regardless of
    size.

    Adjacent same-named polygons are unioned (e.g. Lake Huron's CanVec
    tile pieces) so routing point-in-polygon tests treat them as one
    logical lake and the rendered map shows no internal tile boundaries.

    Returns list of {name, polygon, centroid, source: 'canvec'}.
    """
    if not CANVEC_CACHE_PATH.exists():
        return []
    cv = json.loads(CANVEC_CACHE_PATH.read_text(encoding="utf-8"))
    out = []
    for lake in cv.get("lakes", []):
        polygon = lake.get("polygon") or []
        if not polygon:
            continue
        name = lake.get("name") or ""
        if not name.strip():
            if _polygon_area_sq_m(polygon) < CANVEC_UNNAMED_MIN_AREA_SQ_M:
                continue
        lats = [p[0] for p in polygon]
        lons = [p[1] for p in polygon]
        out.append({
            "name": name,
            "polygon": polygon,
            "centroid": [sum(lats) / len(lats), sum(lons) / len(lons)],
            "source": "canvec",
        })
    return _merge_same_name_canvec(out)


def load_killarney_features() -> dict:
    """Read cached features. Merges multiple sources by precedence.

    Lakes (precedence order):
      1. CanVec 1:50K (when `data/canvec_killarney_lakes.json` is present) —
         government-grade hydrography, ~1500 vertices for Killarney Lake.
         Used as the primary polygon source for routing's point-in-polygon
         tests.
      2. Jeff's KMZ-extracted polygons — supplemental named lakes that
         CanVec may have merged into larger water bodies (e.g., Baie Fine
         is part of Lake Huron in CanVec).
      3. OSM polygons — final fallback, retained because OSM portage
         endpoints were originally located against OSM-shaped polygons.

    Portages: merged from OSM + GPX (GPX canonical via spatial dedup at 200 m).
    Campsites: from `data/killarneyCampsites.gpx` when present (name/lat/lon
    shape); falls back to Jeff's cache; absent on OSM-only loads.
    Paths: from `data/jeffs_canoe_paths.json` (yellow paddle paths extracted
    from Jeff's KMZ); empty list when the file is absent.

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
        # Jeff's lakes prepended so name lookup finds Jeff's first.
        # OSM lakes preserved as fallback for portage endpoint resolution.
        out["lakes"] = list(jeffs_lakes) + out["lakes"]
        out["campsites"] = jeffs.get("campsites", [])

    # CanVec lakes — prepended above Jeff's and OSM so name lookups and
    # point-in-polygon tests prefer the high-resolution polygons. OSM/Jeff
    # remain in the list as fallback for features CanVec might not cover
    # (small unnamed ponds, hardcoded supplements like Baie Fine).
    canvec_lakes = _load_canvec_lakes()
    if canvec_lakes:
        out["lakes"] = canvec_lakes + out["lakes"]

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

    # Manual portages — synthetic straight-line connectors that bridge
    # data gaps (e.g. Pig portage to Baie Fine, which the paddleplanner
    # GPX doesn't cover). Loaded last so they survive any future dedup.
    manual = _load_manual_portages()
    if manual:
        out["portages"] = list(out["portages"]) + list(manual)

    # Extend portage endpoints to nearest lake polygon edge when CanVec's
    # tighter polygons leave them just outside the water (≤PORTAGE_SNAP_
    # TOLERANCE_KM). Otherwise rendered lines visibly stop short of the lake.
    if out["lakes"]:
        out["portages"], _ = _extend_portages_to_lakes(
            out["portages"], out["lakes"])

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
