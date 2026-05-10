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
from fractions import Fraction
from typing import Optional

# Conservative pace defaults — see spec for rationale.
PADDLE_KMH = 4.0
PORTAGE_KMH = 2.0
# "2 carries" = walk loaded, walk back empty, walk loaded again =
# 3 traversals of the portage trail per portage segment.
PORTAGE_TRAVERSALS = 3
BUFFER_PCT = 0.15

# Portage endpoint matching tolerance: if a portage endpoint is not strictly
# inside any lake polygon, fall back to the nearest lake centroid within this
# distance (km).
PORTAGE_TOLERANCE_KM = 0.3

# Maximum number of portage hops to search when pathfinding between lakes.
MAX_PORTAGE_HOPS = 5

# Hardcoded GPS for Killarney's main access points. Used to anchor the
# first/last paddle segments of a trip so the route line starts/ends at the
# real put-in instead of a misleading lake centroid.
KILLARNEY_ACCESS_POINTS = {
    "George Lake": {"gps": [46.0136, -81.4049], "lake": "George Lake"},
    "Bell Lake":   {"gps": [46.0822, -81.2680], "lake": "Bell Lake"},
    "Chikanishing": {"gps": [46.0125, -81.4485], "lake": "Chikanishing River"},
}

# OSM doesn't tag Baie Fine as a separate lake (it's part of Lake Huron /
# North Channel). Hardcode an approximate polygon and centroid so the route
# engine can resolve trips that visit Baie Fine.
LAKE_SUPPLEMENT = [
    {
        "name": "Baie Fine",
        # Rough fjord outline: long diagonal SW-running inlet from The Pool
        # (east end) out toward the North Channel mouth. Approximate, not
        # survey-accurate — the centroid lands mid-fjord where backcountry
        # sites cluster.
        "polygon": [
            [46.020, -81.495],  # NE near Threenarrows
            [46.022, -81.510],  # The Pool
            [46.018, -81.530],
            [46.012, -81.555],
            [46.005, -81.580],
            [46.000, -81.600],  # west mouth
            [46.005, -81.575],  # return south shore
            [46.010, -81.550],
            [46.015, -81.525],
            [46.018, -81.505],
            [46.020, -81.495],  # close
        ],
        "centroid": [46.012, -81.540],
    },
]


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


def _line_inside_polygon(p1: list, p2: list, polygon: list,
                         samples: int = 50) -> bool:
    """True if the line from p1 to p2 stays inside polygon (sampled).

    Sampling density (`samples=50`) is calibrated so a typical Killarney
    paddle leg (a few hundred meters between samples) won't skip past a
    thin peninsula or shoreline crinkle. The polygon passed here should
    be the FULL high-resolution polygon — not a decimated one — so the
    in-water test is accurate.
    """
    for i in range(samples + 1):
        t = i / samples
        lat = p1[0] + t * (p2[0] - p1[0])
        lon = p1[1] + t * (p2[1] - p1[1])
        if not _point_in_polygon([lat, lon], polygon):
            return False
    return True


# Cap polygon vertex count for visibility graph computation. Jeff's
# extracted polygons typically have 80-180 vertices; the visibility graph
# is O(V²) over polygon vertices and each edge does an O(V) line-inside
# test, so working on the raw polygons explodes to minutes per trip.
# Decimating to ≤ this many vertices keeps the geometry good enough for
# routing-around-peninsulas while making the algorithm sub-second.
_PADDLE_MAX_POLYGON_VERTICES = 25


