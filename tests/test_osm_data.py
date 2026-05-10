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


def test_parse_extracts_multipolygon_relation():
    """Killarney's major lakes are tagged as multipolygon relations, not simple ways."""
    data = {
        "version": 0.6,
        "elements": [
            {
                "type": "relation",
                "id": 100,
                "tags": {
                    "natural": "water",
                    "name": "Big Lake",
                    "type": "multipolygon",
                },
                "members": [
                    {
                        "type": "way",
                        "ref": 200,
                        "role": "outer",
                        "geometry": [
                            {"lat": 46.0, "lon": -81.0},
                            {"lat": 46.0, "lon": -81.1},
                            {"lat": 46.1, "lon": -81.1},
                            {"lat": 46.1, "lon": -81.0},
                            {"lat": 46.0, "lon": -81.0},
                        ],
                    },
                    {
                        "type": "way",
                        "ref": 201,
                        "role": "inner",  # an island, ignored
                        "geometry": [
                            {"lat": 46.04, "lon": -81.05},
                            {"lat": 46.06, "lon": -81.05},
                            {"lat": 46.06, "lon": -81.04},
                            {"lat": 46.04, "lon": -81.05},
                        ],
                    },
                ],
            },
        ],
    }
    out = _parse_overpass_response(data)
    assert len(out["lakes"]) == 1
    lake = out["lakes"][0]
    assert lake["name"] == "Big Lake"
    # Polygon is from the outer member, not the inner island.
    assert len(lake["polygon"]) == 5  # 5 points incl. closure
    cx, cy = lake["centroid"]
    assert 45.99 < cx < 46.11
    assert -81.11 < cy < -80.99


import json

import osm_data as _osm_data


def test_load_features_merges_jeffs_when_present(tmp_path, monkeypatch):
    """When jeffs_killarney_cache.json exists, its lakes win on name conflict
    and its campsites surface as a top-level key."""
    osm_cache = {
        "lakes": [
            {"name": "Killarney Lake", "polygon": [[1, 1]], "centroid": [46.05, -81.40]},
            {"name": "Other Lake", "polygon": [[2, 2]], "centroid": [46.0, -81.5]},
        ],
        "portages": [{"name": "X", "line": [[0, 0]], "length_km": 1.0,
                      "endpoints": [[0, 0], [1, 1]]}],
    }
    jeffs_cache = {
        "lakes": [
            {"name": "Killarney Lake", "polygon": [[9, 9]], "centroid": [46.05, -81.40]},
            {"name": "Baie Fine", "polygon": [[8, 8]], "centroid": [46.02, -81.51]},
        ],
        "campsites": [
            {"ref": "61", "lake": "OSA Lake", "gps": [46.063, -81.392]},
        ],
    }
    osm_path = tmp_path / "osm_killarney_cache.json"
    jeffs_path = tmp_path / "jeffs_killarney_cache.json"
    osm_path.write_text(json.dumps(osm_cache))
    jeffs_path.write_text(json.dumps(jeffs_cache))

    monkeypatch.setattr(_osm_data, "CACHE_PATH", osm_path)
    monkeypatch.setattr(_osm_data, "JEFFS_CACHE_PATH", jeffs_path)

    out = _osm_data.load_killarney_features()
    names = sorted(l["name"] for l in out["lakes"])
    # Killarney Lake from Jeff's wins; Other Lake (OSM-only) preserved;
    # Baie Fine added.
    assert names == ["Baie Fine", "Killarney Lake", "Other Lake"]
    killarney = next(l for l in out["lakes"] if l["name"] == "Killarney Lake")
    # Verify Jeff's polygon, not OSM's.
    assert killarney["polygon"] == [[9, 9]]
    # Campsites surfaced.
    assert out["campsites"] == jeffs_cache["campsites"]
    # Portages still from OSM.
    assert len(out["portages"]) == 1


def test_load_features_works_without_jeffs(tmp_path, monkeypatch):
    osm_cache = {
        "lakes": [{"name": "X", "polygon": [[1, 1]], "centroid": [0, 0]}],
        "portages": [],
    }
    osm_path = tmp_path / "osm_killarney_cache.json"
    jeffs_path = tmp_path / "jeffs_killarney_cache.json"  # does NOT exist
    osm_path.write_text(json.dumps(osm_cache))

    monkeypatch.setattr(_osm_data, "CACHE_PATH", osm_path)
    monkeypatch.setattr(_osm_data, "JEFFS_CACHE_PATH", jeffs_path)

    out = _osm_data.load_killarney_features()
    assert len(out["lakes"]) == 1
    assert out["campsites"] == []
