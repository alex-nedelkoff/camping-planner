# Paddle Router Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the visibility-graph paddle routing in `route_engine.py` with a two-strategy router that prefers Jeff's drawn yellow canoe paths and falls back to a centroid-region Bezier curve fitter.

**Architecture:** New `paddle_router.py` (pure geometry, no I/O) implements `route_paddle_leg(entry, exit, lake, yellow_paths)` — tries snap-to-yellow-path first, falls back to Bezier curve through entry → centroid-pull → exit (curve order scales with polygon area), final fallback is straight line. New `jeffs_paths_extractor.py` produces `jeffs_canoe_paths.json` from the KMZ via HSV mask + skeletonize + polyline tracing. Visibility-graph code is deleted.

**Tech Stack:** Python 3 + OpenCV (already in deps; possibly `opencv-contrib-python` for `ximgproc.thinning` with pure-Python Zhang-Suen fallback), pyyaml, pytest.

**Spec:** `docs/superpowers/specs/2026-05-10-paddle-router-rebuild-design.md`

---

## File Structure

**New files:**
- `paddle_router.py` — pure-geometry router (~250 lines): constants, `_haversine_km`, `_point_in_polygon`, `_polygon_area_km2`, `_snap_to_polyline`, Bezier samplers, `fit_paddle_curve`, `route_paddle_leg`
- `jeffs_paths_extractor.py` — CLI tool (~300 lines): KMZ walk, HSV mask, skeletonize, polyline trace, GPS projection
- `paths_palette.yaml` — HSV thresholds + skeletonize/simplify knobs
- `jeffs_canoe_paths.json` — committed extractor output
- `tests/test_paddle_router.py` — 9 unit tests
- `tests/test_jeffs_paths_extractor.py` — 1 smoke test

**Modified files:**
- `route_engine.py` — replace `_polygon_aware_paddle` call sites (lines 548, 614, 634) with `route_paddle_leg`; delete visibility-graph helpers
- `osm_data.py` — load `jeffs_canoe_paths.json` if present, attach `paths` key to returned dict
- `requirements.txt` — add `opencv-contrib-python>=4.8` (with pure-Python fallback in code)
- `README.md` — note the new extractor step
- `tests/test_osm_data.py` — small test for the paths-loading augmentation

**Deletes (in Task 12):** `_polygon_aware_paddle`, `_line_inside_polygon`, `_line_inside_any_polygon`, `_polygons_overlapping_corridor`, `_decimate_polygon`, `_PADDLE_MAX_POLYGON_VERTICES` from `route_engine.py`.

---

## Task 1: paddle_router scaffolding + quadratic Bezier (TDD)

Build the foundation: constants, polygon area, point-in-polygon helper, and the simplest Bezier (quadratic for small lakes).

**Files:**
- Create: `/Users/alex/Documents/camping-planner/paddle_router.py`
- Create: `/Users/alex/Documents/camping-planner/tests/test_paddle_router.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/alex/Documents/camping-planner/tests/test_paddle_router.py`:

```python
"""Tests for paddle_router.py."""
import math

import pytest

from paddle_router import (
    _haversine_km,
    _point_in_polygon,
    _polygon_area_km2,
    fit_paddle_curve,
)


def test_haversine_km_zero_for_same_point():
    assert _haversine_km([46.0, -81.0], [46.0, -81.0]) == 0.0


def test_haversine_km_one_degree_lat():
    d = _haversine_km([46.0, -81.0], [47.0, -81.0])
    assert 110 < d < 112


def test_point_in_polygon_inside_unit_square():
    poly = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    assert _point_in_polygon([0.5, 0.5], poly) is True


def test_point_in_polygon_outside_unit_square():
    poly = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    assert _point_in_polygon([1.5, 0.5], poly) is False


def test_polygon_area_km2_one_degree_square_is_about_12000_km2():
    """A 1°x1° square at lat 46 is roughly 111 × 111 × cos(46) ≈ 8500 km²."""
    poly = [
        [46.0, -81.0], [46.0, -80.0],
        [47.0, -80.0], [47.0, -81.0],
        [46.0, -81.0],
    ]
    area = _polygon_area_km2(poly)
    # Loose bounds: anywhere from 7000 to 13000 km² is acceptable for the
    # planar-degree approximation at this latitude.
    assert 7000 < area < 13000


def test_fit_paddle_curve_quadratic_for_small_lake():
    """Area < 1 km² → quadratic Bezier (1 control point at centroid).

    Synthetic 0.5x0.5 km square (area ≈ 0.25 km²). Curve from one corner
    to the diagonal corner pulls toward the centroid.
    """
    # Centered at lat=46, lon=-81. 0.005° lat ≈ 555 m, 0.005° lon ≈ 386 m.
    poly = [
        [45.9975, -81.0025], [45.9975, -80.9975],
        [46.0025, -80.9975], [46.0025, -81.0025],
        [45.9975, -81.0025],
    ]
    lake = {"polygon": poly, "centroid": [46.0, -81.0]}
    entry = [45.9978, -81.0023]   # near SW corner, inside polygon
    exit = [46.0022, -80.9977]    # near NE corner, inside polygon
    geom = fit_paddle_curve(entry, exit, lake)
    # Output is densely sampled (>= SAMPLES_MIN = 20).
    assert len(geom) >= 20
    # Endpoints preserved exactly.
    assert geom[0] == [entry[0], entry[1]]
    assert geom[-1] == [exit[0], exit[1]]
    # Midpoint is closer to centroid than the entry-exit straight midpoint.
    mid = geom[len(geom) // 2]
    straight_mid = [(entry[0] + exit[0]) / 2, (entry[1] + exit[1]) / 2]
    centroid = lake["centroid"]
    d_curve = math.hypot(mid[0] - centroid[0], mid[1] - centroid[1])
    d_straight = math.hypot(straight_mid[0] - centroid[0],
                             straight_mid[1] - centroid[1])
    # Curve midpoint should be at or pulled toward the centroid relative to
    # the straight line. For our square + centroid setup the straight midpoint
    # already IS the centroid, so we just verify the curve passes through
    # something close to the centroid (within 100 m).
    assert _haversine_km(mid, centroid) < 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 6 tests fail with `ModuleNotFoundError: No module named 'paddle_router'`.

- [ ] **Step 3: Implement paddle_router.py with constants + helpers + quadratic curve**

Create `/Users/alex/Documents/camping-planner/paddle_router.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add paddle_router.py tests/test_paddle_router.py
git commit -m "feat: paddle_router scaffolding + quadratic Bezier for small lakes"
```

---

## Task 2: Cubic + quartic Bezier curves (TDD)

Extend `fit_paddle_curve` to handle medium and large lakes.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/paddle_router.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_paddle_router.py`

