"""Convert the cached lake/portage data into GeoJSON for the editor overlay.

Two sources today, both Killarney-only:
  - osm_killarney_cache.json    → OSM-named lakes + named portages (line strings)
  - jeffs_killarney_cache.json  → finer-grained polygons from Jeff's Maps KMZ

Cached caches are loaded once per process (LRU) and converted to GeoJSON
FeatureCollections lazily. Coordinates are flipped from cache-native
[lat, lon] to GeoJSON's [lon, lat].
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import REPO_ROOT

_OSM_PATHS = (
    REPO_ROOT / "osm_killarney_cache.json",
    REPO_ROOT / "data" / "osm_killarney_cache.json",
)
_JEFFS_PATHS = (
    REPO_ROOT / "jeffs_killarney_cache.json",
    REPO_ROOT / "data" / "jeffs_killarney_cache.json",
)


def _first_existing(paths: tuple[Path, ...]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def _polygon_feature(polygon: list[list[float]], props: dict) -> dict:
    """[[lat, lon], ...] → GeoJSON Polygon feature (lon, lat)."""
    ring = [[lon, lat] for lat, lon in polygon]
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": props,
    }


def _linestring_feature(line: list[list[float]], props: dict) -> dict:
    coords = [[lon, lat] for lat, lon in line]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": props,
    }


@lru_cache(maxsize=4)
def osm_geojson() -> dict:
    """Return a FeatureCollection with named OSM lakes and portages."""
    path = _first_existing(_OSM_PATHS)
    if path is None:
        return {"type": "FeatureCollection", "features": []}
    data = json.loads(path.read_text())
    features: list[dict] = []
    for lake in data.get("lakes", []):
        poly = lake.get("polygon")
        if not poly:
            continue
        features.append(_polygon_feature(poly, {
            "kind": "lake",
            "source": "osm",
            "name": lake.get("name") or "",
        }))
    for portage in data.get("portages", []):
        line = portage.get("line")
        if not line:
            continue
        features.append(_linestring_feature(line, {
            "kind": "portage",
            "source": "osm",
            "name": portage.get("name") or "Portage",
            "length_km": portage.get("length_km"),
        }))
    return {"type": "FeatureCollection", "features": features}


@lru_cache(maxsize=4)
def jeffs_geojson() -> dict:
    """Return a FeatureCollection with Jeff's lake polygons (mostly unnamed)."""
    path = _first_existing(_JEFFS_PATHS)
    if path is None:
        return {"type": "FeatureCollection", "features": []}
    data = json.loads(path.read_text())
    features: list[dict] = []
    for lake in data.get("lakes", []):
        poly = lake.get("polygon")
        if not poly:
            continue
        features.append(_polygon_feature(poly, {
            "kind": "lake",
            "source": "jeffs",
            "name": lake.get("name") or "",
        }))
    return {"type": "FeatureCollection", "features": features}


_PARK_LAYERS = {
    "killarney": {"osm": osm_geojson, "jeffs": jeffs_geojson},
}


def layers_for(park: str) -> dict[str, dict]:
    """Return {layer_name: feature_collection} for the named park, or {} if unknown."""
    spec = _PARK_LAYERS.get(park)
    if not spec:
        return {}
    return {name: producer() for name, producer in spec.items()}
