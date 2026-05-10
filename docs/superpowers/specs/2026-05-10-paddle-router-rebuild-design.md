---
title: Paddle router rebuild — yellow paths + centroid curves
date: 2026-05-10
status: draft
---

# Paddle router rebuild — yellow paths + centroid curves

## Goal

Replace the visibility-graph paddle routing in `route_engine.py` with a
two-strategy router that picks Jeff's drawn yellow canoe paths when
available and falls back to a centroid-region curve fitter otherwise. The
visibility-graph approach was a poor fit for canoe routing on lake
polygons — it tries to follow polygon EDGES (designed for navigating
around polygonal obstacles), while paddle routing should pull through
lake INTERIOR.

Concrete wins:
- Paddle lines hug Jeff's recommended canoe routes where he drew them.
- On unmarked lakes, paddle lines arc through open water via a smooth
  curve toward the lake centroid — visually correct, geometrically
  shorter than today's straight + visibility-graph hybrid.
- Per-leg geometry comes back as a densely-sampled curve, so client-side
  spline rendering is no longer needed (and the spline overshoot/knot
  bugs we hit go away by construction).

Out of scope for this spec: portage line extraction (still a separate
Phase 2 effort), Tesseract campsite extraction (already designed and
implemented; runs independently once Tesseract is installed),
multi-lake yellow chaining (each leg picks at most one yellow path).

## Constraints

- **Replace the visibility graph entirely.** No `--routing=spline` flag,
  no opt-in. Cleaner architecture; the visibility-graph code (and its
  perf tax + spline-rendering complexity it forced) is deleted.
- **Performance budget**: trip render under ~5s. Closed-form Bezier
  curve + small yellow-paths lookup table should deliver this; current
  7.5s is dominated by O(V²) visibility checks we're removing.
- **No new heavy dependencies.** `opencv-contrib-python` (for skeletonize)
  is the only candidate; we keep a pure-Python Zhang-Suen fallback so the
  install path stays simple if contrib is unavailable.
- **Yellow extraction is one-shot**, like the lake extractor. Re-runs
  only when Jeff publishes a new map version. Output `jeffs_canoe_paths.json`
  is committed.

## Architecture

```
                jeffs_killarney_cache.json   (lakes, campsites — existing)
                jeffs_canoe_paths.json       (NEW — yellow polylines)
                            │
                            ▼
                osm_data.load_killarney_features() augmented to
                attach `paths: [...]` alongside `lakes` / `portages` /
                `campsites`.
                            │
                            ▼
                route_engine.build_route(...)
                            │
                            ▼  per paddle leg:
                ┌──────────────────────────────────┐
                │ paddle_router.route_paddle_leg() │
                └─────────┬────────────────────────┘
                          │
                          ▼
                  Try yellow path:
                    nearest path with both endpoints within
                    SNAP_TOLERANCE_KM (0.5 km), filtered by
                    LAKE_COVERAGE_PCT (≥70% inside polygon)
                          │
                  found ──▶│ snap entry → walk path → snap exit
                          │
                  none ──▶│
                          ▼
                  Centroid-region curve:
                    Bezier through entry → centroid-pull → exit;
                    order scales with polygon area;
                    sample densely; validate against polygon;
                    retry with smaller pull factor on failure
                          │
                  degenerate ──▶│
                                ▼
                  Straight line [entry, exit]   (final fallback)
```

## Components

### `paddle_router.py` (NEW, ~200 lines)

Pure-geometry helper. No I/O, no caching. Public API:

```python
def route_paddle_leg(entry: list[float], exit: list[float],
                     lake: dict,
                     yellow_paths: list[dict] = ()) -> list[list[float]]:
    """Return geometry [entry, ..., exit] for a paddle leg.

    Tries yellow paths first; falls back to centroid-region Bezier curve;
    final fallback is straight line. Output is a densely-sampled polyline
    so client-side spline rendering is unnecessary.
    """

def fit_paddle_curve(entry, exit, lake) -> list[list[float]]:
    """Bezier curve through entry → centroid-pull → exit.

    Curve order scales with polygon area:
      area < 1 km² → quadratic (1 control point)
      1 ≤ area < 5 km² → cubic (2 control points)
      area ≥ 5 km² → quartic (3 control points)

    Control points pulled CENTROID_PULL (0.4) toward the lake centroid.
    Densely sampled (N = max(20, ceil(distance_km × 30))).
    Validated: every sample inside polygon (multi-polygon water union when
    `lake` carries an `extra_polygons` key, same as today's check).
    On failure, retries with pull factors 0.2, then 0.0 (≈ straight line).
    """
```