def _decimate_polygon(polygon: list, max_vertices: int) -> list:
    """Stride-decimate a polygon down to at most `max_vertices` vertices.

    Lossy but uniformly so — for visibility-graph paddle routing the rough
    shape is what matters, not sub-vertex precision.
    """
    if len(polygon) <= max_vertices:
        return [list(v) for v in polygon]
    stride = max(1, len(polygon) // max_vertices)
    return [list(polygon[i]) for i in range(0, len(polygon), stride)]


def _polygon_aware_paddle(start: list, end: list, lake: dict) -> list:
    """Return geometry [start, ..., end] for a paddle staying inside `lake`.

    Builds a visibility graph over {start, end, simplified-polygon vertices}.
    An edge exists between two nodes if the straight line between them stays
    inside the (simplified) polygon. Runs Dijkstra to find the shortest path.
    Naturally chains as many intermediate vertices as needed for multi-bend
    / U-shaped / L-shaped lakes.

    Performance: the polygon is stride-decimated to
    `_PADDLE_MAX_POLYGON_VERTICES` vertices before graph construction, which
    keeps the O(V²) visibility check sub-second even for Killarney's
    densely-tessellated lake polygons (typically 80-180 vertices raw).

    Falls back to the straight line if `lake` is missing a polygon, or to
    the lake centroid as a last-resort midpoint if no graph path exists.
    """
    if not lake or not lake.get("polygon"):
        return [start, end]
    # FULL polygon for line-in-water tests (accuracy).
    full_polygon = lake["polygon"]
    # DECIMATED polygon for graph nodes (perf — visibility check is O(V²)).
    graph_vertices = _decimate_polygon(full_polygon, _PADDLE_MAX_POLYGON_VERTICES)

    # Fast path: straight line works against the full-resolution polygon.
    if _line_inside_polygon(start, end, full_polygon):
        return [start, end]

    # Build node list: start (0), end (1), then decimated polygon vertices.
    nodes = [list(start), list(end)] + [[v[0], v[1]] for v in graph_vertices]
    n = len(nodes)

    # Adjacency list with line-of-sight check against the FULL polygon.
    # Decimated graph_vertices give us a small node set; the visibility
    # test still uses full_polygon so we can't shave a corner across a
    # peninsula that the decimation flattened away.
    adj: list = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if _line_inside_polygon(nodes[i], nodes[j], full_polygon):
                w = _haversine_km(nodes[i], nodes[j])
                adj[i].append((j, w))
                adj[j].append((i, w))

    # Dijkstra from 0 (start) to 1 (end).
    INF = float("inf")
    dist = [INF] * n
    parent = [-1] * n
    dist[0] = 0.0
    visited = [False] * n
    while True:
        u = -1
        u_dist = INF
        for k in range(n):
            if not visited[k] and dist[k] < u_dist:
                u_dist = dist[k]
                u = k
        if u == -1 or u == 1:
            break
        visited[u] = True
        for v, w in adj[u]:
            alt = dist[u] + w
            if alt < dist[v]:
                dist[v] = alt
                parent[v] = u

    if dist[1] == INF:
        # No graph path (start or end outside polygon, or polygon is broken).
        centroid = lake.get("centroid")
        if centroid:
            return [list(start), list(centroid), list(end)]
        return [list(start), list(end)]

    # Reconstruct path from end back to start.
    path = []
    cur = 1
    while cur != -1:
        path.append(nodes[cur])
        cur = parent[cur]
    path.reverse()
    return path


def _path_distance_km(geometry: list) -> float:
    """Sum of haversine distances along [lat, lon] points."""
    total = 0.0
    for i in range(1, len(geometry)):
        total += _haversine_km(geometry[i - 1], geometry[i])
    return total


from datetime import datetime, timedelta


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
        if "name" not in lake:
            continue
        if _norm_lake_name(lake["name"]) == target:
            return lake
    return None


def _resolve_access_point(name: str, lakes: list) -> dict:
    """Resolve an access point name to {gps, lake}.

    Tries the hardcoded KILLARNEY_ACCESS_POINTS table first; for unknown
    names falls back to treating the name as a lake and using its centroid,
    so non-Killarney trips still work approximately.
    """
    info = KILLARNEY_ACCESS_POINTS.get(name)
    if info:
        return {"gps": info["gps"], "lake": _find_lake(info["lake"], lakes)}
    lake = _find_lake(name, lakes)
    if lake:
        return {"gps": lake["centroid"], "lake": lake}
    return {"gps": None, "lake": None}


def _min_dist_to_polygon_vertex(point: list, polygon: list) -> float:
    """Return the minimum haversine distance from point to any vertex of polygon."""
    best = float("inf")
    for v in polygon:
        d = _haversine_km(point, v)
        if d < best:
            best = d
    return best


def _classify_portage_endpoints(portage: dict, lakes: list) -> list:
    """Return the lakes (one per endpoint) each portage endpoint best belongs to.

    Strict point-in-polygon first; falls back to nearest-polygon-vertex within
    PORTAGE_TOLERANCE_KM. Centroid distance is a poor proxy for large irregular
    lakes — vertex distance correctly handles portage endpoints that lie exactly
    on the shoreline but fail the ray-cast due to floating-point precision.
    Returns [lake_or_None, lake_or_None].
    """
    result = []
    for ep in portage["endpoints"]:
        match = None
        # First: strict containment.
        for lake in lakes:
            if _point_in_polygon(ep, lake["polygon"]):
                match = lake
                break
        # Fallback: nearest polygon vertex within tolerance.
        if match is None:
            best = None
            best_dist = PORTAGE_TOLERANCE_KM
            for lake in lakes:
                d = _min_dist_to_polygon_vertex(ep, lake["polygon"])
                if d < best_dist:
                    best = lake
                    best_dist = d
            match = best
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


def _build_lake_graph(lakes: list, portages: list) -> dict:
    """Build adjacency: {lake_name: [(neighbor_name, portage_dict, ends), ...]}."""
    graph: dict = {l["name"]: [] for l in lakes if "name" in l}
    for p in portages:
        ends = _classify_portage_endpoints(p, lakes)
        if ends[0] is None or ends[1] is None:
            continue
        if "name" not in ends[0] or "name" not in ends[1]:
            continue
        a_name = ends[0]["name"]
        b_name = ends[1]["name"]
        if a_name == b_name:
            continue  # portage with both endpoints on same lake; ignore
        graph.setdefault(a_name, []).append((b_name, p, ends))
        graph.setdefault(b_name, []).append((a_name, p, ends))
    return graph


def _find_path_through_portages(lake_a: dict, lake_b: dict, lakes: list,
                                portages: list) -> "list | None":
    """BFS over the lake-portage graph from lake_a to lake_b.

    Returns a list of (next_lake_name, portage_dict, ends) tuples representing
    the path from lake_a to lake_b, or None if no path within MAX_PORTAGE_HOPS.
    """
    graph = _build_lake_graph(lakes, portages)
    start = lake_a["name"]
    goal = lake_b["name"]
    if start not in graph:
        return None

    # BFS
    queue: list = [(start, [])]
    visited = {start}
    while queue:
        current, path = queue.pop(0)
        if current == goal:
            return path
        if len(path) >= MAX_PORTAGE_HOPS:
            continue
        for neighbor, portage, ends in graph.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, path + [(neighbor, portage, ends)]))
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


