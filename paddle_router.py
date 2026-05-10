"""
Paddle leg routing — yellow paths + centroid-region Bezier curves.

Public API:
  route_paddle_leg(entry, exit, lake, yellow_paths) -> [[lat, lon], ...]
  fit_paddle_curve(entry, exit, lake) -> [[lat, lon], ...]

This module replaces the visibility-graph paddle routing in route_engine.
"""
import math

# Tunable constants — change here, no separate config file.
SNAP_TOLERANCE_KM = 2.0
LAKE_COVERAGE_PCT = 0.6
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


def _bezier_cubic(p0, p1, p2, p3, t):
    """Cubic Bezier at parameter t."""
    u = 1.0 - t
    uu = u * u
    tt = t * t
    return [
        uu * u * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + tt * t * p3[0],
        uu * u * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + tt * t * p3[1],
    ]


def _bezier_quartic(p0, p1, p2, p3, p4, t):
    """Quartic (4th-order) Bezier at parameter t."""
    u = 1.0 - t
    return [
        u**4 * p0[0]
        + 4 * u**3 * t * p1[0]
        + 6 * u**2 * t**2 * p2[0]
        + 4 * u * t**3 * p3[0]
        + t**4 * p4[0],
        u**4 * p0[1]
        + 4 * u**3 * t * p1[1]
        + 6 * u**2 * t**2 * p2[1]
        + 4 * u * t**3 * p3[1]
        + t**4 * p4[1],
    ]


def _control_point(anchor, centroid, pull):
    """Anchor + pull × (centroid - anchor)."""
    return [
        anchor[0] + pull * (centroid[0] - anchor[0]),
        anchor[1] + pull * (centroid[1] - anchor[1]),
    ]


def _sample_count_for(distance_km):
    """How many sample points to generate along a curve of the given length."""
    return max(SAMPLES_MIN, math.ceil(distance_km * SAMPLES_PER_KM))


def _curve_samples(entry, exit, centroid, pull, area, n_samples):
    """Generate Bezier samples for the given pull factor and lake area."""
    if area < 1.0:
        # Quadratic — single control point pulled from the entry-exit midpoint
        # toward the centroid. Pull=1 puts it at centroid, pull=0 at midpoint.
        midpoint = [(entry[0] + exit[0]) / 2, (entry[1] + exit[1]) / 2]
        cp = [midpoint[0] + pull * (centroid[0] - midpoint[0]),
              midpoint[1] + pull * (centroid[1] - midpoint[1])]
        sampler = lambda t: _bezier_quadratic(entry, cp, exit, t)
    elif area < 5.0:
        cp1 = _control_point(entry, centroid, pull)
        cp2 = _control_point(exit, centroid, pull)
        sampler = lambda t: _bezier_cubic(entry, cp1, cp2, exit, t)
    else:
        # Quartic: 3 anchors at fractions 0.25, 0.5, 0.75 along the
        # entry-exit STRAIGHT line, each pulled toward centroid by `pull`.
        # At pull=0 the anchors stay on the straight line, so the curve
        # degenerates to a straight line — same property the cubic branch
        # already has.
        straight_25 = [entry[0] + 0.25 * (exit[0] - entry[0]),
                       entry[1] + 0.25 * (exit[1] - entry[1])]
        straight_50 = [entry[0] + 0.50 * (exit[0] - entry[0]),
                       entry[1] + 0.50 * (exit[1] - entry[1])]
        straight_75 = [entry[0] + 0.75 * (exit[0] - entry[0]),
                       entry[1] + 0.75 * (exit[1] - entry[1])]
        cp1 = _control_point(straight_25, centroid, pull)
        cp2 = _control_point(straight_50, centroid, pull)
        cp3 = _control_point(straight_75, centroid, pull)
        sampler = lambda t: _bezier_quartic(entry, cp1, cp2, cp3, exit, t)

    out = []
    for i in range(n_samples + 1):
        t = i / n_samples
        out.append(sampler(t))
    out[0] = [entry[0], entry[1]]
    out[-1] = [exit[0], exit[1]]
    return out


def _all_samples_in_polygon(samples, polygon):
    """True if every sample point lies inside the polygon. Endpoints excluded
    (they're often on the polygon boundary by construction)."""
    for pt in samples[1:-1]:
        if not _point_in_polygon(pt, polygon):
            return False
    return True


