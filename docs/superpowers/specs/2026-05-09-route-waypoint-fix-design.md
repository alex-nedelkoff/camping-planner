---
title: Route waypoint accuracy fix (drop centroids, use access points)
date: 2026-05-09
status: draft
---

# Route waypoint accuracy fix

## Goal

Eliminate the misleading lake-centroid waypoints from rendered route geometry.
Replace them with hardcoded access-point GPS for the first and last paddle
segments. Add small "site location (lake center)" pins so each night's lake
is still visible on the map.

After this change, every leg of a connected (non-approx) route will have its
endpoints at real shoreline GPS — either an OSM portage endpoint or a known
access-point GPS. Centroids only appear for approx-fallback legs (where they
already carry an explicit `⚠` warning).

## Non-goals

- Per-site GPS sourcing. We confirmed no clean automated source exists:
  Ontario Parks API has only pixel coords, OSM has spotty backcountry coverage,
  Google Places needs a paid key. Skipping.
- Visual smoothing/Bezier on paddle segments. Paddling across an open lake is
  geographically a straight line; fake curves would lie. Revisit only if the
  honest version still feels sparse.
- Hardcoded coords for non-Killarney parks. Out of scope until we plan a trip
  there.

## Constraints

- Don't disturb the approx-fallback path. Approx legs (Baie Fine) still use
  centroids and emit warnings — that's correct behavior.
- Don't break the existing test suite (35/35 passing).
- Frontmatter format unchanged. No new fields required.

## Architecture

```
build_trip.py
   render_route_section(trip)
        │
        ▼
route_engine.py
   build_route(nights, access_point, osm)
        │
        ├── _resolve_access_point(name)  ← NEW
        │       look up KILLARNEY_ACCESS_POINTS dict
        │       returns [lat, lon] for known names, falls back to lake centroid
        │
        ├── (per-leg)
        │     ├── connected path: paddle segments use access GPS or portage
        │     │   endpoints, never lake centroids
        │     └── approx fallback: still uses centroids (unchanged)
        │
        └── markers (NEW field on returned dict)
              one marker per night: {label, lat, lon, kind: "site"}
              one marker for access point: {label, lat, lon, kind: "access"}
              consumed by _render_auto_route() to add Leaflet pins
```

## Components

### `route_engine.py` changes

#### Add `KILLARNEY_ACCESS_POINTS` constant

```python
# Hardcoded GPS for Killarney's main access points. The 'lake' entry is the
# lake the access sits on, used as a fallback for naming.
KILLARNEY_ACCESS_POINTS = {
    "George Lake": {"gps": [46.0136, -81.4049], "lake": "George Lake"},
    "Bell Lake":   {"gps": [46.0822, -81.2680], "lake": "Bell Lake"},
    "Chikanishing": {"gps": [46.0125, -81.4485], "lake": "Chikanishing River"},
}
```

(GPS sourced from publicly known Killarney access points: George Lake parking
lot at the day-use beach; Bell Lake parking; Chikanishing put-in.)

#### Add `_resolve_access_point()` helper

```python
def _resolve_access_point(name: str, lakes: list) -> dict:
    """Return {gps: [lat, lon], lake: dict_or_None} for an access point name.

    First tries the hardcoded KILLARNEY_ACCESS_POINTS table. If unknown,
    falls back to the lake-centroid behavior so non-Killarney trips still
    work approximately.
    """
    info = KILLARNEY_ACCESS_POINTS.get(name)
    if info:
        lake = _find_lake(info["lake"], lakes)
        return {"gps": info["gps"], "lake": lake}
    # Fallback: treat name as a lake; use centroid.
    lake = _find_lake(name, lakes)
    if lake:
        return {"gps": lake["centroid"], "lake": lake}
    return {"gps": None, "lake": None}
```

#### Modify `build_route()`

Two changes inside the existing connected-path branch (the multi-hop logic):

1. **First paddle segment** — replace the current `current_pt = lake_a["centroid"]`
   line. If the leg starts from the access point, use the access point's GPS
   instead.

2. **Last paddle segment** — currently ends at `lake_b["centroid"]`. If the
   leg ends at the access point (i.e., the return leg), use access GPS instead.