def build_route(nights: list, access_point: str, osm: dict,
                library: Optional[dict] = None) -> dict:
    """Build per-leg segments + warnings from frontmatter nights + OSM data.

    Each "leg" is the travel between consecutive waypoints. Legs are:
      - Day 1: access_point -> nights[0]
      - Day N: nights[N-1] -> nights[N]
      - Last day: nights[-1] -> access_point

    For each leg the engine consults `library` (curated GPX connectors) first
    and uses real geometry when a matching lake-pair connector is found.
    Falls back to the OSM portage graph + straight-line paddle when no library
    match exists, and finally to an `approx` straight-line segment when even
    OSM lacks connecting data.

    Returns {"segments": [...], "warnings": [...], "markers": [...]}.
    """
    if library is None:
        library = {"connectors": []}
    lakes = osm["lakes"] + LAKE_SUPPLEMENT  # add hardcoded supplements
    portages = osm["portages"]
    segments: list = []
    warnings: list = []

    # Resolve the access point once — used as the start/end "point" for the
    # access waypoints regardless of route-finding outcome.
    access_info = _resolve_access_point(access_point, lakes)

    def _night_point(night: dict) -> Optional[list]:
        """Best [lat, lon] for a night.

        Resolution order:
          1. Frontmatter `gps:` override.
          2. Auto-resolve from osm['campsites'] by (ref, lake).
          3. Lake centroid.
          4. None if even the lake doesn't resolve.
        """
        gps = night.get("gps")
        if gps and len(gps) == 2:
            return [gps[0], gps[1]]
        site_ref = str(night.get("site", ""))
        location = night.get("location", "")
        for cs in osm.get("campsites", []) or []:
            if cs.get("ref") == site_ref and cs.get("lake") == location:
                return [cs["gps"][0], cs["gps"][1]]
        lake = _find_lake(location, lakes)
        return lake["centroid"] if lake else None

    # Build the ordered list of waypoint dicts. Each carries a `point` that
    # downstream segment construction uses as its actual coordinate.
    waypoints = [{
        "label": access_point,
        "location": access_point,
        "day_label": _day_label(nights[0]["date"]) if nights else "",
        "point": access_info["gps"],
    }]
    for night in nights:
        waypoints.append({
            "label": f"{night['location']} (site {night['site']})",
            "location": night["location"],
            "day_label": _day_label(night["date"]),
            "point": _night_point(night),
        })
    # Final leg: return to access point on the day after the last night.
    if nights:
        last_date = nights[-1]["date"]
        try:
            d = datetime.strptime(last_date, "%Y-%m-%d")
            return_date = (d + timedelta(days=1)).strftime("%Y-%m-%d")
            return_label = _day_label(return_date)
        except ValueError:
            return_label = "Return"
    else:
        return_label = "Return"
    waypoints.append({
        "label": access_point,
        "location": access_point,
        "day_label": return_label,
        "point": access_info["gps"],
    })

    # Walk leg by leg.
    for i in range(1, len(waypoints)):
        a = waypoints[i - 1]
        b = waypoints[i]
        day_label = b["day_label"]
        lake_a = _find_lake(a["location"], lakes)
        lake_b = _find_lake(b["location"], lakes)

        # Use waypoint-resolved points (gps override / access GPS / centroid)
        # rather than raw lake centroids so user-supplied site coords flow
        # through to the rendered geometry.
        a_pt_resolved = a["point"] if a["point"] else (lake_a["centroid"] if lake_a else None)
        b_pt_resolved = b["point"] if b["point"] else (lake_b["centroid"] if lake_b else None)

        if lake_a and lake_b and lake_a["name"] == lake_b["name"]:
            # Same lake — straight paddle, routed around peninsulas if needed.
            geom = _polygon_aware_paddle(a_pt_resolved, b_pt_resolved, lake_a)
            segments.append(_segment(
                day_label, "paddle", a["label"], b["label"],
                _path_distance_km(geom), geom,
            ))
            continue

        if lake_a and lake_b:
            # Library path (possibly multi-hop) takes precedence over OSM.
            from gpx_library import find_library_path
            lib_path = find_library_path(lake_a["name"], lake_b["name"], library)
            if lib_path:
                # Walk each connector in the chain, emitting paddle / portage /
                # paddle for each hop. Inter-hop paddles between two connectors
                # use the geometry from the prior connector's `departure` and
                # the next connector's `approach`.
                for hop_idx, conn in enumerate(lib_path):
                    is_first_hop = hop_idx == 0
                    is_last_hop = hop_idx == len(lib_path) - 1

                    # Approach paddle is only emitted on the FIRST hop. For
                    # subsequent hops, the previous hop's `departure` already
                    # covers the same intermediate-lake traversal — skipping
                    # avoids double-counting both distance and geometry.
                    if is_first_hop:
                        approach_geom = ([a_pt_resolved] + conn["approach"]
                                         if a_pt_resolved else conn["approach"])
                        segments.append(_segment(
                            day_label, "paddle", a["label"],
                            f"{conn['lake_a']} portage",
                            conn["approach_km"], approach_geom,
                        ))
                    segments.append(_segment(
                        day_label, "portage",
                        f"{conn['lake_a']} portage",
                        f"{conn['lake_b']} portage",
                        conn["portage_km"], conn["portage"],
                    ))
                    if is_last_hop and b_pt_resolved:
                        departure_geom = conn["departure"] + [b_pt_resolved]
                    else:
                        departure_geom = conn["departure"]
                    segments.append(_segment(
                        day_label, "paddle",
                        f"{conn['lake_b']} portage",
                        b["label"] if is_last_hop else conn["lake_b"],
                        conn["departure_km"], departure_geom,
                    ))
                continue

            path = _find_path_through_portages(lake_a, lake_b, lakes, portages)
            if path:
                current_lake = lake_a
                current_pt = a_pt_resolved or lake_a["centroid"]
                for next_name, portage, ends in path:
                    # Find which endpoint is in current_lake.
                    if ends[0] and ends[0]["name"] == current_lake["name"]:
                        entry, exit_ = portage["endpoints"]
                        portage_geom = portage["line"]
                    else:
                        exit_, entry = portage["endpoints"]
                        portage_geom = list(reversed(portage["line"]))
                    # Paddle from current point to portage entry, routed around
                    # peninsulas if a straight line would cross outside the lake.
                    paddle_geom = _polygon_aware_paddle(
                        current_pt, entry, current_lake,
                    )
                    segments.append(_segment(
                        day_label, "paddle",
                        a["label"] if current_lake is lake_a else f"{current_lake['name']}",
                        f"{current_lake['name']} portage",
                        _path_distance_km(paddle_geom), paddle_geom,
                    ))
                    # Portage.
                    next_lake = next((l for l in lakes if "name" in l and l["name"] == next_name), None)
                    segments.append(_segment(
                        day_label, "portage",
                        f"{current_lake['name']} portage",
                        f"{next_name} portage",
                        portage["length_km"], portage_geom,
                    ))
                    current_lake = next_lake
                    current_pt = exit_
                end_pt = b_pt_resolved or lake_b["centroid"]
                final_geom = _polygon_aware_paddle(current_pt, end_pt, lake_b)
                segments.append(_segment(
                    day_label, "paddle",
                    f"{lake_b['name']} portage", b["label"],
                    _path_distance_km(final_geom), final_geom,
                ))
                continue

        # Approximate-fallback: lake unmatched OR no connecting portage.
        if not lake_a:
            warnings.append(
                f"Could not resolve lake '{a['location']}' in OSM data — "
                "leg shown as straight line."
            )
        if not lake_b:
            warnings.append(
                f"Could not resolve lake '{b['location']}' in OSM data — "
                "leg shown as straight line."
            )
        if lake_a and lake_b:
            warnings.append(
                f"No portage found between {lake_a['name']} and {lake_b['name']} — "
                "leg shown as straight line."
            )
        # Use resolved waypoint points when available (gps override / access
        # GPS / centroid), otherwise fall back to a sentinel point roughly in
        # the middle of the Killarney bbox so the map still renders.
        a_pt = a_pt_resolved if a_pt_resolved else [46.02, -81.40]
        b_pt = b_pt_resolved if b_pt_resolved else [46.02, -81.40]
        d_km = _haversine_km(a_pt, b_pt)
        segments.append(_segment(
            day_label, "approx", a["label"], b["label"], d_km, [a_pt, b_pt],
        ))

    # Build markers: one for the access point, one per night.
    markers: list = []
    access = _resolve_access_point(access_point, lakes)
    if access["gps"]:
        markers.append({
            "label": access_point,
            "lat": access["gps"][0],
            "lon": access["gps"][1],
            "kind": "access",
        })
    for night in nights:
        # Use the same resolution priority as _night_point above.
        gps = night.get("gps")
        if gps and len(gps) == 2:
            markers.append({
                "label": f"Site {night['site']}, {night['location']}",
                "lat": gps[0],
                "lon": gps[1],
                "kind": "site",
            })
            continue
        site_ref = str(night.get("site", ""))
        location = night.get("location", "")
        campsite = next(
            (cs for cs in (osm.get("campsites") or [])
             if cs.get("ref") == site_ref and cs.get("lake") == location),
            None,
        )
        if campsite:
            markers.append({
                "label": f"Site {night['site']}, {night['location']}",
                "lat": campsite["gps"][0],
                "lon": campsite["gps"][1],
                "kind": "site",
            })
            continue
        lake = _find_lake(location, lakes)
        if lake:
            markers.append({
                "label": f"Site {night['site']}, {night['location']} (lake center)",
                "lat": lake["centroid"][0],
                "lon": lake["centroid"][1],
                "kind": "site",
            })

    return {"segments": segments, "warnings": warnings, "markers": markers}


