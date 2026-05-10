"""Tests for route_engine.py."""
from route_engine import (
    _norm_lake_name,
    _point_in_polygon,
    _haversine_km,
)


def test_norm_lake_name_strips_punctuation_and_lake_suffix():
    assert _norm_lake_name("OSA Lake") == "OSA"
    assert _norm_lake_name("O.S.A. Lake") == "OSA"
    assert _norm_lake_name("osa") == "OSA"
    assert _norm_lake_name("Killarney Lake") == "KILLARNEY"
    assert _norm_lake_name("Baie-Fine") == "BAIEFINE"
    assert _norm_lake_name("Baie Fine") == "BAIE FINE"


def test_point_in_polygon_inside():
    # Unit square (0,0)-(1,1).
    poly = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    assert _point_in_polygon([0.5, 0.5], poly) is True


def test_point_in_polygon_outside():
    poly = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    assert _point_in_polygon([1.5, 0.5], poly) is False
    assert _point_in_polygon([-0.1, 0.5], poly) is False


def test_point_in_polygon_handles_concave_polygon():
    # L-shape: outer hull goes around a notch.
    poly = [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2], [0, 0]]
    # Point in the notch (outside the L) should return False.
    assert _point_in_polygon([1.5, 1.5], poly) is False
    # Point inside the L's bottom arm.
    assert _point_in_polygon([0.5, 0.5], poly) is True


def test_haversine_km_zero_for_same_point():
    assert _haversine_km([46.0, -81.0], [46.0, -81.0]) == 0.0


def test_haversine_km_one_degree_lat():
    # 1 degree of latitude is ~111 km.
    d = _haversine_km([46.0, -81.0], [47.0, -81.0])
    assert 110 < d < 112
