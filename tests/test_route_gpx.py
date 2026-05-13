import pytest

from app.services import route_gpx


def test_render_then_parse_round_trips_waypoints(tmp_path):
    wpts = [
        {"lat": 46.013600, "lon": -81.404900, "name": "George Lake put-in"},
        {"lat": 46.020000, "lon": -81.410000, "name": ""},
        {"lat": 46.044041, "lon": -81.503845, "name": "Camp — night 2 & lunch"},
    ]
    gpx = route_gpx.render_gpx(wpts)
    back = route_gpx.parse_gpx(gpx)
    assert back == wpts


def test_render_is_deterministic_for_the_same_input():
    wpts = [
        {"lat": 46.01, "lon": -81.40, "name": "A"},
        {"lat": 46.02, "lon": -81.41, "name": "B"},
    ]
    assert route_gpx.render_gpx(wpts) == route_gpx.render_gpx(wpts)


def test_render_includes_trk_only_when_two_or_more_waypoints():
    one = route_gpx.render_gpx([{"lat": 46.0, "lon": -81.0, "name": "Solo"}])
    assert "<trk>" not in one
    two = route_gpx.render_gpx(
        [
            {"lat": 46.0, "lon": -81.0, "name": "A"},
            {"lat": 46.1, "lon": -81.1, "name": "B"},
        ]
    )
    assert "<trk>" in two
    assert two.count("<trkpt") == 2


def test_render_escapes_xml_in_names():
    gpx = route_gpx.render_gpx([{"lat": 1.0, "lon": 2.0, "name": 'A & "B" <C>'}])
    assert "A &amp; &quot;B&quot; &lt;C&gt;" in gpx


def test_save_and_load_waypoints_round_trip(tmp_path):
    wpts = [
        {"lat": 46.0, "lon": -81.0, "name": "X"},
        {"lat": 46.1, "lon": -81.1, "name": "Y"},
    ]
    saved = route_gpx.save_waypoints(tmp_path, wpts)
    assert saved == tmp_path / "route.gpx"
    assert route_gpx.load_waypoints(tmp_path) == wpts


def test_load_waypoints_returns_empty_when_no_file(tmp_path):
    assert route_gpx.load_waypoints(tmp_path) == []


def test_total_distance_km_zero_for_empty_or_single():
    assert route_gpx.total_distance_km([]) == 0.0
    assert route_gpx.total_distance_km([{"lat": 0.0, "lon": 0.0}]) == 0.0


def test_total_distance_km_haversine_against_known_pair():
    # George Lake put-in → Killarney Lake centroid, ~9 km airline.
    pts = [
        {"lat": 46.0136, "lon": -81.4049},
        {"lat": 46.0850, "lon": -81.4150},
    ]
    d = route_gpx.total_distance_km(pts)
    assert 7.5 < d < 9.0, d


def test_route_map_parse_route_file_consumes_our_output(tmp_path):
    """Sanity-check: build_trip.py's existing parser handles our GPX format."""
    import route_map

    wpts = [
        {"lat": 46.01, "lon": -81.40, "name": "Put-in"},
        {"lat": 46.05, "lon": -81.45, "name": "Camp 1"},
    ]
    path = route_gpx.save_waypoints(tmp_path, wpts)
    parsed = route_map.parse_route_file(str(path))
    assert len(parsed["waypoints"]) == 2
    assert parsed["waypoints"][0]["name"] == "Put-in"
    assert parsed["tracks"] and len(parsed["tracks"][0]["points"]) == 2
