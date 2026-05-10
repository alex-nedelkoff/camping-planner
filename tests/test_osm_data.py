"""Tests for osm_data.py (parser only — no live network calls)."""
from osm_data import _parse_overpass_response


# A trimmed Overpass response with one lake (closed way) + one portage (open way).
_SAMPLE = {
    "version": 0.6,
    "elements": [
        {
            "type": "way",
            "id": 1,
            "tags": {"natural": "water", "name": "Test Lake"},
            "geometry": [
                {"lat": 46.00, "lon": -81.00},
                {"lat": 46.00, "lon": -81.01},
                {"lat": 46.01, "lon": -81.01},
                {"lat": 46.01, "lon": -81.00},
                {"lat": 46.00, "lon": -81.00},  # closed
            ],
        },
        {
            "type": "way",
            "id": 2,
            "tags": {"portage": "yes", "name": "Test Portage"},
            "geometry": [
                {"lat": 46.005, "lon": -81.012},
                {"lat": 46.005, "lon": -81.020},
            ],
        },
        {
            # Unnamed un-tagged way that should be filtered out.
            "type": "way",
            "id": 3,
            "tags": {"highway": "residential"},
            "geometry": [
                {"lat": 46.0, "lon": -81.0},
                {"lat": 46.0, "lon": -80.99},
            ],
        },
    ],
}


def test_parse_extracts_lake():
    out = _parse_overpass_response(_SAMPLE)
    assert len(out["lakes"]) == 1
    lake = out["lakes"][0]
    assert lake["name"] == "Test Lake"
    assert len(lake["polygon"]) == 5  # closed ring preserved
    # Centroid should be near the lake center.
    cx, cy = lake["centroid"]
    assert 45.99 < cx < 46.02
    assert -81.02 < cy < -80.99


def test_parse_extracts_portage_with_endpoints_and_length():
    out = _parse_overpass_response(_SAMPLE)
    assert len(out["portages"]) == 1
    p = out["portages"][0]
    assert p["name"] == "Test Portage"
    assert p["endpoints"][0] == [46.005, -81.012]
    assert p["endpoints"][1] == [46.005, -81.020]
    # Portage length: ~0.008 deg longitude at lat 46 ≈ 0.6 km.
    assert 0.4 < p["length_km"] < 0.8


def test_parse_filters_unrelated_ways():
    out = _parse_overpass_response(_SAMPLE)
    # The highway=residential way must NOT appear in lakes or portages.
    assert all(l["name"] != "" for l in out["lakes"])  # no empty/unnamed
    assert "lakes" in out and "portages" in out
    # Verify the residential way was dropped.
    assert len(out["lakes"]) + len(out["portages"]) == 2
