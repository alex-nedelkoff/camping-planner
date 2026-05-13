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
import os
from functools import lru_cache
from pathlib import Path

from app.config import REPO_ROOT


def _candidate_dirs() -> tuple[Path, ...]:
    """Where to look for cached lake/portage data, in priority order.

    LAKE_DATA_DIR overrides everything else, useful when a worktree (under
    .claude/worktrees/...) needs to share cached data with the parent
    checkout. Otherwise fall back to REPO_ROOT/data and finally REPO_ROOT
    itself (legacy paths kept the JSONs at the project root).
    """
    out: list[Path] = []
    env = os.environ.get("LAKE_DATA_DIR")
    if env:
        out.append(Path(env))
    out.append(REPO_ROOT / "data")
    out.append(REPO_ROOT)
    # If we're a worktree under .claude/worktrees/<name>, the parent repo
    # often has the local-only cache files (CanVec, hiking trails, etc.).
    parts = REPO_ROOT.parts
    if len(parts) >= 4 and parts[-3:-1] == (".claude", "worktrees"):
        parent_repo = REPO_ROOT.parents[2]
        out.append(parent_repo / "data")
        out.append(parent_repo)
    return tuple(out)


def _find(name: str) -> Path | None:
    for d in _candidate_dirs():
        p = d / name
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
    path = _find("osm_killarney_cache.json")
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
    path = _find("jeffs_killarney_cache.json")
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


@lru_cache(maxsize=4)
def canvec_geojson() -> dict:
    """Return a FeatureCollection of CanVec (NRCan) waterbody polygons."""
    path = _find("canvec_killarney_lakes.json")
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
            "source": "canvec",
            "name": lake.get("name") or "",
        }))
    return {"type": "FeatureCollection", "features": features}


_PARK_LAYERS = {
    "killarney": {
        "osm": osm_geojson,
        "jeffs": jeffs_geojson,
        "canvec": canvec_geojson,
    },
}


def layers_for(park: str) -> dict[str, dict]:
    """Return {layer_name: feature_collection} for the named park, or {} if unknown."""
    spec = _PARK_LAYERS.get(park)
    if not spec:
        return {}
    return {name: producer() for name, producer in spec.items()}
