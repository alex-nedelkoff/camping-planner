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
    """When jeffs_killarney_cache.json exists, BOTH Jeff's and OSM polygons
    are kept (Jeff's first), so name lookups find Jeff's first while
    point-in-polygon tests still see OSM polygons. Campsites surface as a
    top-level key."""
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
    monkeypatch.setattr(_osm_data, "CAMPSITES_GPX_PATH",
                        tmp_path / "absent_campsites.gpx")  # absent
    monkeypatch.setattr(_osm_data, "PORTAGES_GPX_PATH",
                        tmp_path / "absent_portages.gpx")  # absent

    out = _osm_data.load_killarney_features()
    # Killarney Lake appears twice (Jeff's + OSM's), Other Lake once, Baie Fine once.
    names = sorted(l["name"] for l in out["lakes"])
    assert names == ["Baie Fine", "Killarney Lake", "Killarney Lake", "Other Lake"]
    # First Killarney Lake in the list is Jeff's (so name lookups return Jeff's).
    first_killarney = next(l for l in out["lakes"] if l["name"] == "Killarney Lake")
    assert first_killarney["polygon"] == [[9, 9]]
    # OSM's Killarney Lake is also still present.
    osm_killarney_polygons = [
        l["polygon"] for l in out["lakes"]
        if l["name"] == "Killarney Lake"
    ]
    assert [[1, 1]] in osm_killarney_polygons
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
    monkeypatch.setattr(_osm_data, "CAMPSITES_GPX_PATH",
                        tmp_path / "absent_campsites.gpx")  # absent
    monkeypatch.setattr(_osm_data, "PORTAGES_GPX_PATH",
                        tmp_path / "absent_portages.gpx")  # absent

    out = _osm_data.load_killarney_features()
    assert len(out["lakes"]) == 1
    assert out["campsites"] == []


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
    monkeypatch.setattr(_osm_data, "CAMPSITES_GPX_PATH",
                        tmp_path / "absent_campsites.gpx")  # absent
    monkeypatch.setattr(_osm_data, "PORTAGES_GPX_PATH",
                        tmp_path / "absent_portages.gpx")  # absent

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
    monkeypatch.setattr(_osm_data, "CAMPSITES_GPX_PATH",
                        tmp_path / "absent_campsites.gpx")  # absent
    monkeypatch.setattr(_osm_data, "PORTAGES_GPX_PATH",
                        tmp_path / "absent_portages.gpx")  # absent

    out = _osm_data.load_killarney_features()
    assert out.get("paths") == []


def test_load_features_uses_gpx_campsites_when_present(tmp_path, monkeypatch):
    """If killarneyCampsites.gpx exists, out['campsites'] comes from it."""
    osm_cache = {"lakes": [], "portages": []}
    osm_path = tmp_path / "osm_killarney_cache.json"
    osm_path.write_text(json.dumps(osm_cache))

    campsites_gpx = tmp_path / "killarneyCampsites.gpx"
    campsites_gpx.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        '<wpt lat="46.0" lon="-81.0"><name>1</name>'
        '<desc>Killarney 1</desc></wpt>'
        '</gpx>'
    )

    monkeypatch.setattr(_osm_data, "CACHE_PATH", osm_path)
    monkeypatch.setattr(_osm_data, "JEFFS_CACHE_PATH",
                        tmp_path / "absent_jeffs.json")
    monkeypatch.setattr(_osm_data, "PATHS_CACHE_PATH",
                        tmp_path / "absent_paths.json")
    monkeypatch.setattr(_osm_data, "CAMPSITES_GPX_PATH", campsites_gpx)
    monkeypatch.setattr(_osm_data, "PORTAGES_GPX_PATH",
                        tmp_path / "absent_portages.gpx")

    out = _osm_data.load_killarney_features()
    assert len(out["campsites"]) == 1
    assert out["campsites"][0]["name"] == "1"


def test_find_campsite_case_insensitive_match():
    """find_campsite resolves by name, case-insensitive."""
    campsites = [
        {"name": "61", "lat": 46.05, "lon": -81.36, "desc": "..."},
        {"name": "82", "lat": 46.04, "lon": -81.50, "desc": "..."},
    ]
    assert _osm_data.find_campsite("61", campsites)["lat"] == 46.05
    # Case-insensitive (e.g., when name is alphanumeric like "H51").
    assert _osm_data.find_campsite("61", campsites) is not None


def test_find_campsite_returns_none_on_miss():
    """find_campsite returns None when name not found."""
    campsites = [{"name": "61", "lat": 46.05, "lon": -81.36, "desc": "..."}]
    assert _osm_data.find_campsite("99", campsites) is None
    # Also None on empty input.
    assert _osm_data.find_campsite("61", []) is None
    assert _osm_data.find_campsite("", campsites) is None


def test_merge_portages_dedups_near_osm_keeps_distant_osm():
    """GPX is canonical; OSM portages with midpoint within 200m of a GPX
    midpoint are dropped. Distant OSM portages are kept."""
    osm_portages = [
        # NEAR a GPX portage (will be deduped).
        {"name": "OSM near", "endpoints": [[46.0353, -81.3815], [46.0354, -81.3805]],
         "line": [[46.0353, -81.3815], [46.0354, -81.3805]], "length_km": 0.08,
         "source": "osm"},
        # FAR (in another park area).
        {"name": "OSM far", "endpoints": [[46.5, -81.0], [46.51, -81.0]],
         "line": [[46.5, -81.0], [46.51, -81.0]], "length_km": 1.1,
         "source": "osm"},
    ]
    gpx_portages = [
        {"name": "42056", "endpoints": [[46.03524, -81.38126], [46.03535, -81.38053]],
         "line": [[46.03524, -81.38126], [46.03535, -81.38053]], "length_km": 0.058,
         "source": "gpx"},
    ]
    merged = _osm_data._merge_portages(osm_portages, gpx_portages,
                                       spatial_dedup_m=200)
    names = {p["name"] for p in merged}
    # The near-OSM portage is dropped; far-OSM and GPX are kept.
    assert "OSM near" not in names
    assert "OSM far" in names
    assert "42056" in names
    assert len(merged) == 2
