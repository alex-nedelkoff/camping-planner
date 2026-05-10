---
title: Jeff's Maps vectorizer — Phase 1 (lakes + campsites)
date: 2026-05-09
status: draft
---

# Jeff's Maps vectorizer — Phase 1 (lakes + campsites)

## Goal

Extract lake polygons and numbered campsite locations from Jeff's "Full
French River and Killarney Paddling Map" KMZ (Google Earth super-overlay
format) into a committed JSON cache that augments
`osm_killarney_cache.json`. Solves two real problems for the trip planner:

1. **Baie Fine is missing from OSM** as a separate lake. Jeff's Map shows
   it clearly; extraction yields a real polygon and centroid.
2. **Manual `gps:` overrides per night.** Every backcountry site on Jeff's
   Map has a numbered icon. Extracting these eliminates the need for users
   to look up site GPS by hand — auto-resolved at trip render time.

Out of scope for this spec (deferred Phase 2+): portage line extraction,
place name OCR, support for parks Jeff hasn't published.

## Source format (confirmed)

The KMZ is `Maps by Jeff - Full French River and Killarney Paddling Map
v4.0 - Google Earth.kmz`, a Google Earth super-overlay tile pyramid:

- 8 zoom levels (0 = whole region overview, 7 = highest detail).
- Each level has a quadtree of tiles; level N has ~4× the tiles of level N-1.
- Tiles are PNG/JPG with axis-aligned `LatLonBox` bounds in their per-tile KML
  (rotation=0 throughout — confirmed by inspection).
- **No vector data anywhere** (no Placemarks, LineStrings, or Points). Pure
  raster overlays.
- Total covered area: ~50 km × 200 km (French River corridor + Killarney).
- Killarney bbox alone (45.92–46.12 N, -81.60 to -81.25 W) covers:
  - Level 5: 84 tiles (~20 MP if mosaicked)
  - Level 6: 318 tiles (~80 MP)
  - Level 7: 1168 tiles (~300 MP — too big to mosaic naively)

Filename and structure subject to change with future map versions; the
extractor identifies tiles by parsing per-tile KML rather than hardcoding
paths.

## Constraints

- **Copyright.** The KMZ is a paid product. The raw KMZ is `.gitignore`d
  and never committed. The vectorized output (`jeffs_killarney_cache.json`)
  is a derived dataset; treat as personal-use only and don't redistribute.
- **One-shot extraction.** Re-runs only when Jeff publishes a new map
  version (rare). The cache file is the canonical artifact for collaborators.
- **Augment, don't replace.** OSM data still loads; Jeff's data merges in
  on top, winning conflicts on lake-name match. Trips planned in regions
  Jeff's hasn't covered fall back to OSM unchanged.
- **No new heavy services.** OpenCV and Tesseract are local dependencies.
  No cloud OCR, no map-server calls.
- **Bounded by region.** The extractor takes a bbox argument and only
  processes tiles intersecting it. Killarney's bbox is the default; same
  pipeline can run on French River later by changing the bbox.

## Architecture

```
KMZ file                                  (~117 MB, gitignored)
   │
   ├── jeffs_killarney_overrides.yaml     (manual lake/site overrides)
   ├── lakes_palette.yaml                 (HSV thresholds)
   ├── campsites_palette.yaml             (HSV thresholds)
   └── --bbox argument                    (target region; default Killarney)
            │
            ▼
     jeffs_extractor.py  (new module, single CLI)
            │  ├─ Stage A': KMZ traversal (filter tiles by bbox)
            │  ├─ Stage B:  lake polygons (level 6 mosaic + color seg)
            │  ├─ Stage C:  campsites (level 7 per-tile + OCR)
            │  └─ Stage D:  output assembly + review HTML
            │
            ▼
     jeffs_killarney_cache.json   (committed; ~50-200 KB)
            │
            ▼
   osm_data.load_killarney_features()
   merges OSM + Jeff's:
     - lakes:      Jeff's wins on name conflict
     - portages:   OSM only (Phase 1 doesn't extract portages)
     - campsites:  Jeff's only (new top-level key)
            │
            ▼
   route_engine.build_route()  (no signature change)
   route_engine._night_point()  (now auto-resolves site GPS from campsites)
```

## Components