def estimate_minutes(paddle_km: float, portage_km: float) -> int:
    """Total estimated travel time in minutes, including the buffer.

    Uses Fraction arithmetic throughout to avoid floating-point precision
    issues when results land exactly on 0.5 (e.g. 90 * 1.15 = 103.5 exactly,
    which Python's float gives as 103.4999...9).
    """
    paddle_f = Fraction(paddle_km).limit_denominator(10000)
    portage_f = Fraction(portage_km).limit_denominator(10000)
    paddle_kmh_f = Fraction(PADDLE_KMH).limit_denominator(10000)
    portage_kmh_f = Fraction(PORTAGE_KMH).limit_denominator(10000)
    # BUFFER_PCT = 0.15 => multiplier = 1.15 = 23/20 exactly.
    buf_f = Fraction(23, 20)
    paddle_min = paddle_f * 60 / paddle_kmh_f
    portage_min = portage_f * PORTAGE_TRAVERSALS * 60 / portage_kmh_f
    total = (paddle_min + portage_min) * buf_f
    return round(float(total))


def format_human_time(minutes: int) -> str:
    """Round minutes to nearest 5 and format as 'Xh Ym' or 'Ym'."""
    rounded = 5 * round(minutes / 5)
    h, m = divmod(rounded, 60)
    if h == 0:
        return f"{m}m"
    return f"{h}h {m}m"


