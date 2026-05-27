"""
Fetch hiking trails from OSM Overpass for the Killarney bbox.

Visual data only — not consumed by the route engine. Killarney has named
hiking trails (La Cloche Silhouette, Cranberry, Granite Ridge, etc.) that
appear on the OSM tile renderer but aren't pulled by osm_data.py's portage-
only Overpass query.

Output: `data/osm_hiking_trails.json`
Schema: {"trails": [{"id", "name", "highway", "geometry": [[lat, lon], ...]}]}

Usage:
    python3 scripts/fetch_osm_hiking_trails.py
"""
import json
import sys
import urllib.parse
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_PATH = DATA_DIR / "osm_hiking_trails.json"

# Killarney Provincial Park bbox (south, west, north, east).
BBOX = (45.92, -81.60, 46.12, -81.25)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Pull all path/track ways + named footways. Exclude ways already tagged
# as portage (those are in osm_killarney_cache.json and we don't want
# duplicates).
OVERPASS_QUERY = """
[out:json][timeout:60];
(
  way["highway"="path"][!"portage"][!"canoe"]({s},{w},{n},{e});
  way["highway"="track"][!"portage"][!"canoe"]({s},{w},{n},{e});
  way["highway"="footway"]["name"]({s},{w},{n},{e});
);
out geom;
""".strip()


def fetch():
    s, w, n, e = BBOX
    query = OVERPASS_QUERY.format(s=s, w=w, n=n, e=e)
    body = urllib.parse.urlencode({"data": query})
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "camping-planner/1.0 (github.com/alex)",
    }
    print(f"Querying Overpass for hiking trails in {BBOX}...", file=sys.stderr)
    r = requests.post(OVERPASS_URL, data=body, headers=headers, timeout=90)
    r.raise_for_status()
    return r.json()


def parse(overpass_json) -> dict:
    trails = []
    for el in overpass_json.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        tags = el.get("tags", {})
        trails.append({
            "id": el.get("id"),
            "name": tags.get("name", ""),
            "highway": tags.get("highway", ""),
            "geometry": [[p["lat"], p["lon"]] for p in geom],
        })
    return {"trails": trails, "bbox": list(BBOX)}


def main():
    DATA_DIR.mkdir(exist_ok=True)
    data = fetch()
    parsed = parse(data)
    CACHE_PATH.write_text(json.dumps(parsed, indent=2))
    named = sum(1 for t in parsed["trails"] if t["name"])
    print(f"Wrote {CACHE_PATH}", file=sys.stderr)
    print(f"  total trails: {len(parsed['trails'])}", file=sys.stderr)
    print(f"  named:        {named}", file=sys.stderr)
    # Most common names (sanity check).
    from collections import Counter
    name_counts = Counter(t["name"] for t in parsed["trails"] if t["name"])
    print(f"  top names:", file=sys.stderr)
    for name, count in name_counts.most_common(10):
        print(f"    {name}: {count} way(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