### `jeffs_extractor.py` (new, ~450 lines)

Single CLI tool, multiple stages. Each stage is a top-level function so
each is independently testable.

#### CLI

```
python3 jeffs_extractor.py path/to/jeffs.kmz \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --overrides jeffs_killarney_overrides.yaml \
  --lakes-palette lakes_palette.yaml \
  --campsites-palette campsites_palette.yaml \
  --out jeffs_killarney_cache.json \
  --review-html jeffs_review.html
```

Auxiliary flags:
- `--lakes-only` / `--campsites-only` — skip one stage during iteration.
- `--zoom-lakes 6 --zoom-campsites 7` — override default zoom levels.
- `--temp-dir /tmp/jeffs_extracted` — keep extracted tiles around for
  inspection (default: clean up after run).

#### Stage A': KMZ traversal

Function: `walk_kmz(kmz_path, bbox, zoom_level) -> Iterable[Tile]`.

Steps:
1. Unzip KMZ to a temp directory (using `zipfile.ZipFile`).
2. Recursively scan for `*.kml` files under the chosen zoom-level directory
   (e.g., `<temp>/6/`).
3. For each KML, parse the `<GroundOverlay>/<LatLonBox>` and `<Icon>/<href>`
   elements. Resolve the href relative to the KML's directory.
4. Compute tile-bbox vs target-bbox intersection. Skip tiles that don't
   intersect.
5. Yield `Tile(image_path, north, south, east, west)` for each surviving tile.

Pixel-to-GPS for any tile is straightforward linear interpolation:

```python
def tile_pixel_to_gps(tile, px, py, img_w, img_h):
    lon = tile.west + (px / img_w) * (tile.east - tile.west)
    lat = tile.north - (py / img_h) * (tile.north - tile.south)
    return [lat, lon]
```

(Inverse for GPS-to-pixel when stitching.)

No homography needed; every tile is axis-aligned. Validation: assert
`rotation=0` while parsing; hard-fail if any tile has non-zero rotation
(would require a different transform).

#### Stage B: Lake polygon extraction

For lakes we use a **mosaic approach** at zoom level 6 (~318 Killarney
tiles, ~80 MP final image). Lake polygons are large features; level 6
resolution is plenty.

Function: `extract_lakes(kmz_path, bbox, palette, overrides, osm_lakes) -> [Lake]`.

Steps:

1. Walk KMZ at zoom level 6, collect tiles intersecting bbox.
2. Compute mosaic pixel dimensions: pick the tile-pixel scale of the
   highest-resolution tile (tiles at the same zoom level should match), then
   compute the mosaic's pixel size from the bbox span.