def build_day_estimates(segments: list) -> list:
    """Aggregate segments by day. Returns list of DayEstimate dicts in day order."""
    days_in_order: list = []
    by_day: dict = {}
    for seg in segments:
        d = seg["day"]
        if d not in by_day:
            by_day[d] = {
                "day": d,
                "paddle_km": 0.0,
                "portage_km": 0.0,
                "approx": False,
                "_first_from": seg["from"],
                "_last_to": seg["to"],
            }
            days_in_order.append(d)
        rec = by_day[d]
        if seg["kind"] == "paddle":
            rec["paddle_km"] += seg["distance_km"]
        elif seg["kind"] == "portage":
            rec["portage_km"] += seg["distance_km"]
        elif seg["kind"] == "approx":
            # Approx legs count as paddle for distance + flag the day.
            rec["paddle_km"] += seg["distance_km"]
            rec["approx"] = True
        rec["_last_to"] = seg["to"]

    out = []
    for d in days_in_order:
        rec = by_day[d]
        paddle_km = round(rec["paddle_km"], 2)
        portage_km = round(rec["portage_km"], 2)
        minutes = estimate_minutes(paddle_km, portage_km)
        out.append({
            "day": d,
            "label": f"{rec['_first_from']} → {rec['_last_to']}",
            "paddle_km": paddle_km,
            "portage_km": portage_km,
            "approx": rec["approx"],
            "minutes": minutes,
            "human_time": format_human_time(minutes),
        })
    return out
