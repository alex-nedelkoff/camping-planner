---
title: OSM-driven route maps and time estimates
date: 2026-05-09
status: draft
---

# OSM-driven route maps and time estimates

## Goal

Add a "Route" section to generated trip pages: an interactive map of the
trip's lakes and portages (sourced from OpenStreetMap) plus a per-day table
of estimated paddle/portage distance and travel time. Targets the Killarney
2026-05-15 trip first; designed to work for any Killarney interior trip and
to be extensible to other parks later.

## Non-goals

- Replacing user-supplied GPX/KML routes (those still take precedence when
  `route.gpx` or `route.kml` is present).
- Building a general waterway-routing engine. The path geometry is
  paddle-straight-line on water, snapped to the actual OSM portage trail at
  land crossings — no around-island pathfinding, no multi-hop search.
- Configurable pace per trip. Conservative defaults (paddle 4 km/h, portage
  2 km/h × 2 carries, +15% buffer) are baked in for now; revisit if needed.
- Wind, current, or weather adjustments.
- Coverage outside Killarney. The Overpass query and lake-centroid lookups
  use a Killarney bbox; other parks need separate work.

## Constraints

- OSM portage coverage in Killarney is genuinely patchy. Some legs will
  degrade to straight-line "approximate" with a visible warning in the
  output. Honest UX, not a bug.
- Overpass API is rate-limited and occasionally down. The system must work
  offline against a committed cache; a `--refresh-osm` flag is the only
  way to refetch.
- No new heavy dependencies. Point-in-polygon and lake-name normalization
  are small enough to implement directly without shapely.

## Architecture

```
                                 ┌──────────────────────────┐
                                 │  Overpass API (online)   │
                                 └────────────┬─────────────┘
                                              │ one-shot fetch (manual)
                                              ▼
osm_data.py ──────► osm_killarney_cache.json (committed, ~50-200KB)
                              │
                              │ load_killarney_features()
                              ▼
                    {"lakes": [...], "portages": [...]}
                              │
                              ▼
                      route_engine.py
                  (name matching, segments,
                   time math, table data)
                              │
                              ▼
                       build_trip.py
                (render_route_section becomes a switch)
                              │
                              ▼
                          trip.html
                  (Leaflet+SVG map + per-day table)
```

## Components

### `osm_data.py` (new, ~80 lines)

Single responsibility: fetch from Overpass, normalize, cache.

**Public API:**

```python
def load_killarney_features() -> dict:
    """Returns {'lakes': [Lake, ...], 'portages': [Portage, ...]}.

    Reads from osm_killarney_cache.json. Raises FileNotFoundError if
    cache is missing — caller should suggest running with --refresh-osm.
    """

def refresh_killarney_cache() -> None:
    """Fetches from Overpass and writes osm_killarney_cache.json.

    Called only when build_trip.py is invoked with --refresh-osm.
    """
```

**Data shapes:**

```python
Lake = {
    "name": str,           # OSM name tag
    "polygon": [[lat, lon], ...],  # closed ring
    "centroid": [lat, lon],
}

Portage = {
    "name": str | None,    # may be unnamed
    "line": [[lat, lon], ...],
    "length_km": float,
    "endpoints": ([lat, lon], [lat, lon]),  # first and last point
}
```

**Overpass query** (Killarney bbox 45.92, -81.60, 46.12, -81.25):

```
[out:json][timeout:30];
(
  way["natural"="water"]["name"](45.92,-81.60,46.12,-81.25);
  way["portage"](45.92,-81.60,46.12,-81.25);
  way["canoe"="portage"](45.92,-81.60,46.12,-81.25);
  way["highway"="path"]["name"~"[Pp]ortage"](45.92,-81.60,46.12,-81.25);
);
out geom;
```

(Ways with no name and no portage tag are filtered out post-fetch to keep
the cache small.)

### `route_engine.py` (new, ~150 lines)

Single responsibility: turn a list of `nights` into a list of segments and
a table of estimates.

**Public API:**