3. Allocate a numpy uint8 RGB mosaic. Paste each tile at its computed
   pixel position (use `tile_gps_to_pixel` against the mosaic's bbox).
4. Convert mosaic BGR → HSV.
5. Build water mask via `cv2.inRange(hsv, low, high)` using thresholds
   from `lakes_palette.yaml`. Default starting palette (tuned on first run):

   ```yaml
   hue:        [85, 110]
   saturation: [40, 200]
   value:      [180, 255]
   ```

6. Morphology to clean the mask:
   - `MORPH_CLOSE` 5×5 kernel — fill label-text holes, anti-aliasing.
   - `MORPH_OPEN` 3×3 kernel — remove specks.
7. `cv2.findContours(mask, RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)`. Each
   external contour is a lake candidate.
8. Filter contours by `cv2.contourArea` < `min_area_px` (default 500).
9. Simplify each surviving contour with `cv2.approxPolyDP` at
   ε = 0.001 × perimeter.
10. Project each polygon's mosaic-pixel coords through the inverse mosaic
    transform → `[[lat, lon], ...]`.
11. Compute centroid as the simple average of polygon vertices in GPS.

**Naming step** (`assign_names(lakes, osm_lakes, overrides) -> [Lake]`):

1. For each unnamed Jeff's polygon, find the closest OSM lake centroid
   (haversine distance). If distance < 500m, assign `name = osm_lake.name`.
2. For unmatched polygons, check `overrides.lakes` for any
   `centroid_near: [lat, lon], name: "X"` entry whose `centroid_near` is
   within 500m. Apply.
3. Polygons still unnamed printed to stdout as warnings:
   `Unnamed polygon at [46.020, -81.510] (area 38421 px²)` so user
   can add overrides and re-run.
4. Polygons with names go into the final output's `lakes:` list.

Output: list of `Lake` dicts matching the existing OSM lake schema
(`name`, `polygon`, `centroid`).

#### Stage C: Campsite extraction

For campsites we use **per-tile processing at zoom level 7** (~1168
Killarney tiles). Campsite icons are small (~15-25 px); level 7 gives the
detail needed for icon detection and OCR.

Three sub-stages.

**Sub-stage C1 — Icon detection** (`detect_icons_in_tile(tile, image, palette) -> [Icon]`):

1. Load tile image; HSV mask using `campsites_palette.yaml` (Jeff's icon
   color — typically red/orange; tuned on first run).
2. Light morphology: `MORPH_CLOSE` 3×3 to consolidate broken icons.
3. `cv2.connectedComponentsWithStats` to find blobs.
4. Filter blobs:
   - area in [50, 2000] px²
   - aspect ratio in [0.5, 2.0]
5. Yield `Icon` dicts with `pixel_center` `(px, py)` (in tile coords),
   `bbox` `(x, y, w, h)`, and reference back to the originating tile.

**Fallback** if color segmentation produces too many false positives:
template matching with a single icon template (`templates/jeffs_campsite.png`).
CLI flag `--icon-method=template` switches the mode.

**Sub-stage C2 — Number OCR** (`ocr_icon_numbers(tile, image, icons) -> [IconWithRef]`):

For each icon:
1. Crop bounding box around it: `(x - 30, y - 30, x + w + 30, y + h + 30)`,
   clipped to tile bounds.
2. Pre-process the crop:
   - Convert to grayscale.
   - Gaussian blur 3×3.
   - Otsu threshold to binarize.
3. Run Tesseract: `pytesseract.image_to_data(crop, config='--psm 7 -c
   tessedit_char_whitelist=0123456789')`. Use `image_to_data` (not
   `image_to_string`) for per-character confidence.
4. Filter: drop characters with confidence < 60. Concatenate surviving
   digits → `ref` string. If empty after filter: `ref = None`, log warning.

**Sub-stage C3 — Aggregation across tiles** (`aggregate_campsites(all_icons, lakes, overrides) -> [Campsite]`):

After per-tile processing across all level-7 Killarney tiles:

1. For each icon, project pixel → GPS via the originating tile's
   `tile_pixel_to_gps`.
2. **Deduplicate**: if two icons in different tiles are within 10m of each
   other in GPS (boundary overlap), keep the one with the higher OCR
   confidence (or merge if both have the same `ref`).
3. **Apply overrides** from `overrides.campsites`: any
   `centroid_near: [lat, lon], ref: '82'` entry overrides OCR for icons
   within 50m of `centroid_near`.
4. **Lake assignment**: for each surviving icon, point-in-polygon against
   Stage B's lake polygons. Tag with `lake = polygon.name` if contained;
   else `lake = null` and warn.

Final campsite shape:

```json
{
  "campsites": [
    {"ref": "61", "lake": "OSA Lake", "gps": [46.063, -81.392]},
    {"ref": "82", "lake": "Baie Fine", "gps": [46.044, -81.504]},
    {"ref": null, "lake": "Killarney Lake", "gps": [46.045, -81.347],
     "warning": "OCR failed; add to overrides"}
  ]
}
```

#### Stage D: Output assembly + review HTML

The final `jeffs_killarney_cache.json`:

```json
{
  "lakes": [
    {"name": "Killarney Lake", "polygon": [[lat,lon],...], "centroid": [...]},
    {"name": "Baie Fine", "polygon": [...], "centroid": [...]}
  ],
  "campsites": [...],
  "_meta": {
    "source_kmz": "Maps by Jeff - Full ... v4.0 ... .kmz",
    "extracted_at": "2026-05-10T...",
    "bbox": [45.92, -81.60, 46.12, -81.25],
    "lakes_zoom": 6,
    "campsites_zoom": 7,
    "tiles_processed_lakes": 318,
    "tiles_processed_campsites": 1168,
    "lakes_count": 47,
    "campsites_count": 312,
    "campsites_ocr_failed": 4
  }
}
```

Review HTML (`jeffs_review.html`): a single self-contained file with:
- The level-6 mosaic embedded as base64 background (~80 MP scaled down to
  ~4000 px wide for in-browser rendering).
- SVG overlays of each detected lake polygon, color-coded; lake name as
  hover tooltip.
- SVG circles for each campsite at its GPS-projected pixel coords, with
  `ref` as label.
- Summary panel: counts, unnamed polygons, OCR failures.

User opens this in a browser to visually verify before committing the
cache. Fixes go into the YAML overrides; re-run extractor.

### `osm_data.py` modifications

Currently `load_killarney_features()` returns `{lakes, portages}` from
`osm_killarney_cache.json`. After this change:

```python
def load_killarney_features() -> dict:
    osm = json.loads(OSM_CACHE_PATH.read_text())
    out = {"lakes": list(osm["lakes"]),
           "portages": list(osm["portages"]),
           "campsites": []}

    if JEFFS_CACHE_PATH.exists():
        jeffs = json.loads(JEFFS_CACHE_PATH.read_text())
        # Lakes: Jeff's wins on name conflict.
        jeffs_names = {l["name"] for l in jeffs.get("lakes", [])}
        out["lakes"] = (
            [l for l in out["lakes"] if l["name"] not in jeffs_names]
            + jeffs["lakes"]
        )
        out["campsites"] = jeffs.get("campsites", [])

    return out
```

`refresh_killarney_cache()` is unchanged — it only refetches OSM. Jeff's
cache is regenerated separately by running `jeffs_extractor.py`.

### `route_engine.py` modifications

`_night_point()` (currently a closure inside `build_route()` that captures
`lakes`) becomes a closure that also captures `campsites`:

```python
def _night_point(night):
    # 1. Frontmatter override wins.
    gps = night.get("gps")
    if gps and len(gps) == 2:
        return [gps[0], gps[1]]
    # 2. Auto-resolve from Jeff's campsites by (ref, lake).
    site_ref = str(night.get("site", ""))
    location = night.get("location", "")
    for cs in osm.get("campsites", []):
        if cs.get("ref") == site_ref and cs.get("lake") == location:
            return [cs["gps"][0], cs["gps"][1]]
    # 3. Fall back to lake centroid.
    lake = _find_lake(location, lakes)
    return lake["centroid"] if lake else None
```

`build_route()` already receives `osm` so `osm["campsites"]` is in scope.
Existing tests don't supply `campsites`, so they fall through paths 1 and
3 — backwards compatible.

### Test plan (`tests/test_jeffs_extractor.py`)

Unit-testable parts (no real KMZ required):

1. `test_walk_kmz_yields_tiles_in_bbox` — synthetic mini-KMZ with 4 tiles
   (programmatically built in the test setUp), bbox covers 2 of them;
   verify exactly 2 yielded.
2. `test_tile_pixel_to_gps_linear_interpolation` — known LatLonBox, known
   pixel; verify GPS within 1m of expected.
3. `test_extract_lakes_finds_synthetic_blue_blob` — draw a blue circle on
   a 200×200 white mosaic, run `extract_lakes` against an HSV palette
   matching the blue; verify exactly one polygon emitted.
4. `test_simplify_polygon_preserves_shape` — irregular octagon; simplified
   output has < 20 vertices but Hausdorff distance < 5 px from original.
5. `test_assign_lake_names_uses_osm_within_500m` — 3 fake polygons, 2 with
   centroids near OSM lakes (named correctly), 1 unmatched (no name).
6. `test_assign_lake_names_uses_overrides_for_unmatched` — overrides YAML
   provides a name for the unmatched polygon; verify named.
7. `test_aggregate_campsites_dedups_within_10m` — two icons at GPS 1m
   apart with same `ref`; aggregator outputs one.
8. `test_aggregate_campsites_assigns_lake_via_point_in_polygon` — fake
   campsite inside fake lake polygon; verify assigned.
9. `test_ocr_filter_drops_low_confidence` — mock pytesseract output with
   mixed confidence; verify only high-confidence digits kept.

CV-heavy parts get smoke tests with programmatically drawn synthetic
images (`cv2.rectangle`, `cv2.circle`, etc.); no committed binary fixtures.

These don't replace tuning on the real Jeff KMZ — that's empirical work
during the extraction iteration loop. The tests catch regressions on the
algorithmic core.

### File changes summary

**New:**
- `jeffs_extractor.py`
- `jeffs_killarney_overrides.yaml` (starts: `lakes: [], campsites: []`)
- `lakes_palette.yaml`
- `campsites_palette.yaml`
- `jeffs_killarney_cache.json` (committed; produced by extractor)
- `tests/test_jeffs_extractor.py`
- `tests/fixtures/synthetic_kmz.py` (helper that builds a tiny KMZ
  programmatically at test time)

**Modified:**
- `osm_data.py` (merge Jeff's into load result)
- `route_engine.py` (`_night_point` auto-resolves campsite GPS)
- `requirements.txt` (`opencv-python>=4.8`, `pytesseract>=0.3.10`,
  `pillow>=10.0`)
- `.gitignore` (`*.kmz`, `*.kml` outside templates, `templates/jeffs_campsite.png`)
- `README.md` (Tesseract install note: `brew install tesseract` on macOS,
  `apt install tesseract-ocr` on Linux; one-paragraph extractor overview)

**NOT modified:**
- `gpx_library.py`, `route_engine.build_route()` core logic, `build_trip.py`
  rendering — Jeff's data flows through existing pipelines without schema
  changes.

## Implementation order

Each step is testable and reversible.

1. Add OpenCV + pytesseract + pillow to `requirements.txt`. Document
   Tesseract binary install in README. Add `.gitignore` rule for `*.kmz`.
2. Build Stage A' (`walk_kmz`, `tile_pixel_to_gps`, bbox filtering).
   Unit-test against a programmatically-built mini-KMZ.
3. Build Stage B's mosaic builder + lake-extraction pipeline. First run
   on real KMZ at level 6 is the lakes-palette-tuning loop — expect
   1-2 hours.
4. Build the naming step (auto-match against OSM + overrides).
5. Wire Jeff's lakes into `osm_data.py`. Regenerate trip page; verify
   Baie Fine renders as a real polygon and OSA→Baie Fine→Killarney legs
   no longer fall to approx-fallback.
6. Build Stage C1 (icon detection in single tile). Tune
   `campsites_palette.yaml` on a level-7 Killarney tile.
7. Build Stage C2 (OCR) + override system. Iterate on accuracy.
8. Build Stage C3 (aggregate + dedupe + lake assignment).
9. Wire campsites into `route_engine._night_point` auto-fill. Remove
   manual `gps:` from Killarney trip; verify identical or better marker
   placement.
10. Build review HTML.
11. Commit `jeffs_killarney_cache.json`. Push. Pizza-zip pulls; trip
    page renders with the new data.

## Risks & open questions

- **Palette tuning.** First-run HSV thresholds need 1-2 hours of
  iteration against the actual mosaic. Review HTML makes this fast
  (visually obvious when the threshold is wrong). Palette files are YAML
  so changes are one-liners.
- **OCR accuracy.** Tesseract on small numbered icons is the highest
  uncertainty piece. If accuracy < 80% we fall back to per-digit
  template matching (~3h extra). Override system handles individual
  failures cleanly.
- **Mosaic memory.** Level 6 Killarney mosaic is ~80 MP × 3 channels =
  ~240 MB in memory uncompressed. Fine on a Mac. If it ever balloons,
  drop to level 5 (~20 MP) — lake shapes don't need finer resolution.
- **Per-tile feature splits.** A campsite icon at the boundary of two
  level-7 tiles could be split into two halves and missed by both
  detectors. Mitigation: in Stage C, run icon detection on each tile
  with a small overlap zone (e.g., expand each tile bbox by 5% before
  loading the image — Google Earth's pyramid tiles already include some
  overlap, so this may be a no-op).
- **Copyright.** Spec assumes vectorized output is personal-use only,
  consistent with how the user purchased the map. The cache lives in a
  private repo. If the repo ever goes public, the cache should NOT be
  included.
- **Phase 2 dependencies.** Portage extraction (Phase 2) will share the
  KMZ traversal, mosaic builder, palette config, and overrides infra.
  Designing the YAML overrides with `lakes:`, `campsites:`, and a
  future `portages:` key keeps Phase 2 a smaller add.