**Tunable constants** at top of `paddle_router.py`:
```python
SNAP_TOLERANCE_KM = 0.5
LAKE_COVERAGE_PCT = 0.7
CENTROID_PULL = 0.4
PULL_RETRY_FACTORS = (0.4, 0.2, 0.0)
SAMPLES_PER_KM = 30
SAMPLES_MIN = 20
```

#### Curve sampling math (closed-form, no optimization)

For a cubic Bezier with control points `cp1`, `cp2`:
```
B(t) = (1-t)³·entry + 3(1-t)²t·cp1 + 3(1-t)t²·cp2 + t³·exit
```
where:
```
cp1 = entry + CENTROID_PULL × (centroid - entry)
cp2 = exit  + CENTROID_PULL × (centroid - exit)
```

For quadratic (small lakes), single control = the centroid itself.

For quartic (large lakes), 3 control points distributed at fractions
0.25, 0.5, 0.75 along the entry → centroid → exit polyline, each pulled
toward the centroid by CENTROID_PULL.

**Polygon area** computed via shoelace formula (in degrees², converted
to km² using a planar approximation valid at Killarney latitudes).

#### Yellow-path snap (closed-form geometry)

For each candidate yellow path, find nearest point on the polyline:
```python
def _snap_to_polyline(point, polyline):
    """Closest point on polyline (any segment, not just vertices).
    Returns (snap_point, snap_index, t) where t∈[0,1] within the
    segment between polyline[snap_index] and polyline[snap_index+1].
    """
```

Implementation: for each polyline segment `(p_i, p_{i+1})`, project
`point` onto the segment line, clamp `t` to `[0, 1]`, compute distance.
Return the segment + t with smallest distance. Pure planar projection
(haversine isn't needed at sub-km scales for nearest-point computation;
distance comparison is consistent in either metric).

#### Path orientation

After snapping entry and exit:
- If `snap_index_entry > snap_index_exit`, the path is "going the wrong
  way" — reverse the path's interior subset before walking.
- Path subset = points `[snap_entry, polyline[snap_index_entry+1], ...,
  polyline[snap_index_exit], snap_exit]`. Add intermediate polyline
  vertices in order; clip the partial-segment tails using the t-values.

### `jeffs_paths_extractor.py` (NEW, ~250 lines)

CV pipeline that produces `jeffs_canoe_paths.json` from the KMZ raster.

**CLI:**
```
python3 jeffs_paths_extractor.py <kmz> \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --paths-palette paths_palette.yaml \
  --out jeffs_canoe_paths.json \
  --review-html jeffs_paths_review.html \
  [--zoom 7]
```

**Pipeline:**

1. **Walk KMZ at zoom 7** — reuse `jeffs_extractor.walk_kmz`. Build
   mosaic via `jeffs_extractor.build_mosaic`. Store the mosaic's
   pixel→GPS transform alongside the image.
2. **HSV mask for yellow** — `cv2.inRange` with thresholds from
   `paths_palette.yaml`. Default starting palette:
   ```yaml
   hue:        [22, 38]
   saturation: [120, 255]
   value:      [180, 255]
   ```
