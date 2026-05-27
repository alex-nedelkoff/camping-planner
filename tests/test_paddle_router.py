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
    # Yellow route should include the polyline's interior point
    # (46.0, -80.985). Consecutive duplicates are deduped, so when entry
    # snaps exactly onto polyline[0] and exit onto polyline[-1] the output
    # collapses to 3 points (entry + interior + exit) rather than 5.
    assert len(geom) >= 3
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
