# Route Maps and Time Estimates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an OSM-driven route map and per-day time-estimate table to generated trip pages, replacing the current "no route file = no section" behavior with auto-routing across Killarney lakes and portages.

**Architecture:** Two new modules. `osm_data.py` handles a one-shot Overpass fetch and a committed JSON cache. `route_engine.py` consumes that cache plus the trip's `nights` frontmatter, builds an ordered list of paddle/portage segments (1-hop search; degrades to straight-line with a warning when no connecting portage is found), and computes per-day time estimates. `build_trip.py`'s `render_route_section()` becomes a switch: user-supplied GPX wins, else auto-route from OSM, else section omitted.

**Tech Stack:** Python 3 (stdlib only — no shapely; point-in-polygon is hand-rolled), `requests` (already in `requirements.txt`), `pytest`, existing `route_map.py` for the Leaflet+SVG renderer.

**Spec:** `docs/superpowers/specs/2026-05-09-route-maps-and-estimates-design.md`

---

## File Structure

**New files (in repo root):**
- `osm_data.py` — Overpass fetch + cache loader (~80 lines)
- `route_engine.py` — name normalization, polygon helpers, route assembly, time math (~200 lines)
- `osm_killarney_cache.json` — committed; refreshable via `--refresh-osm` flag

**New tests:**
- `tests/test_osm_data.py` — parser test (no network)
- `tests/test_route_engine.py` — unit tests with synthetic OSM features

**Modified files:**
- `build_trip.py` — `render_route_section()` signature changes from `(route_file)` to `(trip)`; new `_render_auto_route()`, new `--refresh-osm` CLI flag.
- `tests/test_build_trip.py` — update the existing `test_build_html_assembles_full_page` test to assert the new section rendering shape (or mock through it).

**Out of scope:** generic-park support (Killarney bbox hardcoded), shapely, around-island pathfinding, configurable pace.

---

## Task 1: `osm_data.py` — Overpass fetch and cache

**Files:**
- Create: `osm_data.py`
- Create: `tests/test_osm_data.py`

- [ ] **Step 1: Write the failing parser test**

Create `/Users/alex/Documents/camping-planner/tests/test_osm_data.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_osm_data.py -v
```

Expected: 3 tests fail with `ModuleNotFoundError: No module named 'osm_data'`.

- [ ] **Step 3: Implement `osm_data.py`**

Create `/Users/alex/Documents/camping-planner/osm_data.py`:

```python
"""
Fetch and cache OpenStreetMap features for Killarney Provincial Park.

Public API:
  load_killarney_features() -> dict
    Returns {'lakes': [...], 'portages': [...]} from the cached JSON.

  refresh_killarney_cache() -> None
    Hits Overpass and writes osm_killarney_cache.json.

The cache is committed to the repo so collaborators don't need to refetch.
Refresh with `python3 build_trip.py --refresh-osm`.
"""
import json
import math
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).parent / "osm_killarney_cache.json"

# Killarney Provincial Park bounding box (south, west, north, east).
KILLARNEY_BBOX = (45.92, -81.60, 46.12, -81.25)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = """
[out:json][timeout:30];
(
  way["natural"="water"]["name"]({s},{w},{n},{e});
  way["portage"]({s},{w},{n},{e});
  way["canoe"="portage"]({s},{w},{n},{e});
  way["highway"="path"]["name"~"[Pp]ortage"]({s},{w},{n},{e});
);
out geom;
""".strip()


def _haversine_km(a: list, b: list) -> float:
    """Distance in km between [lat, lon] points."""
    lat1, lon1, lat2, lon2 = a[0], a[1], b[0], b[1]
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


def _polygon_centroid(points: list) -> list:
    """Centroid of a closed polygon (averaged vertices, ignoring duplicate close)."""
    pts = points[:-1] if points and points[0] == points[-1] else points
    n = len(pts)
    if n == 0:
        return [0.0, 0.0]
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    return [cx, cy]


def _line_length_km(points: list) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += _haversine_km(points[i - 1], points[i])
    return total


def _is_lake(tags: dict) -> bool:
    return tags.get("natural") == "water" and bool(tags.get("name"))


def _is_portage(tags: dict) -> bool:
    if tags.get("portage"):
        return True
    if tags.get("canoe") == "portage":
        return True
    if tags.get("highway") == "path":
        name = tags.get("name", "")
        if "portage" in name.lower():
            return True
    return False


def _parse_overpass_response(data: dict) -> dict:
    """Convert raw Overpass JSON into our normalized {lakes, portages} shape."""
    lakes = []
    portages = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        geom = el.get("geometry") or []
        points = [[p["lat"], p["lon"]] for p in geom]
        if not points:
            continue

        if _is_lake(tags):
            lakes.append({
                "name": tags["name"],
                "polygon": points,
                "centroid": _polygon_centroid(points),
            })
        elif _is_portage(tags):
            portages.append({
                "name": tags.get("name") or None,
                "line": points,
                "length_km": round(_line_length_km(points), 3),
                "endpoints": [points[0], points[-1]],
            })
    return {"lakes": lakes, "portages": portages}


def refresh_killarney_cache() -> None:
    """Fetch from Overpass and write the cache file. Slow; rate-limit tolerant."""
    s, w, n, e = KILLARNEY_BBOX
    query = OVERPASS_QUERY.format(s=s, w=w, n=n, e=e)
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=60)
    resp.raise_for_status()
    parsed = _parse_overpass_response(resp.json())
    CACHE_PATH.write_text(json.dumps(parsed, indent=2))
    print(f"Wrote {len(parsed['lakes'])} lakes, {len(parsed['portages'])} "
          f"portages to {CACHE_PATH}")


def load_killarney_features() -> dict:
    """Read the cached features. Raises FileNotFoundError if cache is missing."""
    if not CACHE_PATH.exists():
        raise FileNotFoundError(
            f"{CACHE_PATH}: cache missing. "
            "Run `python3 build_trip.py --refresh-osm <trip-dir>` to populate."
        )
    return json.loads(CACHE_PATH.read_text())


if __name__ == "__main__":
    refresh_killarney_cache()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_osm_data.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add osm_data.py tests/test_osm_data.py
git commit -m "feat: add osm_data module for Killarney Overpass fetch and cache"
```

---

## Task 2: `route_engine.py` — helpers (TDD)

Lake-name normalization, point-in-polygon, distance/centroid math.

**Files:**
- Create: `route_engine.py`
- Create: `tests/test_route_engine.py`

- [ ] **Step 1: Write the failing helper tests**

Create `/Users/alex/Documents/camping-planner/tests/test_route_engine.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v
```

Expected: 6 tests fail with `ModuleNotFoundError: No module named 'route_engine'`.

- [ ] **Step 3: Implement helpers**

Create `/Users/alex/Documents/camping-planner/route_engine.py`:

```python
"""
Build per-day paddle/portage segments and time estimates from a trip's
`nights` frontmatter using cached OpenStreetMap features for Killarney.

Public API:
  build_route(nights, access_point, osm) -> dict
  estimate_minutes(paddle_km, portage_km) -> int
  format_human_time(minutes) -> str
"""
import math
import re

# Conservative pace defaults — see spec for rationale.
PADDLE_KMH = 4.0
PORTAGE_KMH = 2.0
# "2 carries" = walk loaded, walk back empty, walk loaded again =
# 3 traversals of the portage trail per portage segment.
PORTAGE_TRAVERSALS = 3
BUFFER_PCT = 0.15


def _norm_lake_name(name: str) -> str:
    """Normalize a lake name for case-insensitive, punctuation-insensitive matching.

    Examples: "OSA Lake" -> "OSA", "O.S.A. Lake" -> "OSA",
    "Baie Fine" -> "BAIE FINE", "Baie-Fine" -> "BAIEFINE".
    """
    s = name.upper()
    s = re.sub(r"[._,\-]", "", s)
    s = re.sub(r"\s+LAKE$", "", s)
    return s.strip()


def _haversine_km(a: list, b: list) -> float:
    """Distance in km between [lat, lon] points."""
    R = 6371.0
    p1 = math.radians(a[0])
    p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


def _point_in_polygon(point: list, polygon: list) -> bool:
    """Ray-casting point-in-polygon test. Polygon is a closed ring of [lat, lon]."""
    x, y = point[0], point[1]
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add route_engine.py tests/test_route_engine.py
git commit -m "feat: add route_engine helpers (name normalization, point-in-polygon, haversine)"
```