def fit_paddle_curve(entry, exit, lake):
    """Fit a Bezier curve from entry to exit pulling toward the lake centroid.

    Curve order scales with polygon area:
      area < 1 km²   → quadratic (1 control point)
      1 ≤ area < 5   → cubic    (2 control points)
      area ≥ 5       → quartic  (3 control points)

    Tries pull factors from PULL_RETRY_FACTORS in order; returns the first
    curve whose intermediate samples all lie inside the polygon. Pull 0.0
    degenerates to a straight line, so this always returns SOMETHING valid.

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

    last_geom = None
    for pull in PULL_RETRY_FACTORS:
        geom = _curve_samples(entry, exit, centroid, pull, area, n_samples)
        if _all_samples_in_polygon(geom, polygon):
            return geom
        last_geom = geom
    # All retries failed → return the straightest version (last attempted).
    return last_geom or [list(entry), list(exit)]


def _snap_to_polyline(point, polyline):
    """Closest point on the polyline (any segment, not just vertices).

    Returns (snap_point, segment_index, t) where t∈[0,1] is the position
    along the segment between polyline[segment_index] and
    polyline[segment_index+1]. Uses planar projection — adequate for
    sub-km nearest-point comparisons at Killarney latitudes.
    """
    if len(polyline) < 2:
        if polyline:
            return list(polyline[0]), 0, 0.0
        return list(point), 0, 0.0

    best = None  # (sq_dist, snap, idx, t)
    px, py = point[0], point[1]
    for i in range(len(polyline) - 1):
        ax, ay = polyline[i][0], polyline[i][1]
        bx, by = polyline[i + 1][0], polyline[i + 1][1]
        dx, dy = bx - ax, by - ay
        seg_sq = dx * dx + dy * dy
        if seg_sq < 1e-18:
            t = 0.0
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / seg_sq
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
        sx = ax + t * dx
        sy = ay + t * dy
        ddx, ddy = px - sx, py - sy
        sq = ddx * ddx + ddy * ddy
        if best is None or sq < best[0]:
            best = (sq, [sx, sy], i, t)
    return best[1], best[2], best[3]


def _path_inside_lake_pct(polyline_points, polygon):
    """Fraction of polyline vertices that fall inside the polygon."""
    if not polyline_points:
        return 0.0
    inside = sum(1 for pt in polyline_points if _point_in_polygon(pt, polygon))
    return inside / len(polyline_points)


def _walk_yellow_path(entry, exit, polyline):
    """Snap entry & exit to polyline; return geometry from entry → exit
    walking the polyline in the correct direction.

    Returns None if the polyline can't yield a sensible walk (e.g., snap
    points are at the same segment+t, meaning entry≈exit on the path).
    """
    snap_e, idx_e, t_e = _snap_to_polyline(entry, polyline)
    snap_x, idx_x, t_x = _snap_to_polyline(exit, polyline)
    # If entry and exit snap to the same single point, no useful walk.
    if idx_e == idx_x and abs(t_e - t_x) < 1e-9:
        return None

    # Determine forward vs reverse: lower (idx, t) is "earlier" along the path.
    forward = (idx_e, t_e) < (idx_x, t_x)
    out = [list(entry), list(snap_e)]
    if forward:
        # Add intermediate vertices polyline[idx_e+1 ... idx_x] (vertices
        # between the two snap points).
        for i in range(idx_e + 1, idx_x + 1):
            out.append(list(polyline[i]))
        out.append(list(snap_x))
    else:
        # Reverse: walk from idx_e backward to idx_x+1.
        for i in range(idx_e, idx_x, -1):
            out.append(list(polyline[i]))
        out.append(list(snap_x))
    out.append(list(exit))
    return out


def route_paddle_leg(entry, exit, lake, yellow_paths=()):
    """Route a paddle leg from entry to exit within the given lake.

    Tries yellow paths first (snap + walk); falls back to centroid-region
    Bezier curve if no yellow path qualifies. Final fallback is a straight
    line. Output geometry is densely sampled (the curve already IS the
    smooth geometry — no client-side spline rendering required).

    yellow_paths is a list of {"points": [[lat,lon], ...], ...} dicts.
    """
    polygon = lake.get("polygon") or []

    # Filter candidate yellow paths.
    candidates = []
    for yp in yellow_paths or ():
        pts = yp.get("points") or []
        if len(pts) < 2:
            continue
        if polygon and _path_inside_lake_pct(pts, polygon) < LAKE_COVERAGE_PCT:
            continue
        snap_e, _, _ = _snap_to_polyline(entry, pts)
        snap_x, _, _ = _snap_to_polyline(exit, pts)
        d_e = _haversine_km(entry, snap_e)
        d_x = _haversine_km(exit, snap_x)
        if d_e <= SNAP_TOLERANCE_KM and d_x <= SNAP_TOLERANCE_KM:
            # Score: total cost (entry-snap + walk + snap-exit).
            # We approximate the walk cost as |d_e + d_x| + path_length;
            # ranking on this is fine for the v1 "pick shortest" heuristic.
            total = d_e + d_x + (yp.get("length_km") or 0.0)
            candidates.append((total, pts))

    if candidates:
        candidates.sort(key=lambda c: c[0])
        for _, pts in candidates:
            walked = _walk_yellow_path(entry, exit, pts)
            if walked:
                return walked
        # All candidates produced empty walks → fall through to centroid.

    # Centroid-region curve.
    return fit_paddle_curve(entry, exit, lake)
