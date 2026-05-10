"""
Paddle leg routing — yellow paths + centroid-region Bezier curves.

Public API:
  route_paddle_leg(entry, exit, lake, yellow_paths) -> [[lat, lon], ...]
  fit_paddle_curve(entry, exit, lake) -> [[lat, lon], ...]

This module replaces the visibility-graph paddle routing in route_engine.
"""
import math

# Tunable constants — change here, no separate config file.
SNAP_TOLERANCE_KM = 0.5
LAKE_COVERAGE_PCT = 0.7
CENTROID_PULL = 0.4
PULL_RETRY_FACTORS = (0.4, 0.2, 0.0)
SAMPLES_PER_KM = 30
SAMPLES_MIN = 20


def _haversine_km(a, b):
    """Distance in km between [lat, lon] points."""
    R = 6371.0
    p1 = math.radians(a[0])
    p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


def _point_in_polygon(point, polygon):
    """Ray-casting point-in-polygon test. Polygon is a closed [lat, lon] ring."""
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


def _polygon_area_km2(polygon):
    """Polygon area in km² via planar shoelace (good enough for Killarney scale)."""
    if len(polygon) < 3:
        return 0.0
    pts = polygon[:-1] if polygon[0] == polygon[-1] else polygon
    # Convert lat/lon to local meters using mean latitude for lon scaling.
    mean_lat = sum(p[0] for p in pts) / len(pts)
    cos_lat = math.cos(math.radians(mean_lat))
    deg_lat_km = 111.32
    deg_lon_km = 111.32 * cos_lat
    xs = [p[1] * deg_lon_km for p in pts]
    ys = [p[0] * deg_lat_km for p in pts]
    s = 0.0
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        s += xs[i] * ys[j] - xs[j] * ys[i]
    return abs(s) / 2.0


def _bezier_quadratic(p0, p1, p2, t):
    """Quadratic Bezier interpolation at parameter t∈[0,1]."""
    u = 1.0 - t
    return [
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    ]


def _sample_count_for(distance_km):
    """How many sample points to generate along a curve of the given length."""
    return max(SAMPLES_MIN, math.ceil(distance_km * SAMPLES_PER_KM))


def fit_paddle_curve(entry, exit, lake):
    """Fit a Bezier curve from entry to exit pulling toward the lake centroid.

    Curve order scales with polygon area:
      area < 1 km²   → quadratic (1 control point at centroid)
      1 ≤ area < 5   → cubic    (2 control points; added in Task 2)
      area ≥ 5       → quartic  (3 control points; added in Task 2)

    Returns a densely-sampled polyline of [lat, lon] points starting at
    entry and ending at exit.
    """
    polygon = lake.get("polygon") or []
    centroid = lake.get("centroid")
    if not polygon or not centroid:
        return [list(entry), list(exit)]
    distance = _haversine_km(entry, exit)
    n_samples = _sample_count_for(distance)
    area = _polygon_area_km2(polygon)
    # Quadratic for small lakes: control point IS the centroid (no pull factor
    # needed because there's only one point to place).
    if area < 1.0:
        out = []
        for i in range(n_samples + 1):
            t = i / n_samples
            out.append(_bezier_quadratic(entry, centroid, exit, t))
        # Force exact endpoint match (Bezier evaluates to endpoints at t=0/1
        # but we may want zero floating-point drift).
        out[0] = [entry[0], entry[1]]
        out[-1] = [exit[0], exit[1]]
        return out
    # Cubic / quartic added in Task 2; return straight line for now.
    return [list(entry), list(exit)]
