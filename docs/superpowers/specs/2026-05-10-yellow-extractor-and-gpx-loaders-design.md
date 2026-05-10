# Yellow Extractor Refresh + GPX Loaders for Campsites & Portages

**Status**: Approved 2026-05-10. Ready for implementation plan.

## Goal

Replace OSM's sparse 11 portages and Jeff's incomplete campsite cache with canonical GPX-sourced data (110 portages, 214 campsites). Refresh the yellow paddle-path extractor with an OCR text-removal pre-pass for cleaner output. Migrate all data caches to a `data/` directory.

## Context

### Current state

`osm_data.load_killarney_features()` returns:
- `lakes` — 81 polygons (51 OSM-named + 30 Jeff's named/unnamed). **Sufficient.**
- `portages` — 11 from OSM Overpass. **Inadequate** (Killarney has 110).
- `campsites` — extracted from Jeff's KMZ raster. **Inconsistent coverage.**
- `paths` — 72 yellow polylines from `jeffs_paths_extractor.py`. **Working but noisy** (yellow text glyphs on labels become spurious polylines).

### New data sources (already in repo at root)

- `killarneyCampsites.gpx` — 214 waypoints, one per site, with name (campsite number) and GPS. Source: PaddlePlanner.com.
- `killarneyPortages.gpx` — 220 waypoints (110 portages × 2 endpoints), each with portage ID and length in meters.

These are canonical. Replace OSM/Jeff's fallback data with them where coverage exists.

### Future enhancement (deferred)

Closed-loop parameter tuning for the yellow extractor (score extraction palette params against known GPX waypoint positions, optimize). Out of scope for this spec.

## Architecture

```
                           data/
                           ├── killarneyCampsites.gpx     (214 sites)
                           ├── killarneyPortages.gpx      (110 portages, 220 endpoints)
                           ├── osm_killarney_cache.json   (lakes + sparse OSM portages)
                           ├── jeffs_killarney_cache.json (Jeff lake polygons)
                           └── jeffs_canoe_paths.json     (yellow polylines from KMZ)
                                       │
                                       ▼
   gpx_loader.py ──┐    osm_data.load_killarney_features()
   (pure parse)    │           │ merges everything
                   └──────────►│
                               ▼
              { lakes, portages, campsites, paths }
                               │
                               ▼
                      route_engine.build_route()
                      paddle_router.route_paddle_leg()
                      app/services/...

   jeffs_paths_extractor.py (KMZ → jeffs_canoe_paths.json)
        + new: OCR text-removal pre-pass for cleaner masks
```

## Components

### 1. `gpx_loader.py` (new)

Pure parsing module. No I/O beyond reading the supplied path. No dependency on OSM, route engine, or anything project-specific. Easy to test in isolation.

```python
def load_campsites(path: Path) -> list[dict]:
    """Returns: [{'name': '61',
                  'lat': 46.05199,
                  'lon': -81.36224,
                  'desc': 'Killarney 61, Open-Potential, ...'},
                 ...]
    """

def load_portages(path: Path) -> list[dict]:
    """Returns one entry per UNIQUE portage ID:
    [{'name': '42056',
      'endpoints': [[46.03524, -81.38126], [46.03535, -81.38053]],
      'line':      [[46.03524, -81.38126], [46.03535, -81.38053]],
      'length_km': 0.058,
      'source':    'gpx'},
     ...]

    Two GPX waypoints sharing a name are paired into one record.
    `line` field matches the shape OSM portages use (list of [lat, lon]
    points along the trail) so the route engine treats both sources
    identically. With only endpoints in GPX, `line` is the straight-line
    pair — sufficient for routing and time estimation.
    """
```

**Length parsing**: GPX `<desc>` contains `"~117 meters (23 rods)"`. Extract the meters, convert to km. If parse fails, fall back to haversine of the two endpoints.

**Edge cases**:
- Orphan waypoints (single wpt with a given name): logger.warning, skip portage
- Empty/malformed GPX: raise `ValueError` (caller invariant — user authored these files)
- Description missing entirely: haversine fallback

### 2. `osm_data.py` integration

Three edits to `load_killarney_features()`:

**Path constants**: introduce `DATA_DIR = Path(__file__).parent / "data"`. Update all 5 cache/data paths to point under it.

**Campsites**: GPX is canonical, replaces existing `out["campsites"]`.

```python
if CAMPSITES_GPX_PATH.exists():
    out["campsites"] = gpx_loader.load_campsites(CAMPSITES_GPX_PATH)
```

**Portages: GPX merged with OSM via spatial dedup**. GPX is canonical for Killarney; OSM portages whose midpoint is within 200m of any GPX portage midpoint are dropped (same portage, both sources). OSM portages outside that radius (other parks, gaps) are kept. Result: 110 GPX + 0–few OSM stragglers.

```python
def _merge_portages(osm_portages, gpx_portages, spatial_dedup_m=200) -> list:
    """GPX is canonical. Drop OSM portages whose midpoint is within
    spatial_dedup_m of any GPX portage midpoint."""
```

Spatial-dedup, not name-matching: GPX IDs (`42056`) and OSM names don't align. Proximity is the only reliable match.

**Campsite lookup helper** (new, called by route engine):

```python
def find_campsite(name: str, campsites: list) -> Optional[dict]:
    """Resolve a trip night's `site: 61` → campsite dict with lat/lon.
    Case-insensitive string match on the `name` field. Returns None if
    no match — caller falls back to existing lake-centroid behavior."""
```

### 3. `jeffs_paths_extractor.py` refresh

One change to `_extract_paths_from_mosaic()`: prepend `_remove_text()` before the HSV color mask.

```python
def _extract_paths_from_mosaic(mosaic_bgr, palette):
    mosaic_bgr = _remove_text(mosaic_bgr)        # NEW
    # ... existing HSV mask → morphology → skeletonize → trace ...

def _remove_text(bgr, conf_min=25, pad_px=3):
    """Tesseract --psm 11 sparse text detection. White-fill every detected
    bbox before color masking. Lazy-import pytesseract; if unavailable,
    return bgr unchanged."""
```

**Properties**:
- **Lazy import + graceful degradation**: missing pytesseract or tesseract binary → return bgr unchanged. No hard new dependency.
- **CLI flag**: `--skip-text-removal` for debugging or explicit fallback to old behavior.
- `requirements.txt` notes pytesseract as optional. README mentions `brew install tesseract` recommended.

**Expected impact**: yellow letterforms in distance markers (`"0.6km"`, `"23m"`) along yellow paths no longer become noise polylines. The 72-polyline output shrinks toward ~50 cleaner polylines. Downstream `paddle_router` snap logic handles either count — strict quality improvement.

### 4. Route engine integration

Two surgical edits to `route_engine.py`:

1. `_night_point()`: when a night has `site: <number>`, call `find_campsite(site, osm["campsites"])` and use its GPS instead of falling back to lake centroid.
2. No other change. GPX portages with `source: 'gpx'` look identical to OSM portages structurally, so existing portage-traversal code handles them transparently.

### 5. File-layout migration

Move 5 files to `data/`:
- `osm_killarney_cache.json`
- `jeffs_killarney_cache.json`
- `jeffs_canoe_paths.json`
- `killarneyCampsites.gpx`
- `killarneyPortages.gpx`

`git mv` to preserve history. Single atomic commit. Update path constants in `osm_data.py`. Update `jeffs_paths_extractor.py` default `--out` argument. Update `CLAUDE.md` "Project files" section. Verify `.gitignore` has no stale references; confirm `tests/test_osm_data.py` doesn't pin absolute paths.

## Data flow

1. **Load**: `osm_data.load_killarney_features()` reads `data/osm_killarney_cache.json` (existing), then layers `gpx_loader.load_campsites(...)` and `gpx_loader.load_portages(...)` on top, then loads `data/jeffs_canoe_paths.json` for yellow paths.
2. **Merge**: `_merge_portages()` deduplicates GPX vs OSM portages by spatial proximity. Campsites are GPX-only (replaces previous extracted-from-Jeff data).
3. **Consume**: route engine reads `osm["portages"]`, `osm["campsites"]`, `osm["paths"]`. Calls `find_campsite()` for site-number resolution.
4. **Render**: yellow extractor (offline tool, run when KMZ updates) produces fresh `data/jeffs_canoe_paths.json` for routing input.

## Error handling

| Failure mode | Behavior |
|---|---|
| GPX file missing at expected path | logger.warning, return empty list — legacy OSM data still loads |
| GPX malformed XML | Raise `ValueError` with file path. Hard fail — invariant the user authored this file |
| Orphan portage waypoint (single endpoint) | logger.warning, skip the portage |
| Tesseract not installed | Extractor logs once, falls back to non-text-removed path |
| `find_campsite()` name not found | Return `None`; caller falls back to existing lake-centroid behavior |
| `_merge_portages()` empty inputs | Return whichever is non-empty; if both empty, return `[]` |

## Testing

New tests, added to existing suite (~9 total, <5s runtime impact):

- `tests/test_gpx_loader.py` (new file, 4 tests):
  - Round-trip: 2-endpoint pair → one portage record
  - Orphan endpoint dropped with warning
  - Length parsed from `~117 meters` description
  - Length fallback to haversine when description missing meters
- `tests/test_osm_data.py` (extend, 2 tests):
  - `_merge_portages` dedups GPX vs nearby OSM, keeps distant OSM
  - `find_campsite` resolves by name, returns None on miss
- `tests/test_jeffs_paths_extractor.py` (extend, 2 tests):
  - `_remove_text` whitens detected text bboxes (synthetic image with rendered word)
  - Graceful degradation when pytesseract missing (monkeypatched ImportError)
- `tests/test_route_engine.py` (extend, 1 test):
  - Site-number → GPS via campsite lookup; falls back to centroid when not found

Existing route engine + extractor end-to-end tests re-run unchanged; expect pass.

## Migration & rollback

**Rollback path**: each component is in its own commit. To revert:
- File migration: `git revert` the move commit
- gpx_loader: `git revert` adds the file
- osm_data integration: `git revert` restores prior portage/campsite handling
- Extractor refresh: `git revert` removes the OCR pre-pass

No data loss in any rollback — input GPX/JSON/KMZ files are untouched.

## Out of scope

- Closed-loop parameter tuning for the extractor (deferred to a follow-up spec).
- Refactoring `osm_data.py` → `killarney_data.py` rename (the file is now misleadingly named, but rename adds churn without immediate benefit).
- Pulling additional GPX datasets (lakes, hiking trails, fishing spots) — same loader can handle them later, but no current consumer.
- Multi-park support (Algonquin, French River, etc.). Killarney-only for this work.

## Implementation order

1. Move files to `data/`, update path constants. Tests pass.
2. Add `gpx_loader.py` with tests.
3. Wire GPX into `osm_data.load_killarney_features()` with tests.
4. Add `find_campsite()` helper, wire into route engine `_night_point()` with test.
5. Refresh `jeffs_paths_extractor.py` with text-removal pre-pass and tests.
6. Re-run extractor against KMZ → fresh `data/jeffs_canoe_paths.json`. Compare polyline count.
7. Final integration: rebuild `trips/killarney-2026-05/trip.html`, run audit. Verify portages count is now 110, campsite GPS is from GPX.

Each step is a self-contained commit; suite passes after each.