---

## Task 3: `route_engine.py` — `build_route()` core (TDD)

Same-lake leg, two-lake-with-portage leg. No fallback yet — Task 4 adds approximate-fallback behavior.

**Files:**
- Modify: `route_engine.py`
- Modify: `tests/test_route_engine.py`

- [ ] **Step 1: Append fixture builder + failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_route_engine.py`:

```python
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

    # Day 1 (access -> night 1): same lake, single paddle segment.
    # Day 2 (night 1 -> night 2): same lake, single paddle segment.
    assert len(paddle_segs) == 2
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v
```

Expected: 2 new tests fail with `ImportError: cannot import name 'build_route'`. The 6 helper tests still pass.

- [ ] **Step 3: Implement `build_route()` (no fallback yet — happy path)**

Append to `/Users/alex/Documents/camping-planner/route_engine.py`:

```python
from datetime import datetime


_WEEKDAY_PREFIX = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
                   4: "Fri", 5: "Sat", 6: "Sun"}


def _day_label(date_str: str) -> str:
    """'2026-05-15' -> 'Fri 2026-05-15'. Falls back to raw string if unparseable."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{_WEEKDAY_PREFIX[d.weekday()]} {date_str}"
    except (ValueError, KeyError):
        return date_str


def _find_lake(name: str, lakes: list) -> dict | None:
    """Look up a lake by name (normalized). Returns lake dict or None."""
    target = _norm_lake_name(name)
    for lake in lakes:
        if _norm_lake_name(lake["name"]) == target:
            return lake
    return None


def _classify_portage_endpoints(portage: dict, lakes: list) -> list:
    """Return the lakes (by index) each portage endpoint falls inside.

    Returns [lake_or_None_for_endpoint_0, lake_or_None_for_endpoint_1].
    """
    result = []
    for ep in portage["endpoints"]:
        match = None
        for lake in lakes:
            if _point_in_polygon(ep, lake["polygon"]):
                match = lake
                break
        result.append(match)
    return result


def _find_connecting_portage(lake_a: dict, lake_b: dict, portages: list) -> dict | None:
    """Return a portage whose endpoints fall in lake_a and lake_b (any order)."""
    name_a = lake_a["name"]
    name_b = lake_b["name"]
    for p in portages:
        ends = _classify_portage_endpoints(p, [lake_a, lake_b])
        names_at_ends = {e["name"] if e else None for e in ends}
        if {name_a, name_b}.issubset(names_at_ends):
            return p
    return None


def _segment(day: str, kind: str, frm: str, to: str,
             distance_km: float, geometry: list) -> dict:
    return {
        "day": day,
        "kind": kind,
        "from": frm,
        "to": to,
        "distance_km": round(distance_km, 2),
        "geometry": geometry,
    }


def build_route(nights: list, access_point: str, osm: dict) -> dict:
    """Build per-leg segments + warnings from frontmatter nights + OSM data.

    Each "leg" is the travel between consecutive waypoints. Legs are:
      - Day 1: access_point -> nights[0]
      - Day N: nights[N-1] -> nights[N]
      - Last day: nights[-1] -> access_point

    Returns {"segments": [...], "warnings": [...]}.
    """
    lakes = osm["lakes"]
    portages = osm["portages"]
    segments: list = []
    warnings: list = []

    # Build the ordered list of waypoint dicts: each has {label, location, day_label}.
    waypoints = [{
        "label": access_point,
        "location": access_point,
        "day_label": _day_label(nights[0]["date"]) if nights else "",
    }]
    for night in nights:
        waypoints.append({
            "label": f"{night['location']} (site {night['site']})",
            "location": night["location"],
            "day_label": _day_label(night["date"]),
        })
    # Final leg: return to access point on the day after the last night.
    if nights:
        last_date = nights[-1]["date"]
        try:
            d = datetime.strptime(last_date, "%Y-%m-%d")
            return_label = _day_label(
                (d.replace(day=d.day + 1)).strftime("%Y-%m-%d")
            )
        except (ValueError, KeyError):
            return_label = "Return"
    else:
        return_label = "Return"
    waypoints.append({
        "label": access_point,
        "location": access_point,
        "day_label": return_label,
    })

    # Walk leg by leg.
    for i in range(1, len(waypoints)):
        a = waypoints[i - 1]
        b = waypoints[i]
        day_label = b["day_label"]
        lake_a = _find_lake(a["location"], lakes)
        lake_b = _find_lake(b["location"], lakes)

        if lake_a and lake_b and lake_a["name"] == lake_b["name"]:
            # Same lake — straight paddle.
            d_km = _haversine_km(lake_a["centroid"], lake_b["centroid"])
            segments.append(_segment(
                day_label, "paddle", a["label"], b["label"],
                d_km, [lake_a["centroid"], lake_b["centroid"]],
            ))
            continue

        if lake_a and lake_b:
            portage = _find_connecting_portage(lake_a, lake_b, portages)
            if portage:
                ends = _classify_portage_endpoints(portage, [lake_a, lake_b])
                # Ordered entry/exit so entry is in lake_a, exit in lake_b.
                if ends[0] and ends[0]["name"] == lake_a["name"]:
                    entry, exit_ = portage["endpoints"]
                    portage_geom = portage["line"]
                else:
                    exit_, entry = portage["endpoints"]
                    portage_geom = list(reversed(portage["line"]))
                # Paddle in lake_a from centroid to portage entry.
                d1 = _haversine_km(lake_a["centroid"], entry)
                segments.append(_segment(
                    day_label, "paddle", a["label"], f"{lake_a['name']} portage",
                    d1, [lake_a["centroid"], entry],
                ))
                # Portage.
                segments.append(_segment(
                    day_label, "portage", f"{lake_a['name']} portage",
                    f"{lake_b['name']} portage", portage["length_km"],
                    portage_geom,
                ))
                # Paddle in lake_b from portage exit to centroid.
                d2 = _haversine_km(exit_, lake_b["centroid"])
                segments.append(_segment(
                    day_label, "paddle", f"{lake_b['name']} portage", b["label"],
                    d2, [exit_, lake_b["centroid"]],
                ))
                continue

        # No-portage / unmatched-lake fallback: filled in by Task 4.
        # For now, raise so Task 3's tests pass (which only cover happy paths)
        # but failures during Task 4 development are loud.
        raise NotImplementedError(
            f"Cannot route from {a['location']} to {b['location']} "
            "(approximate fallback added in Task 4)"
        )

    return {"segments": segments, "warnings": warnings}
```

NOTE: the fixture `nights` for these tests covers only same-lake and
two-lakes-with-portage. The first leg (access_point -> nights[0]) hits the
same-lake branch (access_point and nights[0] are the same lake in both
tests). The last "return to access" leg also uses the same lake. The
intentional `NotImplementedError` is reached only when Task 4's fallback
isn't in place — Task 3's tests don't trip it.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add route_engine.py tests/test_route_engine.py
git commit -m "feat: build paddle/portage segments for same-lake and one-hop legs"
```

---

## Task 4: `route_engine.py` — approximate fallback (TDD)

When two consecutive lakes have no connecting portage in OSM data — or when a lake name doesn't resolve at all — emit a single `kind: "approx"` straight-line segment and add a human-readable warning.

**Files:**
- Modify: `route_engine.py`
- Modify: `tests/test_route_engine.py`

- [ ] **Step 1: Append failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_route_engine.py`:

```python
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
    assert len(approx) == 1  # one Alpha->Beta leg degraded
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v
```

Expected: the 2 new tests fail with `NotImplementedError` (raised by the
placeholder in Task 3).

- [ ] **Step 3: Replace the `raise NotImplementedError` with the fallback**

Edit `/Users/alex/Documents/camping-planner/route_engine.py`. Replace the entire `raise NotImplementedError(...)` block (and its preceding comment) at the bottom of `build_route()` with:

```python
        # Approximate-fallback: lake unmatched OR no connecting portage.
        if not lake_a:
            warnings.append(
                f"Could not resolve lake '{a['location']}' in OSM data — "
                "leg shown as straight line."
            )
        if not lake_b:
            warnings.append(
                f"Could not resolve lake '{b['location']}' in OSM data — "
                "leg shown as straight line."
            )
        if lake_a and lake_b:
            warnings.append(
                f"No portage found between {lake_a['name']} and {lake_b['name']} — "
                "leg shown as straight line."
            )
        # Use centroids when known, otherwise fall back to a sentinel point
        # roughly in the middle of the Killarney bbox so the map still renders.
        a_pt = lake_a["centroid"] if lake_a else [46.02, -81.40]
        b_pt = lake_b["centroid"] if lake_b else [46.02, -81.40]
        d_km = _haversine_km(a_pt, b_pt)
        segments.append(_segment(
            day_label, "approx", a["label"], b["label"], d_km, [a_pt, b_pt],
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v
```

Expected: 10 tests pass (8 from before + 2 new).

- [ ] **Step 5: Commit**

```bash
git add route_engine.py tests/test_route_engine.py
git commit -m "feat: approximate-fallback when lake/portage data is missing"
```

---

## Task 5: `route_engine.py` — time estimation (TDD)

Per-day estimate row builder + minute math + human time formatting.

**Files:**
- Modify: `route_engine.py`
- Modify: `tests/test_route_engine.py`

- [ ] **Step 1: Append failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_route_engine.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v
```

Expected: 7 new tests fail with `ImportError: cannot import name 'estimate_minutes'`.

- [ ] **Step 3: Implement estimation functions**

Append to `/Users/alex/Documents/camping-planner/route_engine.py`:

```python
def estimate_minutes(paddle_km: float, portage_km: float) -> int:
    """Total estimated travel time in minutes, including the buffer."""
    paddle_min = paddle_km * 60 / PADDLE_KMH
    portage_min = portage_km * PORTAGE_TRAVERSALS * 60 / PORTAGE_KMH
    return round((paddle_min + portage_min) * (1 + BUFFER_PCT))


def format_human_time(minutes: int) -> str:
    """Round minutes to nearest 5 and format as 'Xh Ym' or 'Ym'."""
    rounded = 5 * round(minutes / 5)
    h, m = divmod(rounded, 60)
    if h == 0:
        return f"{m}m"
    return f"{h}h {m}m"


def build_day_estimates(segments: list) -> list:
    """Aggregate segments by day. Returns list of DayEstimate dicts in day order."""
    days_in_order: list = []
    by_day: dict = {}
    for seg in segments:
        d = seg["day"]
        if d not in by_day:
            by_day[d] = {
                "day": d,
                "paddle_km": 0.0,
                "portage_km": 0.0,
                "approx": False,
                "_first_from": seg["from"],
                "_last_to": seg["to"],
            }
            days_in_order.append(d)
        rec = by_day[d]
        if seg["kind"] == "paddle":
            rec["paddle_km"] += seg["distance_km"]
        elif seg["kind"] == "portage":
            rec["portage_km"] += seg["distance_km"]
        elif seg["kind"] == "approx":
            # Approx legs count as paddle for distance + flag the day.
            rec["paddle_km"] += seg["distance_km"]
            rec["approx"] = True
        rec["_last_to"] = seg["to"]

    out = []
    for d in days_in_order:
        rec = by_day[d]
        paddle_km = round(rec["paddle_km"], 2)
        portage_km = round(rec["portage_km"], 2)
        minutes = estimate_minutes(paddle_km, portage_km)
        out.append({
            "day": d,
            "label": f"{rec['_first_from']} → {rec['_last_to']}",
            "paddle_km": paddle_km,
            "portage_km": portage_km,
            "approx": rec["approx"],
            "minutes": minutes,
            "human_time": format_human_time(minutes),
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v
```

Expected: 17 tests pass (10 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add route_engine.py tests/test_route_engine.py
git commit -m "feat: per-day estimate aggregation and human time formatting"
```

---

## Task 6: `build_trip.py` — integration

Switch `render_route_section` to a 3-way switch (user GPX → auto-route → empty). Add `_render_auto_route()` that produces map + table HTML. Add `--refresh-osm` flag.

**Files:**
- Modify: `build_trip.py`
- Modify: `tests/test_build_trip.py`

- [ ] **Step 1: Update existing integration test for the new function signature**

Edit `/Users/alex/Documents/camping-planner/tests/test_build_trip.py`. The existing `test_build_html_assembles_full_page` test mocks `build_trip._weather.get_weather` but does not currently exercise auto-routing. Append a new test:

```python
def test_build_html_renders_auto_route_table_when_no_gpx():
    """When no route file is present and OSM cache is loadable, an auto route table appears."""
    fixture = Path(__file__).parent / "fixtures" / "sample-trip"

    fake_osm = {
        "lakes": [
            {
                "name": "Killarney Lake",
                "polygon": [
                    [46.00, -81.50], [46.00, -81.30],
                    [46.10, -81.30], [46.10, -81.50],
                    [46.00, -81.50],
                ],
                "centroid": [46.05, -81.40],
            },
        ],
        "portages": [],
    }
    with patch("build_trip._weather.get_weather", return_value=_FAKE_WEATHER), \
         patch("build_trip._osm_data.load_killarney_features", return_value=fake_osm):
        html = build_html(fixture)

    # The auto-route renders a "Route" heading with a per-day estimates table.
    assert "Route" in html
    # Per-day table headers.
    for header in ("Day", "Paddle", "Portage", "Est. time"):
        assert header in html


def test_build_html_omits_route_when_no_osm_cache():
    """When OSM cache load fails AND no route file, route section is omitted."""
    fixture = Path(__file__).parent / "fixtures" / "sample-trip"
    with patch("build_trip._weather.get_weather", return_value=_FAKE_WEATHER), \
         patch("build_trip._osm_data.load_killarney_features",
               side_effect=FileNotFoundError("no cache")):
        html = build_html(fixture)
    # No OSM cache and no GPX -> no Route section.
    assert "<section id=\"route\">" not in html
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_build_trip.py -v
```

Expected: the 2 new tests fail (likely with `AttributeError: module 'build_trip'
has no attribute '_osm_data'` — the import doesn't exist yet).

- [ ] **Step 3: Add the imports and the auto-route renderer**

Edit `/Users/alex/Documents/camping-planner/build_trip.py`. In the imports section near the top (alongside `import weather as _weather` and `import route_map as _route_map`), add:

```python
import osm_data as _osm_data
import route_engine as _route_engine
```

- [ ] **Step 4: Replace `render_route_section()` with the new switch**

In `build_trip.py`, find the existing `render_route_section()` function and replace it with:

```python
def render_route_section(trip) -> str:
    """Render the route map section.

    Three modes:
      1. trip['route_file'] set -> use the user-supplied GPX/KML (existing behavior).
      2. No route file but trip frontmatter has 'nights' + 'access_point' ->
         auto-route from cached OSM data.
      3. Neither -> return ''.

    Accepts either a trip dict (preferred, new) or a Path/None (legacy: route_file).
    """
    # Backward-compat: accept the old (route_file) signature where caller passed
    # a Path or None. If caller passes a dict, treat it as the trip dict.
    if trip is None:
        return ""
    if not isinstance(trip, dict):
        # Legacy path-only invocation.
        if trip is None:
            return ""
        data = _route_map.parse_route_file(str(trip))
        return _route_map.generate_map_section(data)

    route_file = trip.get("route_file")
    if route_file is not None:
        data = _route_map.parse_route_file(str(route_file))
        return _route_map.generate_map_section(data)

    fm = trip.get("frontmatter", {}) or {}
    nights = fm.get("nights") or []
    access_point = fm.get("access_point")
    if not (nights and access_point):
        return ""

    try:
        osm = _osm_data.load_killarney_features()
    except FileNotFoundError:
        return ""

    route = _route_engine.build_route(
        nights=nights, access_point=access_point, osm=osm,
    )
    return _render_auto_route(route)
```

- [ ] **Step 5: Add the auto-route HTML renderer**

In `build_trip.py`, after `render_route_section`, add:

```python
def _render_auto_route(route: dict) -> str:
    """Render the OSM-driven route section: map + per-day estimates table."""
    days = _route_engine.build_day_estimates(route["segments"])

    # Build a route_map-compatible structure to pass to generate_map_section.
    tracks = []
    waypoints = []
    for i, seg in enumerate(route["segments"]):
        if not seg["geometry"]:
            continue
        # Each segment becomes a track; route_map.py will color-cycle them.
        track_name = f"{seg['from']} → {seg['to']} ({seg['kind']})"
        tracks.append({
            "name": track_name,
            "points": [tuple(pt) for pt in seg["geometry"]],
        })
    map_html = _route_map.generate_map_section({
        "waypoints": waypoints, "tracks": tracks, "source": "auto",
    })

    # Per-day estimates table.
    rows = []
    total_paddle = 0.0
    total_portage = 0.0
    total_minutes = 0
    for day in days:
        approx_marker = " ⚠" if day["approx"] else ""
        portage_cell = (
            "(approx)" if day["approx"] and day["portage_km"] == 0
            else f"{day['portage_km']} km"
        )
        rows.append(
            f"<tr><td>{day['day']}</td>"
            f"<td>{day['label']}{approx_marker}</td>"
            f"<td>{day['paddle_km']} km</td>"
            f"<td>{portage_cell}</td>"
            f"<td>{day['human_time']}</td></tr>"
        )
        total_paddle += day["paddle_km"]
        total_portage += day["portage_km"]
        total_minutes += day["minutes"]

    rows.append(
        f"<tr><td><strong>Total</strong></td><td></td>"
        f"<td><strong>{round(total_paddle, 1)} km</strong></td>"
        f"<td><strong>{round(total_portage, 1)} km</strong></td>"
        f"<td><strong>{_route_engine.format_human_time(total_minutes)}</strong></td></tr>"
    )

    warnings_html = ""
    if route.get("warnings"):
        items = "".join(f"<li>{w}</li>" for w in route["warnings"])
        warnings_html = f'<div class="warnings"><ul>{items}</ul></div>'

    table_html = (
        "<table><thead><tr><th>Day</th><th>Leg</th>"
        "<th>Paddle</th><th>Portage</th><th>Est. time</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )

    return (
        f'<section id="route"><h2>Route</h2>'
        f"{warnings_html}"
        f"{map_html}"
        f"{table_html}"
        f"</section>"
    )
```

- [ ] **Step 6: Update the call site in `build_html()`**

In `build_trip.py`, find the line in `build_html()` that calls `render_route_section`. It currently looks like:

```python
    sections_html.append(render_route_section(trip["route_file"]))
```

Replace with:

```python
    sections_html.append(render_route_section(trip))
```

- [ ] **Step 7: Add `--refresh-osm` CLI flag**

In `build_trip.py`, find the `main()` function and replace it with:

```python
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trip_dir", help="Path to trip directory (contains trip.md)")
    parser.add_argument(
        "--refresh-osm", action="store_true",
        help="Re-fetch the Killarney OSM cache from Overpass before rendering.",
    )
    args = parser.parse_args(argv)

    if args.refresh_osm:
        _osm_data.refresh_killarney_cache()

    trip_dir = Path(args.trip_dir)
    html = build_html(trip_dir)
    out_path = trip_dir / "trip.html"
    out_path.write_text(html)
    print(f"Wrote {out_path}")
    return 0
```

- [ ] **Step 8: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ -v
```

Expected: all tests pass — 11 build_trip tests (9 original + 2 new), 17 route_engine tests, 3 osm_data tests = 31 total.

- [ ] **Step 9: Commit**

```bash
git add build_trip.py tests/test_build_trip.py
git commit -m "feat: integrate OSM-driven auto-route into build_trip"
```

---

## Task 7: Refresh OSM cache and regenerate Killarney trip

This is the live-data step. It hits the Overpass API once.

**Files:**
- Create: `osm_killarney_cache.json` (committed)
- Modify: `trips/killarney-2026-05/trip.html` (regenerated)

- [ ] **Step 1: Run with `--refresh-osm` to populate the cache and regenerate**

```bash
cd /Users/alex/Documents/camping-planner
python3 build_trip.py --refresh-osm trips/killarney-2026-05/
```

Expected output (counts will vary):
```
Wrote N lakes, M portages to /Users/alex/Documents/camping-planner/osm_killarney_cache.json
Wrote trips/killarney-2026-05/trip.html
```

If Overpass returns 504 or rate-limits, wait 1-2 minutes and retry. The
operation is idempotent.

- [ ] **Step 2: Sanity-check the cache shape**

```bash
cd /Users/alex/Documents/camping-planner
python3 -c "
import json
data = json.loads(open('osm_killarney_cache.json').read())
print(f'lakes: {len(data[\"lakes\"])}')
print(f'portages: {len(data[\"portages\"])}')
named_lakes = sorted(l['name'] for l in data['lakes'])
print(f'lake names (first 10): {named_lakes[:10]}')
print(f'  Killarney Lake found: {\"Killarney Lake\" in named_lakes}')
print(f'  OSA Lake variants: {[n for n in named_lakes if \"OSA\" in n.upper() or \"O.S.A\" in n.upper()]}')
print(f'  Baie Fine variants: {[n for n in named_lakes if \"BAIE\" in n.upper()]}')
"
```

Expected: at least Killarney Lake, an OSA Lake or O.S.A. Lake, and a Baie
Fine somewhere in the list. If any of those three are missing, the route
will degrade to "approx" with a warning — note this as a concern but
proceed.

- [ ] **Step 3: Smoke-test the regenerated HTML**

```bash
cd /Users/alex/Documents/camping-planner
python3 -c "
from pathlib import Path
html = Path('trips/killarney-2026-05/trip.html').read_text()
checks = {
    'route section present': '<section id=\"route\">' in html,
    'route table': '<th>Paddle</th>' in html and '<th>Portage</th>' in html,
    'leaflet present': 'leaflet@' in html,
    'estimates total row': '<strong>Total</strong>' in html,
}
for k, v in checks.items():
    print(f'{\"✓\" if v else \"✗\"} {k}')
"
```

Expected: all 4 checks pass with `✓`.

- [ ] **Step 4: Browser smoke test**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m http.server 8000 &
sleep 1
open "http://localhost:8000/trips/killarney-2026-05/trip.html"
```

Verify in browser:
- New "Route" section appears with a Leaflet map.
- Map shows track lines for each day's leg.
- Per-day table below the map has 4 rows (one per travel day) plus a Total row.
- Any `⚠ no portage` warnings are surfaced in the warnings list above the map.
- All other sections (Itinerary, Weather, Gear, Food, Packing, Costs) still render correctly.

Stop the server when done: `kill %1`.

- [ ] **Step 5: Commit cache + regenerated HTML**

```bash
cd /Users/alex/Documents/camping-planner
git add osm_killarney_cache.json trips/killarney-2026-05/trip.html
git commit -m "feat: refresh Killarney OSM cache and regenerate trip page with route"
```

- [ ] **Step 6: Push to origin**

```bash
git push
```

Expected: pushes the new commits to `origin/main` so pizza-zip sees them
on the next pull.

---

## Verification checklist (run after Task 7)

- [ ] `python3 -m pytest tests/ -v` shows 31 passing tests
- [ ] `osm_killarney_cache.json` is committed and < 500 KB
- [ ] `trips/killarney-2026-05/trip.html` has a `<section id="route">` block
- [ ] Browser preview shows the map and per-day estimate table
- [ ] If any legs degraded to `approx`, the warning is visible in the rendered HTML
- [ ] `git log --oneline | head -8` shows the 7 task commits

If all six pass, the feature is complete.
