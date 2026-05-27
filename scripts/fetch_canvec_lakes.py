"""
Fetch CanVec 1:50K waterbody polygons from the DFO ArcGIS REST service.

Source: Natural Resources Canada / CanVec series, served by DFO.
        Layer 7 = waterbody @ 1:50,000 scale.
URL:    https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/Basemaps/Canvec_En/MapServer/7

Output: data/canvec_killarney_lakes.json
Schema: {"lakes": [{"name": str, "polygon": [[lat, lon], ...] | [[[..], ...], ...]}],
         "bbox": [s, w, n, e]}

Usage:
    python3 scripts/fetch_canvec_lakes.py
"""
import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_PATH = DATA_DIR / "canvec_killarney_lakes.json"

# Killarney Provincial Park bbox (south, west, north, east).
BBOX = (45.92, -81.60, 46.12, -81.25)

URL = ("https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/Basemaps/"
       "Canvec_En/MapServer/7/query")


def fetch():
    s, w, n, e = BBOX
    # ArcGIS REST geometry is xmin,ymin,xmax,ymax in inSR's coords (EPSG:4326).
    params = {
        "where": "1=1",
        "geometry": f"{w},{s},{e},{n}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "outFields": "name_en,name_fr,water_definition,permanency",
        "f": "geojson",
        "resultRecordCount": "2000",
    }
    print(f"Querying CanVec 1:50K waterbody for {BBOX}...", file=sys.stderr)
    r = requests.get(URL, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def to_polygon_list(geom):
    """Convert GeoJSON geometry into a list of [lat, lon] rings.

    Returns either a single ring (Polygon) or a list of rings (MultiPolygon /
    multi-ring Polygon).
    """
    typ = geom.get("type")
    if typ == "Polygon":
        # First ring is exterior; ignore inner holes for our use case.
        ring = geom["coordinates"][0]
        return [[lat, lon] for lon, lat in ring]
    if typ == "MultiPolygon":
        # Largest polygon's outer ring.
        polys = geom["coordinates"]
        biggest = max(polys, key=lambda p: len(p[0]))
        return [[lat, lon] for lon, lat in biggest[0]]
    return []


def main():
    DATA_DIR.mkdir(exist_ok=True)
    data = fetch()
    lakes = []
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        polygon = to_polygon_list(feat.get("geometry") or {})
        if not polygon:
            continue
        lakes.append({
            "name": (props.get("name_en") or props.get("name_fr") or ""),
            "polygon": polygon,
        })
    out = {
        "lakes": lakes,
        "bbox": list(BBOX),
        "source": "CanVec 1:50K waterbody via egisp.dfo-mpo.gc.ca",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    CACHE_PATH.write_text(json.dumps(out, separators=(",", ":")))
    named = sum(1 for l in lakes if l["name"])
    total_vertices = sum(len(l["polygon"]) for l in lakes)
    size_kb = CACHE_PATH.stat().st_size // 1024
    print(f"Wrote {CACHE_PATH}", file=sys.stderr)
    print(f"  features: {len(lakes)} ({named} named)", file=sys.stderr)
    print(f"  total vertices: {total_vertices:,}", file=sys.stderr)
    print(f"  size: {size_kb} KB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