- [ ] **Step 1: Write failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_paddle_router.py`:

```python
def test_fit_paddle_curve_cubic_for_medium_lake():
    """Area in [1, 5) km² → cubic Bezier with 2 control points pulled toward centroid."""
    # ~0.04° square at lat 46 ≈ 4.4 km × 3.1 km ≈ 13.6 km² — actually large.
    # Use a smaller square to land in cubic range.
    # 0.018° lat × 0.018° lon at lat 46 ≈ 2 km × 1.4 km ≈ 2.8 km².
    poly = [
        [45.991, -81.009], [45.991, -80.991],
        [46.009, -80.991], [46.009, -81.009],
        [45.991, -81.009],
    ]
    lake = {"polygon": poly, "centroid": [46.0, -81.0]}
    area = _polygon_area_km2(poly)
    assert 1.0 <= area < 5.0, f"Test fixture wrong: area={area}"
    entry = [45.992, -81.008]
    exit = [46.008, -80.992]
    geom = fit_paddle_curve(entry, exit, lake)
    # Densely sampled.
    assert len(geom) >= 20
    # Endpoints exact.
    assert geom[0] == [entry[0], entry[1]]
    assert geom[-1] == [exit[0], exit[1]]
    # All intermediate samples should be inside the polygon.
    for pt in geom[1:-1]:
        assert _point_in_polygon(pt, poly), f"Sample outside polygon: {pt}"
    # Midpoint should be pulled toward the centroid (closer to it than the
    # entry-exit midpoint would be in the absence of any centroid effect).
    # For our diagonal entry/exit through a square centered on the centroid,
    # the curve midpoint should be at or near the centroid.
    mid = geom[len(geom) // 2]
    assert _haversine_km(mid, lake["centroid"]) < 0.5  # within 500 m


def test_fit_paddle_curve_quartic_for_large_lake():
    """Area ≥ 5 km² → quartic Bezier with 3 control points."""
    # 0.05° square at lat 46 ≈ 5.6 km × 3.9 km ≈ 21 km² — definitely large.
    poly = [
        [45.975, -81.025], [45.975, -80.975],
        [46.025, -80.975], [46.025, -81.025],
        [45.975, -81.025],
    ]
    lake = {"polygon": poly, "centroid": [46.0, -81.0]}
    area = _polygon_area_km2(poly)
    assert area >= 5.0, f"Test fixture wrong: area={area}"
    entry = [45.977, -81.023]
    exit = [46.023, -80.977]
    geom = fit_paddle_curve(entry, exit, lake)
    assert len(geom) >= 20
    assert geom[0] == [entry[0], entry[1]]
    assert geom[-1] == [exit[0], exit[1]]
    for pt in geom[1:-1]:
        assert _point_in_polygon(pt, poly), f"Sample outside polygon: {pt}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 2 new tests fail (curve falls back to straight line; intermediate points pass polygon test trivially OR the midpoint-near-centroid assertion fails).

- [ ] **Step 3: Add cubic + quartic Bezier samplers**

In `/Users/alex/Documents/camping-planner/paddle_router.py`, append after `_bezier_quadratic`:

```python
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
```

Then REPLACE the entire `fit_paddle_curve` function with:

```python
def fit_paddle_curve(entry, exit, lake):
    """Fit a Bezier curve from entry to exit pulling toward the lake centroid.

    Curve order scales with polygon area:
      area < 1 km²   → quadratic (1 control point at centroid)
      1 ≤ area < 5   → cubic    (2 control points pulled toward centroid)
      area ≥ 5       → quartic  (3 control points distributed entry→centroid→exit)

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

    if area < 1.0:
        sampler = lambda t: _bezier_quadratic(entry, centroid, exit, t)
    elif area < 5.0:
        cp1 = _control_point(entry, centroid, CENTROID_PULL)
        cp2 = _control_point(exit, centroid, CENTROID_PULL)
        sampler = lambda t: _bezier_cubic(entry, cp1, cp2, exit, t)
    else:
        # Quartic: 3 controls distributed at fractions 0.25, 0.5, 0.75 of
        # the entry → centroid → exit polyline, each pulled toward centroid.
        # Anchors first:
        a25 = [entry[0] + 0.5 * (centroid[0] - entry[0]),
               entry[1] + 0.5 * (centroid[1] - entry[1])]
        a50 = list(centroid)
        a75 = [exit[0] + 0.5 * (centroid[0] - exit[0]),
               exit[1] + 0.5 * (centroid[1] - exit[1])]
        cp1 = _control_point(a25, centroid, CENTROID_PULL)
        cp2 = _control_point(a50, centroid, CENTROID_PULL)
        cp3 = _control_point(a75, centroid, CENTROID_PULL)
        sampler = lambda t: _bezier_quartic(entry, cp1, cp2, cp3, exit, t)

    out = []
    for i in range(n_samples + 1):
        t = i / n_samples
        out.append(sampler(t))
    out[0] = [entry[0], entry[1]]
    out[-1] = [exit[0], exit[1]]
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 8 tests pass (6 from Task 1 + 2 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add paddle_router.py tests/test_paddle_router.py
git commit -m "feat: cubic + quartic Bezier curves for medium/large lakes"
```

---

## Task 3: Validate-and-retry-with-lower-pull (TDD)

When the curve crosses outside the polygon, retry with a smaller pull factor.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/paddle_router.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_paddle_router.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paddle_router.py`:

```python
def test_fit_paddle_curve_retries_with_lower_pull_when_curve_leaves_polygon():
    """U-shaped polygon where 0.4 pull crosses outside; retry with 0.2 then 0.0."""
    # U-shape (upside down): outer rectangle minus a notch from the middle bottom.
    # Vertices ordered counter-clockwise.
    poly = [
        [0.000, 0.000], [0.000, 1.000],
        [1.000, 1.000], [1.000, 0.000],
        [0.700, 0.000], [0.700, 0.700],
        [0.300, 0.700], [0.300, 0.000],
        [0.000, 0.000],
    ]
    # Centroid at approximate inside-of-U position.
    # Naive average of vertices: lat=0.444, lon=0.378 (close to the notch).
    # We force it to the open part of the U so the cubic Bezier's 0.4-pull
    # cp1/cp2 fall outside the polygon (they'd be in the notch).
    lake = {"polygon": poly, "centroid": [0.5, 0.35]}
    entry = [0.1, 0.1]    # bottom-left arm of U
    exit = [0.9, 0.1]     # bottom-right arm of U
    # With centroid at [0.5, 0.35] inside the notch, control points pulled
    # 0.4 toward it from the entry/exit will be in the notch → outside the
    # polygon. The function should retry with pull 0.2 then 0.0.
    geom = fit_paddle_curve(entry, exit, lake)
    # Endpoints preserved exactly.
    assert geom[0] == [entry[0], entry[1]]
    assert geom[-1] == [exit[0], exit[1]]
    # Final geometry's intermediate samples must all be inside the polygon
    # (the function chose a pull factor that satisfies this).
    for pt in geom[1:-1]:
        assert _point_in_polygon(pt, poly), \
            f"Final geometry leaves polygon at {pt}"
```

NOTE about polygon orientation: this test uses lat/lon as `[x, y]` for
ease — it's a synthetic polygon and the math works the same way regardless
of the actual axis labels. `_point_in_polygon` doesn't care which is
latitude vs longitude.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py::test_fit_paddle_curve_retries_with_lower_pull_when_curve_leaves_polygon -v
```

Expected: FAIL — at least one sample falls in the notch (outside polygon) because pull factor 0.4 isn't being adjusted.

- [ ] **Step 3: Add validate-and-retry logic**

In `/Users/alex/Documents/camping-planner/paddle_router.py`, REPLACE the entire `fit_paddle_curve` function with:

```python
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
        a25 = [entry[0] + 0.5 * (centroid[0] - entry[0]),
               entry[1] + 0.5 * (centroid[1] - entry[1])]
        a50 = list(centroid)
        a75 = [exit[0] + 0.5 * (centroid[0] - exit[0]),
               exit[1] + 0.5 * (centroid[1] - exit[1])]
        cp1 = _control_point(a25, centroid, pull)
        cp2 = _control_point(a50, centroid, pull)
        cp3 = _control_point(a75, centroid, pull)
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
```

NOTE the small change to the quadratic branch: the previous version put
the single control point AT the centroid regardless of pull factor. With
the retry mechanism, pull factor needs to actually affect the curve, so
the quadratic now interpolates the control point between the entry-exit
midpoint (pull=0) and the centroid (pull=1). The Task 1 quadratic test
still passes because the test uses a square + centroid setup where the
straight midpoint already equals the centroid.

- [ ] **Step 4: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add paddle_router.py tests/test_paddle_router.py
git commit -m "feat: retry curve fitting with lower pull factor when out of polygon"
```

---

## Task 4: Snap-to-polyline (TDD)

Closest point on a polyline (any segment, not just vertices) — the geometric primitive for snapping entry/exit to yellow paths.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/paddle_router.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_paddle_router.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_paddle_router.py`:

```python
from paddle_router import _snap_to_polyline


def test_snap_to_polyline_finds_closest_segment_point():
    """Polyline of 3 points; query point off the second segment."""
    polyline = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
    # Query at (1.5, 0.5) — closest point on segment (1,0)-(1,1) is (1, 0.5).
    snap, idx, t = _snap_to_polyline([1.5, 0.5], polyline)
    assert idx == 1   # second segment
    assert abs(t - 0.5) < 1e-9
    assert abs(snap[0] - 1.0) < 1e-9
    assert abs(snap[1] - 0.5) < 1e-9


def test_snap_to_polyline_clamps_to_endpoint_at_start():
    """Query past polyline start; snap at first vertex (idx=0, t=0)."""
    polyline = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
    snap, idx, t = _snap_to_polyline([-1.0, 0.0], polyline)
    assert idx == 0
    assert abs(t) < 1e-9
    assert snap == [0.0, 0.0]


def test_snap_to_polyline_clamps_to_endpoint_at_end():
    polyline = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
    snap, idx, t = _snap_to_polyline([5.0, 0.0], polyline)
    # Last segment is index len-2 = 1, t=1.
    assert idx == 1
    assert abs(t - 1.0) < 1e-9
    assert snap == [2.0, 0.0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 3 new tests fail with `ImportError: cannot import name '_snap_to_polyline'`.

- [ ] **Step 3: Implement _snap_to_polyline**

Append to `/Users/alex/Documents/camping-planner/paddle_router.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add paddle_router.py tests/test_paddle_router.py
git commit -m "feat: snap-to-polyline for nearest-point on yellow paths"
```

---

## Task 5: route_paddle_leg orchestration (TDD)

Combine snap + walk-along-yellow + centroid-curve fallback into the public router.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/paddle_router.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_paddle_router.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_paddle_router.py`:

```python
from paddle_router import route_paddle_leg


def _square_lake(centroid_lat=46.0, centroid_lon=-81.0, half_deg=0.025):
    """A 0.05° square lake centered on (centroid_lat, centroid_lon)."""
    poly = [
        [centroid_lat - half_deg, centroid_lon - half_deg],
        [centroid_lat - half_deg, centroid_lon + half_deg],
        [centroid_lat + half_deg, centroid_lon + half_deg],
        [centroid_lat + half_deg, centroid_lon - half_deg],
        [centroid_lat - half_deg, centroid_lon - half_deg],
    ]
    return {"polygon": poly, "centroid": [centroid_lat, centroid_lon]}


def test_route_paddle_leg_picks_yellow_when_tolerance_met():
    """Yellow path with both endpoints within 0.5 km of entry/exit → use it."""
    lake = _square_lake()
    # Yellow path is a curve through the lake.
    yellow = {
        "id": 0,
        "points": [[45.985, -80.99], [46.0, -80.985], [46.015, -80.99]],
        "length_km": 3.5,
    }
    # Entry close to yellow start, exit close to yellow end.
    entry = [45.985, -80.99]
    exit = [46.015, -80.99]
    geom = route_paddle_leg(entry, exit, lake, [yellow])
    # Yellow route should produce more than just [entry, exit]: it includes
    # the polyline's interior point (46.0, -80.985).
    assert len(geom) >= 4
    # First and last are entry/exit (after snap).
    assert _haversine_km(geom[0], entry) < 0.01
    assert _haversine_km(geom[-1], exit) < 0.01
    # Interior should include something close to the polyline midpoint.
    interior_close_to_yellow_mid = any(
        _haversine_km(pt, [46.0, -80.985]) < 0.05 for pt in geom[1:-1]
    )
    assert interior_close_to_yellow_mid


def test_route_paddle_leg_falls_back_to_centroid_when_yellow_too_far():
    """Yellow path > SNAP_TOLERANCE_KM from entry → use centroid curve instead."""
    lake = _square_lake()
    # Place yellow path 1 km away from the entry point.
    yellow = {
        "id": 0,
        "points": [[45.95, -81.05], [45.96, -81.04]],
        "length_km": 1.0,
    }
    entry = [45.985, -80.99]
    exit = [46.015, -80.99]
    geom = route_paddle_leg(entry, exit, lake, [yellow])
    # Should have many sample points (centroid curve, not snap-walk).
    assert len(geom) >= 20
    # Endpoints exact.
    assert geom[0] == [entry[0], entry[1]]
    assert geom[-1] == [exit[0], exit[1]]


def test_route_paddle_leg_filters_yellow_by_lake_coverage():
    """Yellow polyline mostly outside the lake → not a candidate."""
    lake = _square_lake(centroid_lat=46.0, centroid_lon=-81.0, half_deg=0.01)
    # Yellow polyline 3 of 5 points OUTSIDE the lake (40% inside).
    yellow = {
        "id": 0,
        "points": [
            [46.005, -80.995],   # inside
            [46.005, -81.001],   # inside
            [46.05, -81.05],     # outside
            [46.06, -81.06],     # outside
            [46.07, -81.07],     # outside
        ],
        "length_km": 9.0,
    }
    entry = [46.005, -80.995]
    exit = [46.005, -81.001]
    geom = route_paddle_leg(entry, exit, lake, [yellow])
    # Coverage 40% < 70% → yellow rejected; centroid-curve geometry returned
    # (≥ 20 samples, both endpoints).
    assert len(geom) >= 20
    assert geom[0] == [entry[0], entry[1]]
    assert geom[-1] == [exit[0], exit[1]]


def test_route_paddle_leg_reverses_yellow_when_endpoints_inverted():
    """Entry near yellow's END, exit near yellow's START → walk path reversed."""
    lake = _square_lake()
    yellow = {
        "id": 0,
        "points": [
            [45.985, -80.99],   # path "start"
            [46.0, -80.985],
            [46.015, -80.99],   # path "end"
        ],
        "length_km": 3.5,
    }
    # Entry near the path's END, exit near the path's START.
    entry = [46.015, -80.99]
    exit = [45.985, -80.99]
    geom = route_paddle_leg(entry, exit, lake, [yellow])
    # Returned geometry should still START at entry and END at exit
    # (router must reverse the path internally).
    assert _haversine_km(geom[0], entry) < 0.01
    assert _haversine_km(geom[-1], exit) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 4 new tests fail with `ImportError: cannot import name 'route_paddle_leg'`.

- [ ] **Step 3: Implement route_paddle_leg**

Append to `/Users/alex/Documents/camping-planner/paddle_router.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_paddle_router.py -v
```

Expected: 16 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add paddle_router.py tests/test_paddle_router.py
git commit -m "feat: route_paddle_leg combining yellow paths + centroid curve fallback"
```

---

## Task 6: Wire router into route_engine.build_route

Replace the three `_polygon_aware_paddle` call sites with `route_paddle_leg`. Pass empty `yellow_paths` initially — visibility-graph code stays in place for now (deleted in Task 12).

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/route_engine.py`

- [ ] **Step 1: Add the import at the top of route_engine.py**

In `/Users/alex/Documents/camping-planner/route_engine.py`, find the existing imports (around line 10-13). Add:

```python
from paddle_router import route_paddle_leg
```

- [ ] **Step 2: Replace the same-lake call site (around line 548)**

Find:
```python
        if lake_a and lake_b and lake_a["name"] == lake_b["name"]:
            # Same lake — straight paddle, routed around peninsulas if needed.
            geom = _polygon_aware_paddle(
                a_pt_resolved, b_pt_resolved, lake_a, all_lakes=lakes,
            )
```

Replace with:
```python
        if lake_a and lake_b and lake_a["name"] == lake_b["name"]:
            # Same lake — route via yellow path or centroid curve.
            geom = route_paddle_leg(
                a_pt_resolved, b_pt_resolved, lake_a, yellow_paths=(),
            )
```

- [ ] **Step 3: Replace the multi-hop intermediate call site (around line 614)**

Find:
```python
                    paddle_geom = _polygon_aware_paddle(
                        current_pt, entry, current_lake, all_lakes=lakes,
                    )
```

Replace with:
```python
                    paddle_geom = route_paddle_leg(
                        current_pt, entry, current_lake, yellow_paths=(),
                    )
```

- [ ] **Step 4: Replace the multi-hop final call site (around line 634)**

Find:
```python
                final_geom = _polygon_aware_paddle(
                    current_pt, end_pt, lake_b, all_lakes=lakes,
                )
```

Replace with:
```python
                final_geom = route_paddle_leg(
                    current_pt, end_pt, lake_b, yellow_paths=(),
                )
```

- [ ] **Step 5: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ --ignore=tests/test_routes.py -q
```

Expected: existing tests pass + paddle_router's 16 tests pass. Visibility-graph functions still in `route_engine.py` but no longer called.

- [ ] **Step 6: Quick smoke check on the trip page**

```bash
cd /Users/alex/Documents/camping-planner
time python3 build_trip.py trips/killarney-2026-05/
```

Expected: build succeeds, "Wrote …trip.html" message. Time should be FASTER than before (~3s vs ~7.5s) because no more O(V²) visibility checks.

- [ ] **Step 7: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add route_engine.py trips/killarney-2026-05/trip.html
git commit -m "feat: wire route_paddle_leg into route_engine (centroid curves only, yellow=[])"
```

---

## Task 7: Yellow path extractor — KMZ walk + skeletonize

Build the CV pipeline up through skeletonized mask. No GPS projection yet — that's Task 8.

**Files:**
- Create: `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`
- Create: `/Users/alex/Documents/camping-planner/paths_palette.yaml`
- Create: `/Users/alex/Documents/camping-planner/tests/test_jeffs_paths_extractor.py`

- [ ] **Step 1: Create paths_palette.yaml**

Create `/Users/alex/Documents/camping-planner/paths_palette.yaml`:

```yaml
# HSV thresholds for Jeff's yellow canoe-route lines. Tune empirically
# against the actual KMZ on first run; defaults are starting points.
hue:        [22, 38]
saturation: [120, 255]
value:      [180, 255]

# Morphology: open kernel drops isolated yellow blobs (text labels);
# close kernel fills small gaps in the yellow line.
open_kernel_px:  3
close_kernel_px: 2

# Polyline filtering
min_length_px:   30
simplify_eps_px: 3
```

- [ ] **Step 2: Write failing test for the skeletonization step**

Create `/Users/alex/Documents/camping-planner/tests/test_jeffs_paths_extractor.py`:

```python
"""Tests for jeffs_paths_extractor.py."""
import numpy as np

from jeffs_paths_extractor import _skeletonize


def test_skeletonize_thick_horizontal_line_becomes_thin():
    """A 9-pixel-tall horizontal yellow stripe skeletonizes to ~1 px tall."""
    h, w = 50, 200
    mask = np.zeros((h, w), dtype=np.uint8)
    # Draw a 9-pixel-tall stripe through the middle row.
    mask[20:29, 5:195] = 255
    skel = _skeletonize(mask)
    assert skel.shape == mask.shape
    assert skel.dtype == np.uint8
    # Every column in [5, 194] should have exactly 1-2 white pixels (depends
    # on how the thinning algorithm tied-break a 9-wide stripe).
    for col in range(10, 190):
        col_white = int(np.sum(skel[:, col] > 0))
        assert col_white in (1, 2), \
            f"Column {col} has {col_white} white pixels (expected 1 or 2)"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_paths_extractor.py -v
```

Expected: fail with `ModuleNotFoundError: No module named 'jeffs_paths_extractor'`.

- [ ] **Step 4: Create jeffs_paths_extractor.py with the skeletonize function**

Create `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`:

```python
"""
Extract Jeff's yellow canoe-route polylines from the KMZ raster.

Output: jeffs_canoe_paths.json — a list of GPS polylines that
paddle_router.route_paddle_leg snaps to as the preferred routing source.

Usage:
  python3 jeffs_paths_extractor.py path/to/jeffs.kmz \\
    --bbox 45.92,-81.60,46.12,-81.25 \\
    --paths-palette paths_palette.yaml \\
    --out jeffs_canoe_paths.json \\
    --review-html jeffs_paths_review.html
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


def _skeletonize(mask: np.ndarray) -> np.ndarray:
    """Reduce a binary mask to a 1-pixel-wide centerline.

    Tries cv2.ximgproc.thinning first (fast, C++); falls back to a pure-
    Python Zhang-Suen implementation if `ximgproc` isn't available.
    """
    try:
        import cv2.ximgproc as xip
        return xip.thinning(mask, thinningType=xip.THINNING_GUOHALL)
    except (ImportError, AttributeError):
        return _zhang_suen_thinning(mask)


def _zhang_suen_thinning(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen iterative thinning. Pure NumPy, slower than OpenCV's C++."""
    img = (mask > 0).astype(np.uint8)
    prev = np.zeros_like(img)
    while True:
        # Subiteration 1
        marker = np.zeros_like(img)
        h, w = img.shape
        # Build neighbor stack (P2..P9 in Zhang-Suen notation)
        # Using slicing for speed.
        p2 = np.zeros_like(img); p2[1:, :] = img[:-1, :]
        p3 = np.zeros_like(img); p3[1:, :-1] = img[:-1, 1:]
        p4 = np.zeros_like(img); p4[:, :-1] = img[:, 1:]
        p5 = np.zeros_like(img); p5[:-1, :-1] = img[1:, 1:]
        p6 = np.zeros_like(img); p6[:-1, :] = img[1:, :]
        p7 = np.zeros_like(img); p7[:-1, 1:] = img[1:, :-1]
        p8 = np.zeros_like(img); p8[:, 1:] = img[:, :-1]
        p9 = np.zeros_like(img); p9[1:, 1:] = img[:-1, :-1]
        b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
        # Transitions p2->p3->...->p9->p2 in cyclic order
        a = ((p2 == 0) & (p3 == 1)).astype(np.uint8)
        a += ((p3 == 0) & (p4 == 1)).astype(np.uint8)
        a += ((p4 == 0) & (p5 == 1)).astype(np.uint8)
        a += ((p5 == 0) & (p6 == 1)).astype(np.uint8)
        a += ((p6 == 0) & (p7 == 1)).astype(np.uint8)
        a += ((p7 == 0) & (p8 == 1)).astype(np.uint8)
        a += ((p8 == 0) & (p9 == 1)).astype(np.uint8)
        a += ((p9 == 0) & (p2 == 1)).astype(np.uint8)
        cond = (
            (img == 1) & (b >= 2) & (b <= 6) & (a == 1)
            & (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
        )
        marker[cond] = 1
        img[marker == 1] = 0
        # Subiteration 2 (similar but P2*P4*P8=0 and P2*P6*P8=0)
        marker2 = np.zeros_like(img)
        p2 = np.zeros_like(img); p2[1:, :] = img[:-1, :]
        p3 = np.zeros_like(img); p3[1:, :-1] = img[:-1, 1:]
        p4 = np.zeros_like(img); p4[:, :-1] = img[:, 1:]
        p5 = np.zeros_like(img); p5[:-1, :-1] = img[1:, 1:]
        p6 = np.zeros_like(img); p6[:-1, :] = img[1:, :]
        p7 = np.zeros_like(img); p7[:-1, 1:] = img[1:, :-1]
        p8 = np.zeros_like(img); p8[:, 1:] = img[:, :-1]
        p9 = np.zeros_like(img); p9[1:, 1:] = img[:-1, :-1]
        b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
        a = ((p2 == 0) & (p3 == 1)).astype(np.uint8)
        a += ((p3 == 0) & (p4 == 1)).astype(np.uint8)
        a += ((p4 == 0) & (p5 == 1)).astype(np.uint8)
        a += ((p5 == 0) & (p6 == 1)).astype(np.uint8)
        a += ((p6 == 0) & (p7 == 1)).astype(np.uint8)
        a += ((p7 == 0) & (p8 == 1)).astype(np.uint8)
        a += ((p8 == 0) & (p9 == 1)).astype(np.uint8)
        a += ((p9 == 0) & (p2 == 1)).astype(np.uint8)
        cond = (
            (img == 1) & (b >= 2) & (b <= 6) & (a == 1)
            & (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
        )
        marker2[cond] = 1
        img[marker2 == 1] = 0
        if np.array_equal(img, prev):
            break
        prev = img.copy()
    return (img * 255).astype(np.uint8)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_paths_extractor.py -v
```

Expected: 1 test passes (skeletonize works).

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_paths_extractor.py paths_palette.yaml tests/test_jeffs_paths_extractor.py
git commit -m "feat: yellow path extractor scaffolding + skeletonize"
```

---

## Task 8: Polyline tracing + GPS projection

Walk the skeletonized mask into polylines, simplify, project to GPS.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_paths_extractor.py`

- [ ] **Step 1: Write failing test**

Append to `/Users/alex/Documents/camping-planner/tests/test_jeffs_paths_extractor.py`:

```python
from jeffs_paths_extractor import _trace_skeleton_polylines


def test_trace_skeleton_polylines_finds_one_horizontal_line():
    """A 1-pixel horizontal stripe should yield exactly one polyline."""
    h, w = 30, 100
    skel = np.zeros((h, w), dtype=np.uint8)
    # Single row of white pixels from col 10 to col 89.
    skel[15, 10:90] = 255
    polylines = _trace_skeleton_polylines(skel, min_length_px=10)
    assert len(polylines) == 1
    line = polylines[0]
    # Polyline should span the full extent of the drawn stripe.
    xs = [p[0] for p in line]
    ys = [p[1] for p in line]
    # Note: returned points are (col, row) tuples — i.e., (x, y).
    assert min(xs) == 10
    assert max(xs) == 89
    assert all(y == 15 for y in ys)


def test_trace_skeleton_drops_too_short_polylines():
    """A 5-pixel stripe is below min_length=10 → dropped."""
    skel = np.zeros((20, 50), dtype=np.uint8)
    skel[10, 5:10] = 255
    polylines = _trace_skeleton_polylines(skel, min_length_px=10)
    assert polylines == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_paths_extractor.py -v
```

Expected: 2 new tests fail with ImportError on `_trace_skeleton_polylines`.

- [ ] **Step 3: Implement polyline tracing**

Append to `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`:

```python
def _trace_skeleton_polylines(skel: np.ndarray, min_length_px: int = 30) -> list:
    """Walk a skeletonized binary mask into polylines.

    Returns list of polylines, each a list of (col, row) integer tuples.
    Points where degree != 2 (endpoints, junctions) are treated as polyline
    boundaries — branches at junctions become separate polylines.

    Drops polylines shorter than min_length_px (Manhattan length is fine
    for filtering noise; we don't need true Euclidean length here).
    """
    # Build set of white-pixel coords.
    ys, xs = np.where(skel > 0)
    if len(xs) == 0:
        return []
    pixels = set(zip(xs.tolist(), ys.tolist()))
    h, w = skel.shape

    def neighbors(p):
        x, y = p
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                np_ = (x + dx, y + dy)
                if np_ in pixels:
                    out.append(np_)
        return out

    def degree(p):
        return len(neighbors(p))

    # Endpoints (degree 1) and junctions (degree ≥ 3) are walk boundaries.
    boundaries = {p for p in pixels if degree(p) != 2}

    visited_edges = set()  # set of frozenset({a, b}) edges already walked
    polylines = []

    def walk_from(start, first_step):
        path = [start, first_step]
        visited_edges.add(frozenset({start, first_step}))
        prev, curr = start, first_step
        while curr not in boundaries:
            nbrs = [n for n in neighbors(curr) if n != prev]
            if not nbrs:
                break
            nxt = nbrs[0]
            if frozenset({curr, nxt}) in visited_edges:
                break
            visited_edges.add(frozenset({curr, nxt}))
            path.append(nxt)
            prev, curr = curr, nxt
        return path

    # Walk from every boundary along each unvisited neighbor.
    for b in list(boundaries):
        for n in neighbors(b):
            if frozenset({b, n}) in visited_edges:
                continue
            path = walk_from(b, n)
            if len(path) >= min_length_px:
                polylines.append(path)

    # Pixels in degree-2 chains with no boundary (closed loops) — pick any
    # remaining pixel and walk both directions.
    remaining = pixels - {pt for path in polylines for pt in path}
    for p in list(remaining):
        if any(frozenset({p, n}) in visited_edges for n in neighbors(p)):
            continue
        nbrs = neighbors(p)
        if not nbrs:
            continue
        path = walk_from(p, nbrs[0])
        if len(path) >= min_length_px:
            polylines.append(path)

    return polylines
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_paths_extractor.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_paths_extractor.py tests/test_jeffs_paths_extractor.py
git commit -m "feat: trace skeletonized mask into polylines (boundary-walking)"
```

---

## Task 9: CLI + GPS projection + review HTML + integration test

Tie the pipeline together, project pixel coords to GPS via the existing mosaic transform, write JSON output and review HTML.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_paths_extractor.py`

- [ ] **Step 1: Write a synthetic-image integration test**

Append to `tests/test_jeffs_paths_extractor.py`:

```python
import json
from pathlib import Path

from jeffs_paths_extractor import main as extractor_main
from tests.fixtures.synthetic_kmz import write_synthetic_kmz


def _yellow_line_image_bytes(w=300, h=300):
    """White background with a 6-px-tall yellow stripe across the middle."""
    import cv2 as _cv2
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Yellow in BGR is (0, 255, 255).
    img[145:151, 30:270] = (0, 255, 255)
    ok, buf = _cv2.imencode('.png', img)
    assert ok
    return buf.tobytes()


def test_extractor_main_produces_at_least_one_polyline(tmp_path):
    """End-to-end: synthetic KMZ with a yellow line → JSON with one polyline."""
    kmz = tmp_path / "syn.kmz"
    write_synthetic_kmz(kmz, level=7, tiles=[
        {"filename": "a.png",
         "bounds": (46.0, 45.99, -80.99, -81.0),
         "image": _yellow_line_image_bytes()},
    ])
    palette = tmp_path / "palette.yaml"
    palette.write_text(
        "hue: [22, 38]\nsaturation: [120, 255]\nvalue: [120, 255]\n"
        "open_kernel_px: 1\nclose_kernel_px: 1\n"
        "min_length_px: 20\nsimplify_eps_px: 1\n"
    )
    out = tmp_path / "paths.json"
    rc = extractor_main([
        str(kmz),
        "--bbox", "45.99,-81.00,46.00,-80.99",
        "--paths-palette", str(palette),
        "--out", str(out),
        "--zoom", "7",
    ])
    assert rc == 0
    data = json.loads(out.read_text())
    assert len(data["paths"]) >= 1
    # Each path has GPS coords inside the synthetic bbox.
    for pth in data["paths"]:
        for lat, lon in pth["points"]:
            assert 45.99 <= lat <= 46.0
            assert -81.0 <= lon <= -80.99
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_paths_extractor.py::test_extractor_main_produces_at_least_one_polyline -v
```

Expected: fail with `ImportError: cannot import name 'main' from 'jeffs_paths_extractor'`.

- [ ] **Step 3: Implement the CLI + integration**

Append to `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`:

```python
import yaml
from PIL import Image

# Reuse existing infrastructure.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jeffs_extractor import walk_kmz, build_mosaic


def _polyline_pixel_to_gps(polyline_px, mosaic_bounds, mosaic_shape):
    """Project a list of (col, row) pixel coords through the mosaic transform."""
    n, s, e, w = mosaic_bounds
    h, mosaic_w = mosaic_shape[:2]
    out = []
    for col, row in polyline_px:
        lon = w + (col / mosaic_w) * (e - w)
        lat = n - (row / h) * (n - s)
        out.append([lat, lon])
    return out


def _polyline_length_km(polyline_gps):
    """Sum haversine distances along a GPS polyline."""
    R = 6371.0
    total = 0.0
    for i in range(1, len(polyline_gps)):
        a, b = polyline_gps[i - 1], polyline_gps[i]
        import math
        p1 = math.radians(a[0])
        p2 = math.radians(b[0])
        dp = math.radians(b[0] - a[0])
        dl = math.radians(b[1] - a[1])
        h = (math.sin(dp / 2) ** 2
             + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
        total += R * 2 * math.asin(math.sqrt(h))
    return total


def _extract_paths_from_mosaic(mosaic_bgr: np.ndarray, palette: dict) -> list:
    """Run the full HSV → morphology → skeletonize → trace → simplify pipeline.
    Returns list of (col, row) pixel polylines.
    """
    hsv = cv2.cvtColor(mosaic_bgr, cv2.COLOR_BGR2HSV)
    low = np.array([palette["hue"][0], palette["saturation"][0], palette["value"][0]])
    high = np.array([palette["hue"][1], palette["saturation"][1], palette["value"][1]])
    mask = cv2.inRange(hsv, low, high)

    open_px = int(palette.get("open_kernel_px", 0) or 0)
    if open_px > 0:
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (open_px, open_px)),
        )
    close_px = int(palette.get("close_kernel_px", 0) or 0)
    if close_px > 0:
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (close_px, close_px)),
        )

    skel = _skeletonize(mask)
    min_len = int(palette.get("min_length_px", 30))
    polylines_px = _trace_skeleton_polylines(skel, min_length_px=min_len)
    eps = float(palette.get("simplify_eps_px", 3))
    simplified = []
    for poly in polylines_px:
        arr = np.array([[[p[0], p[1]]] for p in poly], dtype=np.int32)
        approx = cv2.approxPolyDP(arr, eps, closed=False)
        simplified.append([(int(pt[0][0]), int(pt[0][1])) for pt in approx])
    return simplified


def _write_review_html(out_path: Path, paths: list) -> None:
    """Minimal review listing: counts + per-path centroid + length."""
    rows = "".join(
        f"<tr><td>{p['id']}</td><td>{p['length_km']:.2f}</td>"
        f"<td>{p['points'][0][0]:.4f}, {p['points'][0][1]:.4f}</td>"
        f"<td>{len(p['points'])}</td></tr>"
        for p in paths
    )
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Jeff's path extractor review</title>"
        "<style>body{font-family:sans-serif;max-width:900px;margin:2rem auto;"
        "padding:1rem}table{border-collapse:collapse;width:100%}"
        "th,td{border-bottom:1px solid #ddd;padding:0.4rem 0.6rem;text-align:left}"
        "th{background:#f0f4ee}</style></head><body>"
        f"<h1>Yellow paths ({len(paths)})</h1>"
        "<table><thead><tr><th>id</th><th>length_km</th>"
        "<th>first GPS</th><th>vertices</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></body></html>"
    )
    out_path.write_text(html)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kmz", help="Path to Jeff's KMZ")
    parser.add_argument("--bbox", required=True,
                        help="south,west,north,east")
    parser.add_argument("--paths-palette", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--zoom", type=int, default=7)
    parser.add_argument("--review-html")
    args = parser.parse_args(argv)

    bbox = tuple(float(x) for x in args.bbox.split(","))
    if len(bbox) != 4:
        print("--bbox needs 4 comma-separated values", file=sys.stderr)
        return 2

    palette = yaml.safe_load(Path(args.paths_palette).read_text()) or {}

    import shutil
    import tempfile
    extract_dir = Path(tempfile.mkdtemp(prefix="jeffs_paths_"))
    try:
        tiles = list(walk_kmz(Path(args.kmz), bbox=bbox,
                              zoom_level=args.zoom, extract_dir=extract_dir))
        if not tiles:
            print(f"No tiles in bbox {bbox} at zoom {args.zoom}",
                  file=sys.stderr)
            return 3
        print(f"  walking KMZ at zoom {args.zoom}: {len(tiles)} tiles",
              file=sys.stderr)
        mosaic, mosaic_bounds = build_mosaic(tiles)
        polylines_px = _extract_paths_from_mosaic(mosaic, palette)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    paths = []
    for i, poly_px in enumerate(polylines_px):
        gps = _polyline_pixel_to_gps(poly_px, mosaic_bounds, mosaic.shape)
        paths.append({
            "id": i,
            "points": gps,
            "length_km": round(_polyline_length_km(gps), 3),
        })

    out_data = {
        "paths": paths,
        "_meta": {
            "source_kmz": Path(args.kmz).name,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "zoom": args.zoom,
            "bbox": list(bbox),
            "count": len(paths),
        },
    }
    Path(args.out).write_text(json.dumps(out_data, indent=2))
    print(f"Wrote {args.out} with {len(paths)} polylines", file=sys.stderr)

    if args.review_html:
        _write_review_html(Path(args.review_html), paths)
        print(f"Wrote {args.review_html}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ --ignore=tests/test_routes.py -q 2>&1 | tail -3
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_paths_extractor.py tests/test_jeffs_paths_extractor.py
git commit -m "feat: jeffs_paths_extractor CLI + GPS projection + review HTML"
```

---

## Task 10: Wire yellow paths through osm_data + route_engine

Load `jeffs_canoe_paths.json` in `osm_data`, expose as `paths` key. Route engine filters per-lake and passes to `route_paddle_leg`.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/osm_data.py`
- Modify: `/Users/alex/Documents/camping-planner/route_engine.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_osm_data.py`

- [ ] **Step 1: Write failing test for osm_data augmentation**

Append to `/Users/alex/Documents/camping-planner/tests/test_osm_data.py`:

```python
def test_load_features_includes_yellow_paths_when_cache_present(tmp_path, monkeypatch):
    """jeffs_canoe_paths.json file (if present) → 'paths' key on the result."""
    osm_cache = {"lakes": [], "portages": []}
    paths_cache = {
        "paths": [
            {"id": 0, "points": [[46.0, -81.0], [46.01, -81.01]],
             "length_km": 1.4},
        ],
    }
    osm_path = tmp_path / "osm_killarney_cache.json"
    paths_path = tmp_path / "jeffs_canoe_paths.json"
    osm_path.write_text(json.dumps(osm_cache))
    paths_path.write_text(json.dumps(paths_cache))

    monkeypatch.setattr(_osm_data, "CACHE_PATH", osm_path)
    monkeypatch.setattr(_osm_data, "JEFFS_CACHE_PATH",
                        tmp_path / "jeffs_killarney_cache.json")  # absent
    monkeypatch.setattr(_osm_data, "PATHS_CACHE_PATH", paths_path)

    out = _osm_data.load_killarney_features()
    assert "paths" in out
    assert len(out["paths"]) == 1
    assert out["paths"][0]["id"] == 0


def test_load_features_paths_default_empty_when_cache_absent(tmp_path, monkeypatch):
    """Without jeffs_canoe_paths.json, paths key is an empty list."""
    osm_cache = {"lakes": [], "portages": []}
    osm_path = tmp_path / "osm_killarney_cache.json"
    osm_path.write_text(json.dumps(osm_cache))
    monkeypatch.setattr(_osm_data, "CACHE_PATH", osm_path)
    monkeypatch.setattr(_osm_data, "JEFFS_CACHE_PATH",
                        tmp_path / "jeffs_killarney_cache.json")  # absent
    monkeypatch.setattr(_osm_data, "PATHS_CACHE_PATH",
                        tmp_path / "jeffs_canoe_paths.json")  # absent

    out = _osm_data.load_killarney_features()
    assert out.get("paths") == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_osm_data.py -v
```

Expected: 2 new tests fail with `AttributeError: module 'osm_data' has no attribute 'PATHS_CACHE_PATH'`.

- [ ] **Step 3: Augment osm_data.load_killarney_features**

Edit `/Users/alex/Documents/camping-planner/osm_data.py`. Near the top, alongside `JEFFS_CACHE_PATH = ...`, add:

```python
PATHS_CACHE_PATH = Path(__file__).parent / "jeffs_canoe_paths.json"
```

In `load_killarney_features()`, after the `JEFFS_CACHE_PATH` block but before `return out`, add:

```python
    out["paths"] = []
    if PATHS_CACHE_PATH.exists():
        paths_cache = json.loads(PATHS_CACHE_PATH.read_text(encoding="utf-8"))
        out["paths"] = paths_cache.get("paths", [])
```

- [ ] **Step 4: Add a per-lake yellow filter in route_engine**

In `/Users/alex/Documents/camping-planner/route_engine.py`, near the other helper functions (before `build_route`), add:

```python
def _yellow_paths_in_lake(lake: dict, all_paths: list,
                          coverage_threshold: float = 0.7) -> list:
    """Subset of all_paths whose vertices are ≥ coverage_threshold inside lake."""
    if not lake or not lake.get("polygon") or not all_paths:
        return []
    polygon = lake["polygon"]
    out = []
    for path in all_paths:
        pts = path.get("points") or []
        if not pts:
            continue
        inside = sum(1 for p in pts if _point_in_polygon(p, polygon))
        if inside / len(pts) >= coverage_threshold:
            out.append(path)
    return out
```

Then update the three `route_paddle_leg` call sites in `build_route` to pass per-lake filtered paths. Find each call (currently passing `yellow_paths=()`):

For the same-lake case (line ~548):
```python
            geom = route_paddle_leg(
                a_pt_resolved, b_pt_resolved, lake_a, yellow_paths=(),
            )
```
Replace with:
```python
            yellow_in_lake = _yellow_paths_in_lake(lake_a, osm.get("paths", []))
            geom = route_paddle_leg(
                a_pt_resolved, b_pt_resolved, lake_a,
                yellow_paths=yellow_in_lake,
            )
```

Same pattern for the multi-hop intermediate (line ~614, lake = `current_lake`):
```python
                    yellow_in_lake = _yellow_paths_in_lake(
                        current_lake, osm.get("paths", []),
                    )
                    paddle_geom = route_paddle_leg(
                        current_pt, entry, current_lake,
                        yellow_paths=yellow_in_lake,
                    )
```

And the multi-hop final (line ~634, lake = `lake_b`):
```python
                yellow_in_lake = _yellow_paths_in_lake(lake_b, osm.get("paths", []))
                final_geom = route_paddle_leg(
                    current_pt, end_pt, lake_b,
                    yellow_paths=yellow_in_lake,
                )
```

- [ ] **Step 5: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ --ignore=tests/test_routes.py -q 2>&1 | tail -3
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add osm_data.py route_engine.py tests/test_osm_data.py
git commit -m "feat: load + thread yellow paths through to route_paddle_leg"
```

---

## Task 11: Run extractor against real KMZ + commit cache

This is the empirical step — run the extractor, tune palette via review HTML, commit `jeffs_canoe_paths.json`.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/paths_palette.yaml` (palette tuning)
- Create: `/Users/alex/Documents/camping-planner/jeffs_canoe_paths.json`
- Modify: `/Users/alex/Documents/camping-planner/trips/killarney-2026-05/trip.html`

- [ ] **Step 1: Confirm opencv-contrib is installed (or fall back to Zhang-Suen)**

```bash
python3 -c "import cv2.ximgproc; print('ximgproc available')" 2>&1 | tail -1
```

If output is `ximgproc available`, skeletonize will use the fast C++ path. If not, the pure-Python Zhang-Suen runs (slower but works). To install contrib:
```bash
pip install opencv-contrib-python
```
(Optional — only if you want to skip Zhang-Suen on the real run.)

- [ ] **Step 2: Run the extractor**

```bash
cd /Users/alex/Documents/camping-planner
python3 jeffs_paths_extractor.py \
  "/Users/alex/Documents/camping-planner/Maps by Jeff - Full French River and Killarney Paddling Map v4.0 - Google Earth.kmz" \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --paths-palette paths_palette.yaml \
  --out jeffs_canoe_paths.json \
  --review-html /tmp/jeffs_paths_review.html \
  --zoom 7 2>&1 | tail -5
```

Expected: prints `Wrote jeffs_canoe_paths.json with N polylines`. N is typically in the 20-80 range for Killarney (one polyline per Jeff-drawn yellow line, plus some noise).

- [ ] **Step 3: Inspect the result**

```bash
python3 -c "
import json
data = json.load(open('jeffs_canoe_paths.json'))
print(f'paths: {len(data[\"paths\"])}')
lengths = sorted((p['length_km'] for p in data['paths']), reverse=True)
print(f'top 10 lengths (km): {[round(l,2) for l in lengths[:10]]}')
print(f'cache size: {round(__import__(\"os\").path.getsize(\"jeffs_canoe_paths.json\")/1024, 1)} KB')
"
```

If the count is unreasonable (< 5 or > 200), tune `paths_palette.yaml`:
- Too few paths → widen HSV thresholds (broader hue range, lower saturation/value floors).
- Too many paths → tighten HSV (narrower bands), or increase `min_length_px`.

Re-run Step 2 after each palette change. Open `/tmp/jeffs_paths_review.html` to visually verify.

**Budget 30-60 minutes for palette tuning on the first run.**

- [ ] **Step 4: Regenerate the trip page using yellow paths**

```bash
cd /Users/alex/Documents/camping-planner
time python3 build_trip.py trips/killarney-2026-05/ 2>&1 | tail -3
```

Expected: build succeeds quickly (~2-3s). Trip HTML now uses yellow paths where applicable, centroid curves elsewhere.

- [ ] **Step 5: Run the audit**

```bash
python3 scripts/audit_route_water.py --source both 2>&1 | tail -20
```

Expected: in-water % per paddle leg should be ≥ before (visibility-graph baseline was ~80-100% on most paddle legs). Yellow-path-using legs should hit close to 100%.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add paths_palette.yaml jeffs_canoe_paths.json trips/killarney-2026-05/trip.html
git commit -m "feat: extract Jeff's yellow canoe paths + regenerate trip with new routing"
```

---

## Task 12: Delete visibility-graph code from route_engine

Now that everything works without the visibility-graph helpers, remove them.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/route_engine.py`

- [ ] **Step 1: Confirm the helpers have no other callers**

```bash
cd /Users/alex/Documents/camping-planner
grep -n "_polygon_aware_paddle\|_line_inside_polygon\|_line_inside_any_polygon\|_polygons_overlapping_corridor\|_decimate_polygon\|_PADDLE_MAX_POLYGON_VERTICES" \
  $(find . -name "*.py" -not -path "./.venv/*" -not -path "./tests/test_route_engine.py")
```

Expected: ONLY `route_engine.py` matches (the function definitions themselves). If anything else matches, do not delete; investigate.

- [ ] **Step 2: Delete the visibility-graph functions**

In `/Users/alex/Documents/camping-planner/route_engine.py`, delete (in this order):

- `_PADDLE_MAX_POLYGON_VERTICES` constant
- `_decimate_polygon` function
- `_line_inside_polygon` function
- `_line_inside_any_polygon` function
- `_polygons_overlapping_corridor` function
- `_polygon_aware_paddle` function

(Total: ~180 lines deleted.)

KEEP:
- `_point_in_polygon` — still used by `_yellow_paths_in_lake` and other helpers
- `_haversine_km`
- `_path_distance_km`

- [ ] **Step 3: Update tests to remove dead references**

```bash
cd /Users/alex/Documents/camping-planner
grep -n "_polygon_aware_paddle\|_line_inside_polygon\|_polygons_overlapping_corridor\|_decimate_polygon" tests/test_route_engine.py
```

If any tests reference deleted helpers, delete those tests too. Tests for `_point_in_polygon` and `_haversine_km` stay.

- [ ] **Step 4: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ --ignore=tests/test_routes.py -q 2>&1 | tail -3
```

Expected: all tests pass.

- [ ] **Step 5: Quick smoke check**

```bash
time python3 build_trip.py trips/killarney-2026-05/ 2>&1 | tail -3
```

Expected: clean build, comparable timing to Task 11's run.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add route_engine.py tests/test_route_engine.py
git commit -m "chore: delete visibility-graph code (replaced by paddle_router)"
```

---

## Task 13: Final integration check + overlay refresh + commit

End-to-end verification: refresh the overlay, push to the branch, sanity-check trip stats.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_osm_overlay.html`
- Modify: `/Users/alex/Documents/camping-planner/jeffs_osm_overlay_raster.jpg`

- [ ] **Step 1: Refresh the overlay**

```bash
cd /Users/alex/Documents/camping-planner
python3 scripts/overlay_osm_jeffs.py \
  --kmz "/Users/alex/Documents/camping-planner/Maps by Jeff - Full French River and Killarney Paddling Map v4.0 - Google Earth.kmz" \
  --bbox 46.00,-81.62,46.10,-81.32 \
  --zoom-raster 6 \
  --trip trips/killarney-2026-05/ \
  --out jeffs_osm_overlay.html 2>&1 | tail -5
```

- [ ] **Step 2: Open in browser and visually verify**

```bash
open "http://localhost:8000/jeffs_osm_overlay.html"
```

(Assumes the http.server we kept running earlier is still up. If not: `python3 -m http.server 8000 &`.)

Verify:
- Trip route paddle segments visibly hug yellow-line paths where Jeff drew them.
- On lakes without yellow lines, paddle segments are smooth Bezier curves through the lake interior (not straight lines, not jagged visibility-graph polylines).
- Approx legs (Baie Fine area) unchanged — still red dashed.
- No splines bowing into land (the densely-sampled curves ARE the geometry now; no client-side smoothing).

- [ ] **Step 3: Run the water-coverage audit one more time**

```bash
python3 scripts/audit_route_water.py --source both 2>&1 | tail -20
```

Expected: per-leg in-water % ≥ baseline (Task 11). If some legs regressed, note in concerns.

- [ ] **Step 4: Commit + push**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_osm_overlay.html jeffs_osm_overlay_raster.jpg
git commit -m "chore: refresh overlay with new paddle_router geometry"
git push
```

---

## Verification checklist (after Task 13)

- [ ] `python3 -m pytest tests/ --ignore=tests/test_routes.py -q` shows all tests passing
- [ ] `paddle_router.py` exists and is ~250 lines
- [ ] `jeffs_paths_extractor.py` exists and is ~300 lines
- [ ] `jeffs_canoe_paths.json` is committed and < 500 KB
- [ ] `route_engine.py` no longer contains `_polygon_aware_paddle` or visibility-graph helpers
- [ ] `time python3 build_trip.py trips/killarney-2026-05/` < 5 seconds
- [ ] Audit total in-water % ≥ 65% (Task 11 baseline)
- [ ] Trip page renders with smooth paddle curves (no spline rendering, no overshoot, no knots)

If all 8 pass, the rebuild is complete.