3. **Morphological clean**:
   - `MORPH_OPEN` 3×3 to drop isolated yellow blobs (text labels,
     icons on land that aren't trail lines).
   - `MORPH_CLOSE` 2×2 to fill small gaps in the yellow line.
4. **Skeletonize** to a 1-pixel-wide centerline:
   - Try `cv2.ximgproc.thinning(mask, thinningType=cv2.ximgproc.THINNING_GUOHALL)`.
   - If `ximgproc` unavailable, fall back to a pure-Python Zhang-Suen
     thinning (~30 lines).
5. **Trace polylines from skeleton:**
   - Build a pixel-neighbor map (8-connectivity).
   - **Identify nodes**: pixels with degree ≠ 2 (endpoints with
     degree 1, junctions with degree ≥ 3).
   - **Walk each edge**: from each node, follow degree-2 neighbors
     until hitting another node or running out. Each walk emits one
     polyline.
   - Pixels in degree-2 chains that don't touch any node form a closed
     loop — emit as a single polyline (start = end).
6. **Simplify** each polyline with `cv2.approxPolyDP(epsilon=3px,
   closed=False)`. ~10–50 vertices per polyline.
7. **Filter** by length: drop polylines shorter than `min_length_px`
   (default 30, ≈ 100 m at zoom 7) — segmentation noise.
8. **Project to GPS** — each pixel via `mosaic_pixel_to_gps`. Each
   polyline becomes `[[lat, lon], ...]`.

**Output schema:**
```json
{
  "paths": [
    {
      "id": 0,
      "points": [[lat, lon], ...],
      "length_km": 1.42
    },
    ...
  ],
  "_meta": {
    "source_kmz": "Maps by Jeff - ... .kmz",
    "extracted_at": "2026-05-10T...",
    "zoom": 7,
    "bbox": [45.92, -81.60, 46.12, -81.25],
    "count": 47
  }
}
```

**Review HTML:** Leaflet map with each polyline color-cycled, hover for
`id` + `length_km`. Raster underlay so the user can confirm each
extracted polyline matches a real yellow line on Jeff's map. The
`--review-html` flag is required during initial palette tuning.

### `route_engine.py` modifications

**Removed:**
- `_polygon_aware_paddle`
- `_line_inside_polygon`
- `_line_inside_any_polygon`
- `_polygons_overlapping_corridor`
- `_decimate_polygon`
- `_PADDLE_MAX_POLYGON_VERTICES` constant

`_path_distance_km` (haversine-sum over a polyline) STAYS — the new
call sites still use it to compute distance from the router's returned
geometry. About 180 lines of visibility-graph code deleted in total.

**Added:**
- `from paddle_router import route_paddle_leg` import.
- Top-level loader for `osm["paths"]` (the yellow polylines).
- New helper `_yellow_paths_in_lake(lake, all_paths) -> list` —
  filters the paths list to those covering ≥ 70% in the given lake.

**Modified call sites** — three places in `build_route` currently call
`_polygon_aware_paddle(...)`. Each becomes:
```python
yellow_in_lake = _yellow_paths_in_lake(current_lake, osm.get("paths", []))
geom = route_paddle_leg(start_pt, end_pt, current_lake, yellow_in_lake)
segments.append(_segment(... _path_distance_km(geom), geom))
```

### `osm_data.py` modifications

`load_killarney_features()` augmented to read `jeffs_canoe_paths.json`
when present and attach `paths` to the returned dict. Schema:
```python
out = {
    "lakes": [...],
    "portages": [...],
    "campsites": [...],
    "paths": [...],   # NEW
}
```

When the file is missing, `paths` is an empty list — router falls back
to centroid curves + straight lines. Existing trips work unchanged.

### File changes summary

**New:**
- `paddle_router.py`
- `jeffs_paths_extractor.py`
- `paths_palette.yaml`
- `jeffs_canoe_paths.json` (committed; produced by extractor)
- `tests/test_paddle_router.py`

**Modified:**
- `route_engine.py` — remove visibility-graph stack, add router calls
- `osm_data.py` — load `jeffs_canoe_paths.json`, attach `paths` key
- `requirements.txt` — `opencv-contrib-python>=4.8` (with Zhang-Suen
  fallback if unavailable)
- `README.md` — note the new extractor step

**Removed lines:** ~200 (visibility-graph code in `route_engine.py`).
**Added lines:** ~450 (router + extractor + tests).

## Test plan (`tests/test_paddle_router.py`)

Unit tests using synthetic polygons + paths (no real KMZ):

1. `test_fit_paddle_curve_quadratic_for_small_lake` — area 0.5 km² →
   quadratic Bezier. Geometry has ≥ 20 sample points, midpoint pulled
   toward centroid.
2. `test_fit_paddle_curve_cubic_for_medium_lake` — area 2 km² → cubic
   Bezier. Sampled points (excluding endpoints) all inside the polygon.
3. `test_fit_paddle_curve_falls_back_when_curve_leaves_polygon` —
   concave U-shape polygon where 0.4 pull leaves polygon. Verify
   function retries at 0.2, then 0.0; final geometry stays inside.
4. `test_snap_to_polyline_finds_closest_segment_point` — polyline of 3
   points, query off the second segment. Verify snap is on the segment
   interior (not at a vertex).
5. `test_snap_to_polyline_clamps_to_endpoints` — query past the
   polyline's start; verify snap returns the first vertex (t=0).
6. `test_route_paddle_leg_picks_yellow_when_tolerance_met` — yellow
   path within 0.3 km of entry and exit; verify returned geometry
   includes path's interior points (not just entry + exit).
7. `test_route_paddle_leg_falls_back_to_centroid_when_yellow_too_far` —
   yellow path 1.0 km from entry (above SNAP_TOLERANCE_KM); verify
   centroid-curve geometry returned (≥ 20 points, pulled toward centroid).
8. `test_route_paddle_leg_filters_yellow_by_lake_coverage` — yellow
   polyline 60% inside the lake polygon (below LAKE_COVERAGE_PCT);
   verify it's filtered out, fallback used.
9. `test_route_paddle_leg_reverses_path_when_endpoints_inverted` — entry
   snaps near path's end, exit snaps near path's start; verify returned
   geometry walks the path forward-to-exit (reversed).
10. `test_extract_paths_finds_synthetic_yellow_line` — programmatically
    draw a yellow line on a tiny synthetic mosaic; run extractor;
    verify one polyline emitted with reasonable length and GPS
    projection.

## Implementation order

Each step is independently shippable; the trip page renders correctly at
every checkpoint.

1. **Build `paddle_router.py`** — curve fitter + snap-to-polyline +
   `route_paddle_leg`. Unit tests against synthetic polygons + paths.
   Trip page unchanged at this point (router not wired in).
2. **Wire router into `route_engine.build_route`** — replace the three
   `_polygon_aware_paddle` call sites with `route_paddle_leg` calls.
   Pass empty `yellow_paths` initially. Trip renders with centroid
   curves only — already a meaningful upgrade.
3. **Build `jeffs_paths_extractor.py`** — CV pipeline. Run once against
   the user's KMZ to produce `jeffs_canoe_paths.json`. Tune HSV /
   skeletonize knobs via review HTML.
4. **Wire paths through** `osm_data.load_killarney_features` →
   `route_engine.build_route` → `route_paddle_leg`. Trip renders with
   yellow paths preferred where applicable.
5. **Delete visibility-graph code** from `route_engine.py`. Update tests
   accordingly. Net code reduction.
6. **Re-run audit + overlay**. Confirm in-water % improves. Compare
   visually against the raster underlay.

## Risks & open questions

- **Skeletonize edge cases**: yellow lines may have variable thickness
  across the map. Skeleton thinning handles this but can produce
  unexpected branches at junctions. v1 splits at junctions
  (conservative); each branch is a valid sub-path.
- **Snap tolerance tuning**: 0.5 km may be too generous for tightly-
  packed Killarney lakes (could pull a leg onto an unrelated path).
  Visible immediately in the overlay; constant is easy to tune.
- **CV dependency**: `opencv-contrib-python` provides `ximgproc.thinning`.
  We add a pure-Python Zhang-Suen fallback (~30 lines) so installation
  stays simple if `contrib` is unavailable.
- **Curve outside polygon for highly concave shapes**: cubic Bezier
  with control points pulled 40% toward the centroid usually stays
  inside, but a U-shaped lake with entry/exit on opposite arms could
  produce a curve that bows across the bottom of the U into land.
  Mitigated by the retry-with-lower-pull mechanism (0.4 → 0.2 → 0.0);
  worst case is a straight line, same as today.
- **Performance**: closed-form math should be < 5ms per leg. We expect
  trip render time to drop from ~7.5s to ~3s. Verifiable after step 2.
- **Visibility-graph deletion is irreversible** without git revert.
  Anyone who liked the old behavior would have to checkout the old
  code. Mitigated by the implementation order — steps 1-2 ship the new
  centroid-curve behavior alongside the old visibility-graph code; we
  only delete in step 5 once we've confirmed the new approach is at
  least as good.
