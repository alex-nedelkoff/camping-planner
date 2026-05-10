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


from route_engine import build_route


def _synthetic_osm():
    """Two square lakes connected by one portage."""
    # Lake A: square from lat 46.00..46.01, lon -81.02..-81.01
    lake_a = {
        "name": "Alpha Lake",
        "polygon": [
            [46.00, -81.02], [46.00, -81.01],
            [46.01, -81.01], [46.01, -81.02],
            [46.00, -81.02],
        ],
        "centroid": [46.005, -81.015],
    }
    # Lake B: square from lat 46.00..46.01, lon -81.00..-80.99
    lake_b = {
        "name": "Beta Lake",
        "polygon": [
            [46.00, -81.00], [46.00, -80.99],
            [46.01, -80.99], [46.01, -81.00],
            [46.00, -81.00],
        ],
        "centroid": [46.005, -80.995],
    }
    # Portage: starts inside Lake A, ends inside Lake B.
    portage = {
        "name": "A-B Portage",
        "line": [[46.005, -81.012], [46.005, -80.998]],
        "length_km": 1.08,
        "endpoints": [[46.005, -81.012], [46.005, -80.998]],
    }
    return {"lakes": [lake_a, lake_b], "portages": [portage]}


def test_build_route_same_lake_emits_one_paddle_segment():
    osm = _synthetic_osm()
    nights = [
        {"date": "2026-05-15", "site": "1", "location": "Alpha Lake"},
        {"date": "2026-05-16", "site": "2", "location": "Alpha Lake"},
    ]
    out = build_route(nights=nights, access_point="Alpha Lake", osm=osm)

    paddle_segs = [s for s in out["segments"] if s["kind"] == "paddle"]
    portage_segs = [s for s in out["segments"] if s["kind"] == "portage"]

    # Day 1 (access -> night 1): same lake, single paddle segment.
    # Day 2 (night 1 -> night 2): same lake, single paddle segment.
    assert len(paddle_segs) == 2
    assert len(portage_segs) == 0
    assert out["warnings"] == []


def test_build_route_two_lakes_with_portage_emits_paddle_portage_paddle():
    osm = _synthetic_osm()
    nights = [
        {"date": "2026-05-15", "site": "1", "location": "Alpha Lake"},
        {"date": "2026-05-16", "site": "2", "location": "Beta Lake"},
    ]
    out = build_route(nights=nights, access_point="Alpha Lake", osm=osm)

    # Day 1: Alpha access -> Alpha night 1, single paddle (same lake).
    # Day 2: Alpha -> Beta crossing the portage = paddle, portage, paddle.
    day2 = [s for s in out["segments"] if s["day"].startswith("Sat") or "2026-05-16" in s["day"]]
    kinds = [s["kind"] for s in day2]
    assert kinds == ["paddle", "portage", "paddle"]
    # Portage segment uses the OSM line geometry.
    portage_seg = [s for s in day2 if s["kind"] == "portage"][0]
    assert portage_seg["distance_km"] == 1.08
    assert out["warnings"] == []