Detection: a leg is "from access" when `i == 1` (first iteration); a leg is
"to access" when `i == len(waypoints) - 1` (last iteration).

Concrete edit to the existing connected-path block in `build_route()`:

```python
        if lake_a and lake_b:
            path = _find_path_through_portages(lake_a, lake_b, lakes, portages)
            if path:
                # Determine the actual starting point.
                if i == 1:
                    # First leg of trip — start at access point GPS.
                    access = _resolve_access_point(access_point, lakes)
                    current_pt = access["gps"] if access["gps"] else lake_a["centroid"]
                else:
                    current_pt = lake_a["centroid"]
                current_lake = lake_a

                for next_name, portage, ends in path:
                    # ... (existing per-hop paddle/portage emission, unchanged) ...
                    current_pt = exit_

                # Determine the actual ending point.
                if i == len(waypoints) - 1:
                    # Last leg of trip — end at access point GPS.
                    access = _resolve_access_point(access_point, lakes)
                    end_pt = access["gps"] if access["gps"] else lake_b["centroid"]
                else:
                    end_pt = lake_b["centroid"]

                d_final = _haversine_km(current_pt, end_pt)
                segments.append(_segment(
                    day_label, "paddle",
                    f"{lake_b['name']} portage", b["label"],
                    d_final, [current_pt, end_pt],
                ))
                continue
```

NOTE: only the first/last legs are special-cased. Mid-trip legs that *happen*
to start or end at a lake centroid still use the centroid — this preserves
the existing behavior for cases where neither end of a leg is the access
point. Non-Killarney trips fall through to centroid-everywhere via the
fallback inside `_resolve_access_point`.

#### Add `markers` to the `build_route()` return dict

```python
def build_route(...) -> dict:
    ...
    markers = []
    access = _resolve_access_point(access_point, lakes)
    if access["gps"]:
        markers.append({
            "label": access_point,
            "lat": access["gps"][0],
            "lon": access["gps"][1],
            "kind": "access",
        })
    for night in nights:
        lake = _find_lake(night["location"], lakes)
        if lake:
            markers.append({
                "label": f"Site {night['site']}, {night['location']} (lake center)",
                "lat": lake["centroid"][0],
                "lon": lake["centroid"][1],
                "kind": "site",
            })

    return {
        "segments": segments,
        "warnings": warnings,
        "markers": markers,  # NEW
    }
```

### `build_trip.py` changes

`_render_auto_route()` currently passes only `tracks` to
`route_map.generate_map_section`. Update it to also pass `waypoints` derived
from `route["markers"]`:

```python
def _render_auto_route(route: dict) -> str:
    days = _route_engine.build_day_estimates(route["segments"])

    tracks = []
    for seg in route["segments"]:
        if not seg["geometry"]:
            continue
        track_name = f"{seg['from']} → {seg['to']} ({seg['kind']})"
        tracks.append({
            "name": track_name,
            "points": [tuple(pt) for pt in seg["geometry"]],
        })

    # NEW: convert markers to route_map's waypoint shape.
    waypoints = []
    for m in route.get("markers", []):
        waypoints.append({
            "lat": m["lat"],
            "lon": m["lon"],
            "name": m["label"],
            "desc": "",
        })

    map_html = _route_map.generate_map_section({
        "waypoints": waypoints,
        "tracks": tracks,
        "source": "auto",
    })
    # ... rest unchanged (table, warnings, section wrapper) ...
```

## Testing

Two new tests in `tests/test_route_engine.py`:

```python
def test_build_route_uses_access_point_gps_for_first_and_last_legs():
    """When access_point is George Lake, first/last paddle endpoints use
    KILLARNEY_ACCESS_POINTS GPS, not the George Lake centroid."""
    # Use a synthetic OSM with a "George Lake" entry whose centroid is
    # deliberately offset from the hardcoded access GPS. The first segment's
    # start coord and the last segment's end coord should match the access
    # GPS, NOT the offset centroid.
    osm = {
        "lakes": [
            {
                "name": "George Lake",
                "polygon": [[46.00, -81.39], [46.00, -81.41],
                            [46.05, -81.41], [46.05, -81.39],
                            [46.00, -81.39]],
                "centroid": [46.025, -81.40],  # offset from access
            },
            {
                "name": "Killarney Lake",
                "polygon": [[46.04, -81.34], [46.04, -81.36],
                            [46.07, -81.36], [46.07, -81.34],
                            [46.04, -81.34]],
                "centroid": [46.055, -81.35],
            },
        ],
        "portages": [
            {
                "name": "test portage",
                "line": [[46.04, -81.40], [46.05, -81.36]],
                "length_km": 4.5,
                "endpoints": [[46.04, -81.40], [46.05, -81.36]],
            },
        ],
    }
    nights = [
        {"date": "2026-05-15", "site": "1", "location": "Killarney Lake"},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)

    paddle_segs = [s for s in out["segments"] if s["kind"] == "paddle"]
    # First paddle starts at access GPS (46.0136, -81.4049), not centroid.
    first_start = paddle_segs[0]["geometry"][0]
    assert first_start == [46.0136, -81.4049]
    # Last paddle ends at access GPS, not centroid.
    last_end = paddle_segs[-1]["geometry"][-1]
    assert last_end == [46.0136, -81.4049]


def test_build_route_emits_markers_for_access_and_each_night():
    osm = {
        "lakes": [
            {
                "name": "George Lake",
                "polygon": [[46.00, -81.39], [46.00, -81.41],
                            [46.05, -81.41], [46.05, -81.39],
                            [46.00, -81.39]],
                "centroid": [46.025, -81.40],
            },
        ],
        "portages": [],
    }
    nights = [
        {"date": "2026-05-15", "site": "7", "location": "George Lake"},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)
    markers = out.get("markers", [])

    # 1 access marker + 1 night marker.
    assert len(markers) == 2
    access = [m for m in markers if m["kind"] == "access"][0]
    site = [m for m in markers if m["kind"] == "site"][0]
    assert access["lat"] == 46.0136 and access["lon"] == -81.4049
    assert "Site 7" in site["label"]
    assert "lake center" in site["label"]
```

The existing tests stay green:
- Synthetic-fixture tests use lakes "Alpha Lake" / "Beta Lake" which are NOT
  in `KILLARNEY_ACCESS_POINTS`, so the fallback (lake centroid) kicks in.
  Existing assertions about centroid-based paddle segments still hold.

## File changes summary

**Modified:**
- `route_engine.py`: add `KILLARNEY_ACCESS_POINTS` constant and
  `_resolve_access_point()` helper; update `build_route()` to use access GPS
  on first/last legs and to emit a `markers` list.
- `build_trip.py`: `_render_auto_route()` passes markers as waypoints to
  `route_map.generate_map_section`.
- `tests/test_route_engine.py`: 2 new tests as above.

**Not changed:**
- `osm_data.py`, `osm_killarney_cache.json`, the trip frontmatter, the
  templates.

## Implementation order

1. Add `KILLARNEY_ACCESS_POINTS` and `_resolve_access_point` (with a unit
   test for the resolver).
2. Update `build_route()` first/last leg logic + `markers` field. Add the
   two new tests.
3. Update `_render_auto_route()` to forward markers as waypoints.
4. Re-run `python3 build_trip.py trips/killarney-2026-05/`.
5. Smoke-test in browser. Confirm the access point shows as a pin at the
   actual George Lake parking lot, not in the middle of the lake.
6. Commit.

## Risks & open questions

- **Access point GPS accuracy.** I'll use publicly documented Killarney
  parking lot / put-in coordinates. Off by 50m at worst — well below the
  resolution that matters for trip planning.
- **Mid-trip legs without portages.** If a future trip has two consecutive
  same-lake nights with no portage between (e.g., car-camping for two nights
  on George Lake), the current `same lake` branch already emits a single
  paddle from centroid to centroid, which is fine — sleeping in the same
  lake doesn't require a route. No change here.
- **Marker visual styling.** The existing `route_map.py` renders waypoints
  as red circle markers with a popup. That's fine for v1; we can theme
  access vs. site pins differently later if it matters.
