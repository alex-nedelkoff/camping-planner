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

    # Day 1 (access -> night 1): same lake, single paddle.
    # Day 2 (night 1 -> night 2): same lake, single paddle.
    # Day 3 (return): same lake, single paddle.
    assert len(paddle_segs) == 3
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


def test_build_route_no_portage_falls_back_to_approx():
    # Two lakes in the OSM data, but NO portage between them.
    osm = _synthetic_osm()
    osm["portages"] = []  # strip the portage

    nights = [
        {"date": "2026-05-15", "site": "1", "location": "Alpha Lake"},
        {"date": "2026-05-16", "site": "2", "location": "Beta Lake"},
    ]
    out = build_route(nights=nights, access_point="Alpha Lake", osm=osm)

    approx = [s for s in out["segments"] if s["kind"] == "approx"]
    # Two approx legs: outbound (Alpha->Beta) AND return (Beta->Alpha access),
    # neither has a connecting portage in this fixture.
    assert len(approx) == 2
    assert approx[0]["from"].startswith("Alpha")
    assert approx[0]["to"].startswith("Beta")
    assert any("no portage" in w.lower() for w in out["warnings"])


def test_build_route_unknown_lake_name_falls_back_to_approx():
    osm = _synthetic_osm()
    nights = [
        {"date": "2026-05-15", "site": "1", "location": "Alpha Lake"},
        {"date": "2026-05-16", "site": "2", "location": "Mystery Lake"},  # not in OSM
    ]
    out = build_route(nights=nights, access_point="Alpha Lake", osm=osm)

    approx = [s for s in out["segments"] if s["kind"] == "approx"]
    assert len(approx) >= 1
    assert any("Mystery" in w or "could not resolve" in w.lower()
               for w in out["warnings"])


from route_engine import (
    estimate_minutes,
    format_human_time,
    build_day_estimates,
)


def test_estimate_minutes_paddle_only():
    # 4 km at 4 km/h = 60 min, +15% buffer = 69 min, rounds to 69 (no 5-min round here).
    assert estimate_minutes(paddle_km=4.0, portage_km=0.0) == 69


def test_estimate_minutes_portage_only():
    # 1 km portage with 3 traversals at 2 km/h = 90 min, +15% = 103.5 -> 104.
    assert estimate_minutes(paddle_km=0.0, portage_km=1.0) == 104


def test_estimate_minutes_combined():
    # 2 km paddle (30 min) + 0.5 km portage (45 min) = 75 min, +15% = 86.25 -> 86.
    assert estimate_minutes(paddle_km=2.0, portage_km=0.5) == 86


def test_format_human_time_under_an_hour():
    assert format_human_time(45) == "45m"


def test_format_human_time_rounds_to_5_min():
    # 67 -> nearest 5 = 65 -> "1h 5m"
    assert format_human_time(67) == "1h 5m"


def test_format_human_time_exact_hour():
    assert format_human_time(60) == "1h 0m"


def test_build_day_estimates_aggregates_per_day():
    segments = [
        # Day 1: paddle 5 km same-lake.
        {"day": "Fri 2026-05-15", "kind": "paddle", "from": "X", "to": "Y",
         "distance_km": 5.0, "geometry": []},
        # Day 2: paddle + portage + paddle (split leg).
        {"day": "Sat 2026-05-16", "kind": "paddle", "from": "Y", "to": "P-in",
         "distance_km": 3.0, "geometry": []},
        {"day": "Sat 2026-05-16", "kind": "portage", "from": "P-in", "to": "P-out",
         "distance_km": 0.4, "geometry": []},
        {"day": "Sat 2026-05-16", "kind": "paddle", "from": "P-out", "to": "Z",
         "distance_km": 4.0, "geometry": []},
    ]
    days = build_day_estimates(segments)

    assert len(days) == 2
    assert days[0]["paddle_km"] == 5.0
    assert days[0]["portage_km"] == 0.0
    assert days[0]["approx"] is False
    assert days[1]["paddle_km"] == 7.0
    assert days[1]["portage_km"] == 0.4
    # day1 label is start->end of the day's segments.
    assert days[1]["label"].startswith("Y")  # from first segment's from
    assert days[1]["label"].endswith("Z")    # to last segment's to


