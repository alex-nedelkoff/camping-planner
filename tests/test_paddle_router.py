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


def test_fit_paddle_curve_retries_with_lower_pull_when_curve_leaves_polygon():
    """U-shaped polygon where 0.4 pull dips into the notch; retry to a lower
    pull eventually finds a curve (or the straight line) that stays inside.
    """
    # U-shape (upside down): outer rectangle minus a notch from the bottom.
    # Vertices ordered counter-clockwise.
    poly = [
        [0.000, 0.000], [0.000, 1.000],
        [1.000, 1.000], [1.000, 0.000],
        [0.700, 0.000], [0.700, 0.700],
        [0.300, 0.700], [0.300, 0.000],
        [0.000, 0.000],
    ]
    # Centroid placed in the NOTCH so 0.4 pull arcs the curve into it.
    lake = {"polygon": poly, "centroid": [0.5, 0.35]}
    # Entry/exit at the TOPS of the arms — straight line at y=0.9 is
    # above the notch top (y=0.7), so pull=0 is a valid escape hatch.
    entry = [0.1, 0.9]
    exit = [0.9, 0.9]
    geom = fit_paddle_curve(entry, exit, lake)
    # Endpoints preserved exactly.
    assert geom[0] == [entry[0], entry[1]]
    assert geom[-1] == [exit[0], exit[1]]
    # Final geometry's intermediate samples must all be inside the polygon.
    for pt in geom[1:-1]:
        assert _point_in_polygon(pt, poly), \
            f"Final geometry leaves polygon at {pt}"
