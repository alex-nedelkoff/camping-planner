"""GeoJSON conversion of cached lake/portage data + the /api/lakes endpoint."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import lake_layers


def test_layers_for_unknown_park_returns_empty_dict():
    assert lake_layers.layers_for("does-not-exist") == {}


def test_killarney_returns_all_layer_keys():
    layers = lake_layers.layers_for("killarney")
    assert set(layers.keys()) == {"osm", "jeffs", "canvec"}


def test_canvec_geojson_has_lake_features():
    fc = lake_layers.canvec_geojson()
    assert fc["type"] == "FeatureCollection"
    assert all(f["properties"]["kind"] == "lake" for f in fc["features"])
    assert all(f["properties"]["source"] == "canvec" for f in fc["features"])
    # CanVec cache has ~586 lakes in the Killarney bbox.
    assert len(fc["features"]) > 400


def test_osm_geojson_has_lake_and_portage_features():
    fc = lake_layers.osm_geojson()
    assert fc["type"] == "FeatureCollection"
    kinds = {f["properties"]["kind"] for f in fc["features"]}
    # OSM cache has 81 lakes + 11 portages.
    assert "lake" in kinds and "portage" in kinds
    lake = next(f for f in fc["features"] if f["properties"]["kind"] == "lake")
    assert lake["geometry"]["type"] == "Polygon"
    # GeoJSON is lon, lat — check first coord pair makes geographic sense.
    lon, lat = lake["geometry"]["coordinates"][0][0]
    assert -82.5 < lon < -80.0
    assert 45.5 < lat < 46.5
    portage = next(f for f in fc["features"] if f["properties"]["kind"] == "portage")
    assert portage["geometry"]["type"] == "LineString"


def test_jeffs_geojson_has_lakes_only():
    fc = lake_layers.jeffs_geojson()
    assert fc["type"] == "FeatureCollection"
    assert all(f["properties"]["kind"] == "lake" for f in fc["features"])
    assert all(f["properties"]["source"] == "jeffs" for f in fc["features"])
    # Jeff's cache has 299 lakes.
    assert len(fc["features"]) > 100


def test_lakes_endpoint_returns_geojson_for_killarney():
    client = TestClient(app)
    r = client.get("/api/lakes/killarney")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"osm", "jeffs", "canvec"}
    assert body["osm"]["type"] == "FeatureCollection"


def test_lakes_endpoint_404_for_unknown_park():
    client = TestClient(app)
    r = client.get("/api/lakes/wonderland")
    assert r.status_code == 404