def test_build_day_estimates_marks_approx_days():
    segments = [
        {"day": "Fri 2026-05-15", "kind": "approx", "from": "X", "to": "Y",
         "distance_km": 5.0, "geometry": []},
    ]
    days = build_day_estimates(segments)
    assert days[0]["approx"] is True


def test_build_route_uses_access_point_gps_for_first_and_last_legs():
    """First/last paddle endpoints use KILLARNEY_ACCESS_POINTS GPS, not the
    access lake's centroid."""
    osm = {
        "lakes": [
            {
                "name": "George Lake",
                "polygon": [
                    [46.00, -81.39], [46.00, -81.41],
                    [46.05, -81.41], [46.05, -81.39],
                    [46.00, -81.39],
                ],
                "centroid": [46.025, -81.40],  # offset from access GPS
            },
            {
                "name": "Killarney Lake",
                "polygon": [
                    [46.04, -81.34], [46.04, -81.36],
                    [46.07, -81.36], [46.07, -81.34],
                    [46.04, -81.34],
                ],
                "centroid": [46.055, -81.35],
            },
        ],
        "portages": [
            {
                "name": "test portage",
                "line": [[46.04, -81.40], [46.05, -81.36]],
                "length_km": 4.5,
                "endpoints": [[46.04, -81.40], [46.05, -81.36]],
            },
        ],
    }
    nights = [
        {"date": "2026-05-15", "site": "1", "location": "Killarney Lake"},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)
    paddle_segs = [s for s in out["segments"] if s["kind"] == "paddle"]
    # First paddle starts at access GPS, not George Lake centroid.
    first_start = paddle_segs[0]["geometry"][0]
    assert first_start == [46.0150, -81.4049]
    # Last paddle ends at access GPS, not George Lake centroid.
    last_end = paddle_segs[-1]["geometry"][-1]
    assert last_end == [46.0150, -81.4049]


def test_build_route_marker_uses_gps_override_when_present():
    """A `gps:` field on a night entry overrides the lake-centroid marker."""
    osm = {
        "lakes": [
            {
                "name": "George Lake",
                "polygon": [
                    [46.00, -81.39], [46.00, -81.41],
                    [46.05, -81.41], [46.05, -81.39],
                    [46.00, -81.39],
                ],
                "centroid": [46.025, -81.40],
            },
        ],
        "portages": [],
    }
    nights = [
        {"date": "2026-05-15", "site": "5", "location": "George Lake",
         "gps": [46.0312, -81.3998]},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)
    site_markers = [m for m in out.get("markers", []) if m["kind"] == "site"]
    assert len(site_markers) == 1
    # Uses the override, not the centroid.
    assert site_markers[0]["lat"] == 46.0312
    assert site_markers[0]["lon"] == -81.3998
    # Label drops the "(lake center)" hint when GPS is provided.
    assert "lake center" not in site_markers[0]["label"]


def test_build_route_emits_markers_for_access_and_each_night():
    osm = {
        "lakes": [
            {
                "name": "George Lake",
                "polygon": [
                    [46.00, -81.39], [46.00, -81.41],
                    [46.05, -81.41], [46.05, -81.39],
                    [46.00, -81.39],
                ],
                "centroid": [46.025, -81.40],
            },
        ],
        "portages": [],
    }
    nights = [
        {"date": "2026-05-15", "site": "7", "location": "George Lake"},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)
    markers = out.get("markers", [])
    assert len(markers) == 2
    access = [m for m in markers if m["kind"] == "access"][0]
    site = [m for m in markers if m["kind"] == "site"][0]
    assert access["lat"] == 46.0150 and access["lon"] == -81.4049
    assert "Site 7" in site["label"]
    assert "lake center" in site["label"]