```python
def build_route(
    nights: list[dict],         # frontmatter nights, each {date, site, location}
    access_point: str,          # frontmatter access_point (e.g., "George Lake")
    osm: dict,                  # output of load_killarney_features()
) -> dict:
    """Returns:
      {
        'segments': [Segment, ...],  # ordered, includes day labels
        'days': [DayEstimate, ...],  # one per travel day
        'warnings': [str, ...],      # human-readable issues
        'leaflet_route': dict,       # shape consumable by route_map.py
      }
    """

Segment = {
    "day": str,            # "Fri 2026-05-15"
    "kind": "paddle" | "portage" | "approx",
    "from": str,           # "George Lake"
    "to": str,             # "OSA Lake (site 61)"
    "distance_km": float,
    "geometry": [[lat, lon], ...],
}

DayEstimate = {
    "day": str,
    "label": str,                    # "George Lake → OSA Lake (site 61)"
    "paddle_km": float,
    "portage_km": float,
    "approx": bool,                  # True if any leg degraded
    "minutes": int,                  # already includes 15% buffer
    "human_time": str,               # "2h 15m"
}
```

**Algorithm (per leg A → B):**

1. Resolve A and B to lakes via name normalization (uppercase, strip
   punctuation, strip trailing " Lake"/" LAKE", strip whitespace). If
   either fails, emit `kind: "approx"` straight line with warning.
2. If same lake: emit a single `paddle` segment (centroid to centroid).
3. If different lakes: search portages whose two endpoints fall inside
   lake A's and lake B's polygons (1-hop search only). If found, emit
   three segments: paddle A→entry, portage entry→exit (geometry from OSM
   line), paddle exit→B. If none found: straight-line `approx` with
   warning.

**Lake name normalization:**

```python
def _norm(name: str) -> str:
    s = name.upper()
    s = re.sub(r"[.\-_,]", "", s)
    s = re.sub(r"\s+LAKE$", "", s)
    return s.strip()

# "OSA Lake" → "OSA"; "O.S.A. Lake" → "OSA"; "Killarney Lake" → "KILLARNEY"
```

**Hardcoded fallback hints** in `route_engine.py`:

```python
LAKE_NAME_HINTS = {
    # Common Killarney lakes that are sometimes oddly tagged in OSM.
    # Keys are normalized names; values are alternate normalized names
    # to also match.
    "OSA": ["O S A"],
    "BAIE FINE": ["BAIE-FINE", "BAIEFINE"],
}
```

**Point-in-polygon:** ray-casting algorithm, ~10 lines. No external deps.

**Time math:**

```python
PADDLE_KMH = 4.0
PORTAGE_KMH = 2.0
# "2 carries" = walk loaded, walk back empty, walk loaded again = 3 traversals
# of the portage trail per portage segment.
PORTAGE_TRAVERSALS = 3
BUFFER_PCT = 0.15

def estimate_minutes(paddle_km: float, portage_km: float) -> int:
    paddle_min = paddle_km * 60 / PADDLE_KMH
    portage_min = portage_km * PORTAGE_TRAVERSALS * 60 / PORTAGE_KMH
    return round((paddle_min + portage_min) * (1 + BUFFER_PCT))
```

**Display rounding:**

- Paddle distance: 0.1 km
- Portage distance: 0.1 km
- Total time: round to nearest 5 minutes; format as "Xh Ym" (e.g. "2h 15m"
  or "45m" if under 1 hour).

### `build_trip.py` modifications

`render_route_section()` becomes a switch:

```python
def render_route_section(trip: dict) -> str:
    # 1. User-supplied route file wins (existing behavior).
    if trip.get("route_file"):
        return _render_user_route(trip["route_file"])

    # 2. Auto-route from OSM if we have nights + access_point.
    fm = trip["frontmatter"]
    if fm.get("nights") and fm.get("access_point"):
        try:
            osm = osm_data.load_killarney_features()
        except FileNotFoundError:
            return _render_no_osm_warning()
        route = route_engine.build_route(
            nights=fm["nights"],
            access_point=fm["access_point"],
            osm=osm,
        )
        return _render_auto_route(route)

    # 3. No route data at all — section omitted.
    return ""
```

`_render_auto_route(route)` produces:

- The map (passing `route["leaflet_route"]` through existing
  `route_map.generate_map_section`).
- The per-day estimates table beneath the map.
- Any warnings as a `<p class="warning">` block above the map.

**CLI:** `build_trip.py` gets a `--refresh-osm` flag. When set, calls
`osm_data.refresh_killarney_cache()` before the normal build flow.

### Per-day table layout

| Day | Leg | Paddle | Portage | Est. time |
|-----|-----|--------|---------|-----------|
| Fri 2026-05-15 | George Lake → OSA Lake (site 61) | 5.2 km | 0.4 km | 2h 15m |
| Sat 2026-05-16 | OSA Lake → Baie Fine (site 82) | 8.1 km ⚠ | (approx) | 2h 0m |
| Sun 2026-05-17 | Baie Fine → Killarney Lake (site 12) | 6.5 km | 0.7 km | 3h 0m |
| Mon 2026-05-18 | Killarney Lake → George Lake | 4.8 km | 0.0 km | 1h 15m |
| **Total** | | **24.6 km** | **1.1 km** | **8h 30m** |

⚠ marker = leg degraded to straight-line because no connecting portage
was found in OSM data. The "(approx)" word in the portage column makes
the failure mode visible to the reader.

## Testing

`tests/test_route_engine.py` — unit tests with a tiny synthetic OSM
fixture (two square "lakes" + one "portage" connecting them):

1. `test_normalize_lake_name` — verifies `_norm()` matches
   `"OSA Lake"` ↔ `"O.S.A. Lake"` ↔ `"osa"`.
2. `test_point_in_polygon` — point inside, point outside, point on edge.
3. `test_build_route_same_lake` — A and B in same lake → one paddle
   segment, zero portage_km.
4. `test_build_route_two_lakes_with_portage` — A and B in different
   lakes, connecting portage exists → 3 segments, correct distances.
5. `test_build_route_no_portage_falls_back` — A and B in different
   lakes, no portage → 1 approx segment, warning emitted.
6. `test_estimate_minutes_formats_time` — `paddle_km=4, portage_km=0` →
   `human_time == "1h 10m"` (60 min × 1.15 = 69 → round to 70 = "1h 10m").

`tests/fixtures/sample-osm.json` — committed fixture, hand-written, ~30
lines. Used by all `route_engine` tests via `_load_fixture()` helper.

`osm_data.py` is **not** unit-tested for the live Overpass call (network
dependency). It does get a parser test against a saved Overpass response
fixture so we know the cache shape stays consistent.

## File changes summary

**New:**
- `osm_data.py`
- `route_engine.py`
- `osm_killarney_cache.json` (committed, refresh via `--refresh-osm`)
- `tests/test_route_engine.py`
- `tests/test_osm_data.py` (parser only, no network)
- `tests/fixtures/sample-osm.json`
- `tests/fixtures/overpass-response.json` (sample Overpass output)

**Modified:**
- `build_trip.py` (router section becomes a switch; new `--refresh-osm` flag)

**Killarney trip data:**
- `trips/killarney-2026-05/trip.html` regenerated to include the new section.

## Implementation order

Each step recoverable; trip page renders correctly at every commit even
mid-implementation (just without the new section until step 5).

1. `osm_data.py` + `refresh_killarney_cache()` + run it once to populate
   `osm_killarney_cache.json`. Commit cache.
2. `route_engine.py`:
   a. `_norm()` + `_point_in_polygon()` helpers + tests.
   b. `build_route()` for same-lake and two-lake-with-portage cases + tests.
   c. Approximate fallback + warning emission + tests.
   d. `estimate_minutes()` and `format_human_time()` + tests.
3. `build_trip.py` integration: switch in `render_route_section`, table
   renderer, warning block, `--refresh-osm` CLI flag.
4. Re-run `build_trip.py trips/killarney-2026-05/`. Commit refreshed
   `trip.html`.
5. Smoke test in browser.

## Risks & open questions

- **OSM data quality.** If Killarney portage coverage is much worse than
  expected (say 0/3 connecting portages found), the page will render
  with three ⚠ "approx" rows and the map will show only straight lines
  between lake centroids. Still useful as a planning artifact but
  visibly degraded. Mitigation: after step 1, eyeball the cache; if
  it's clearly thin, consider hardcoding a few known portages as
  supplementary data in `route_engine.py`.
- **Lake polygon centroid offsets.** The geometric centroid of a
  long thin lake (Baie Fine especially) can fall in an awkward spot.
  Acceptable for a v1; if it looks bad on the map, swap to the
  largest-inscribed-circle center later.
- **Cache size.** ~50-200KB committed JSON. Fine. If we add more parks
  later we'd revisit.