def test_build_route_resolves_site_gps_from_campsites_when_no_override():
    """Campsite extracted from Jeff's data fills in the marker GPS by ref+lake."""
    osm = {
        "lakes": [
            {"name": "OSA Lake",
             "polygon": [[46.05, -81.40], [46.05, -81.38],
                         [46.07, -81.38], [46.07, -81.40],
                         [46.05, -81.40]],
             "centroid": [46.06, -81.39]},
        ],
        "portages": [],
        "campsites": [
            {"ref": "61", "lake": "OSA Lake", "gps": [46.063, -81.392]},
        ],
    }
    nights = [
        {"date": "2026-05-15", "site": "61", "location": "OSA Lake"},
        # No gps: override.
    ]
    out = build_route(nights=nights, access_point="OSA Lake", osm=osm)
    site_marker = [m for m in out["markers"] if m["kind"] == "site"][0]
    # Marker should be at the campsite GPS, not the OSA Lake centroid.
    assert abs(site_marker["lat"] - 46.063) < 1e-4
    assert abs(site_marker["lon"] - -81.392) < 1e-4


def test_build_route_frontmatter_gps_wins_over_campsite():
    osm = {
        "lakes": [
            {"name": "OSA Lake",
             "polygon": [[46.05, -81.40], [46.05, -81.38],
                         [46.07, -81.38], [46.07, -81.40],
                         [46.05, -81.40]],
             "centroid": [46.06, -81.39]},
        ],
        "portages": [],
        "campsites": [
            {"ref": "61", "lake": "OSA Lake", "gps": [46.063, -81.392]},
        ],
    }
    nights = [
        {"date": "2026-05-15", "site": "61", "location": "OSA Lake",
         "gps": [99.0, -99.0]},  # explicit override
    ]
    out = build_route(nights=nights, access_point="OSA Lake", osm=osm)
    site_marker = [m for m in out["markers"] if m["kind"] == "site"][0]
    # Frontmatter override wins.
    assert site_marker["lat"] == 99.0
    assert site_marker["lon"] == -99.0


def test_build_route_resolves_site_gps_from_gpx_campsites():
    """When osm['campsites'] is GPX-shaped (name + lat + lon), the route
    engine looks up the night's site number and uses that GPS instead of
    falling back to the lake centroid."""
    osm = {
        "lakes": [
            {"name": "Killarney Lake",
             "polygon": [[46.05, -81.36], [46.05, -81.38],
                         [46.07, -81.38], [46.07, -81.36],
                         [46.05, -81.36]],
             "centroid": [46.06, -81.37]},
        ],
        "portages": [],
        "campsites": [
            {"name": "61", "lat": 46.05199, "lon": -81.36224,
             "desc": "Killarney 61"},
        ],
    }
    nights = [
        {"date": "2026-06-01", "site": "61", "location": "Killarney Lake"},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)
    site_markers = [m for m in out.get("markers", []) if m["kind"] == "site"]
    assert len(site_markers) == 1
    # Marker GPS comes from GPX campsite, not the lake centroid (46.06, -81.37).
    assert abs(site_markers[0]["lat"] - 46.05199) < 1e-5
    assert abs(site_markers[0]["lon"] - -81.36224) < 1e-5


def test_build_route_falls_back_to_centroid_when_site_not_in_campsites():
    """If the night's site number isn't found in osm['campsites'], the route
    engine falls back to the lake centroid (existing behavior preserved)."""
    osm = {
        "lakes": [
            {"name": "Killarney Lake",
             "polygon": [[46.05, -81.36], [46.05, -81.38],
                         [46.07, -81.38], [46.07, -81.36],
                         [46.05, -81.36]],
             "centroid": [46.06, -81.37]},
        ],
        "portages": [],
        "campsites": [
            {"name": "99", "lat": 46.0, "lon": -81.0, "desc": "Wrong site"},
        ],
    }
    nights = [
        {"date": "2026-06-01", "site": "61", "location": "Killarney Lake"},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)
    site_markers = [m for m in out.get("markers", []) if m["kind"] == "site"]
    assert len(site_markers) == 1
    # Falls back to the centroid.
    assert site_markers[0]["lat"] == 46.06
    assert site_markers[0]["lon"] == -81.37
