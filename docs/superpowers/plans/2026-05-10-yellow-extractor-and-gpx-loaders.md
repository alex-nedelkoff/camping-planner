# Yellow Extractor Refresh + GPX Loaders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace OSM's sparse 11 Killarney portages and Jeff's incomplete campsite cache with canonical GPX-sourced data (110 portages, 214 campsites). Refresh the yellow paddle-path extractor with an OCR text-removal pre-pass. Migrate cached data files to a `data/` directory.

**Architecture:** New `gpx_loader.py` module parses two GPX files (campsites + portages) into route-engine-compatible dicts. `osm_data.load_killarney_features()` merges GPX results with existing OSM polygons and Jeff's lake polygons. `jeffs_paths_extractor.py` gets a lazy-imported OCR pre-pass for cleaner yellow-line masks. Route engine wiring is minimal — GPX portages match OSM portage shape; campsites are resolved via a new `find_campsite()` helper.

**Tech Stack:** Python 3.9, OpenCV (existing), pytesseract (optional, lazy import), standard library xml.etree, pytest.

**Spec:** `docs/superpowers/specs/2026-05-10-yellow-extractor-and-gpx-loaders-design.md`

---

## File Structure

**New files:**
- `gpx_loader.py` — pure GPX → list-of-dicts parsing for campsites and portages. ~120 lines.
- `tests/test_gpx_loader.py` — 5 unit tests with inline GPX string fixtures.
- `data/` — directory housing the 5 cached/source data files (created by git mv).

**Modified files:**
- `osm_data.py` — add `DATA_DIR` and updated path constants, integrate `gpx_loader` into `load_killarney_features()`, add `_merge_portages()` and `find_campsite()` helpers.
- `route_engine.py` — update `_night_point()` to call `find_campsite(site_ref, osm["campsites"])` (replaces existing Jeff's-cache-style lookup).
- `jeffs_paths_extractor.py` — add `_remove_text()` pre-pass + `--skip-text-removal` CLI flag.
- `tests/test_osm_data.py` — add 2 tests (merge dedup, campsite GPX integration).
- `tests/test_route_engine.py` — add 1 test (site-number → GPS via find_campsite).
- `tests/test_jeffs_paths_extractor.py` — add 2 tests (text removal works, graceful no-tesseract).
- `CLAUDE.md` — update "Project files" section paths (5 files now in `data/`).

**Data file moves** (in Task 1, via `git mv`):
- `osm_killarney_cache.json` → `data/osm_killarney_cache.json`
- `jeffs_killarney_cache.json` → `data/jeffs_killarney_cache.json`
- `jeffs_canoe_paths.json` → `data/jeffs_canoe_paths.json`
- `killarneyCampsites.gpx` → `data/killarneyCampsites.gpx`
- `killarneyPortages.gpx` → `data/killarneyPortages.gpx`

---

## Task 1: Move data files to `data/` and update path constants

Atomic file move. No logic changes — just paths. Suite passes before and after.

**Files:**
- Move: 5 files (see above)
- Modify: `/Users/alex/Documents/camping-planner/osm_data.py:20-22`
- Modify: `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py` (default `--out` argument)

- [ ] **Step 1: Create data/ directory and git mv the 5 files**

```bash
cd /Users/alex/Documents/camping-planner
mkdir -p data
git mv osm_killarney_cache.json data/osm_killarney_cache.json
git mv jeffs_killarney_cache.json data/jeffs_killarney_cache.json
git mv jeffs_canoe_paths.json data/jeffs_canoe_paths.json
git mv killarneyCampsites.gpx data/killarneyCampsites.gpx
git mv killarneyPortages.gpx data/killarneyPortages.gpx
ls data/
```

Expected: 5 files listed in `data/`.

- [ ] **Step 2: Update path constants in osm_data.py**

In `/Users/alex/Documents/camping-planner/osm_data.py`, replace lines 20-22:

```python
CACHE_PATH = Path(__file__).parent / "osm_killarney_cache.json"
JEFFS_CACHE_PATH = Path(__file__).parent / "jeffs_killarney_cache.json"
PATHS_CACHE_PATH = Path(__file__).parent / "jeffs_canoe_paths.json"
```

With:

```python
DATA_DIR = Path(__file__).parent / "data"
CACHE_PATH = DATA_DIR / "osm_killarney_cache.json"
JEFFS_CACHE_PATH = DATA_DIR / "jeffs_killarney_cache.json"
PATHS_CACHE_PATH = DATA_DIR / "jeffs_canoe_paths.json"
CAMPSITES_GPX_PATH = DATA_DIR / "killarneyCampsites.gpx"
PORTAGES_GPX_PATH = DATA_DIR / "killarneyPortages.gpx"
```

- [ ] **Step 3: Update default `--out` argument in jeffs_paths_extractor.py**

In `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`, find the argparse line:

```python
    parser.add_argument("--out", required=True)
```

If `--out` is currently `required=True` (no default), leave it — callers pass an explicit path. Check the current state:

```bash
grep -n '"--out"' jeffs_paths_extractor.py
```

If a default is set (e.g., `"jeffs_canoe_paths.json"`), update it to `"data/jeffs_canoe_paths.json"`. Otherwise no change needed.

- [ ] **Step 4: Run the full test suite to verify nothing broke**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ --ignore=tests/test_routes.py -q 2>&1 | tail -5
```

Expected: all tests pass (same count as before). If a test fails citing a path, find and fix the absolute path reference in that test.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add data/ osm_data.py jeffs_paths_extractor.py
git commit -m "refactor: move cached data files to data/ directory"
```

---

## Task 2: `gpx_loader.py` — campsite parsing (TDD)

Pure parsing function for campsite GPX. One waypoint per campsite.

**Files:**
- Create: `/Users/alex/Documents/camping-planner/gpx_loader.py`
- Create: `/Users/alex/Documents/camping-planner/tests/test_gpx_loader.py`

- [ ] **Step 1: Write the failing test**

Create `/Users/alex/Documents/camping-planner/tests/test_gpx_loader.py`:

```python
"""Tests for gpx_loader.py."""
from pathlib import Path

import pytest

from gpx_loader import load_campsites


CAMPSITES_GPX = """<?xml version="1.0" encoding="utf-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="46.02358" lon="-81.41387">
  <name>1</name>
  <desc>Killarney 1, Open-Potential</desc>
</wpt>
<wpt lat="46.05199" lon="-81.36224">
  <name>61</name>
  <desc>Killarney 61, Open-Potential, Avg User Rating: 4 out of 5</desc>
</wpt>
</gpx>
"""


def test_load_campsites_parses_name_lat_lon_desc(tmp_path):
    gpx = tmp_path / "campsites.gpx"
    gpx.write_text(CAMPSITES_GPX)
    sites = load_campsites(gpx)
    assert len(sites) == 2
    assert sites[0] == {
        "name": "1",
        "lat": 46.02358,
        "lon": -81.41387,
        "desc": "Killarney 1, Open-Potential",
    }
    assert sites[1]["name"] == "61"
    assert sites[1]["lat"] == 46.05199
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_gpx_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'gpx_loader'` or `ImportError`.

- [ ] **Step 3: Create gpx_loader.py with load_campsites**

Create `/Users/alex/Documents/camping-planner/gpx_loader.py`:

```python
"""
GPX loaders for Killarney campsite + portage data sourced from
paddleplanner.com. Pure parsing — no I/O beyond reading the supplied path.

Exposed functions:
  load_campsites(path) -> list of campsite dicts
  load_portages(path)  -> list of portage dicts (paired endpoints)
"""
import logging
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

_NS = {"g": "http://www.topografix.com/GPX/1/1"}


def _parse_gpx(path: Path):
    """Parse the GPX file and return (tree, root). Raises ValueError on
    malformed XML."""
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as e:
        raise ValueError(f"Malformed GPX at {path}: {e}") from e
    return tree, tree.getroot()


def load_campsites(path: Path) -> list:
    """Parse a campsite GPX file.

    Returns: list of {"name": str, "lat": float, "lon": float, "desc": str}.
    """
    _, root = _parse_gpx(path)
    out = []
    for wpt in root.findall("g:wpt", _NS):
        name_el = wpt.find("g:name", _NS)
        desc_el = wpt.find("g:desc", _NS)
        name = (name_el.text if name_el is not None else "") or ""
        desc = (desc_el.text if desc_el is not None else "") or ""
        out.append({
            "name": name,
            "lat": float(wpt.attrib["lat"]),
            "lon": float(wpt.attrib["lon"]),
            "desc": desc,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_gpx_loader.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add gpx_loader.py tests/test_gpx_loader.py
git commit -m "feat: gpx_loader.load_campsites for campsite GPX parsing"
```

---

## Task 3: `gpx_loader.py` — portage parsing with endpoint pairing (TDD)

Each portage has 2 GPX waypoints (one per endpoint) sharing the same `<name>`. Pair them into one record. Handle orphans, length parsing from description, and haversine fallback.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/gpx_loader.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_gpx_loader.py`

- [ ] **Step 1: Write 4 failing tests for portage parsing**

Append to `/Users/alex/Documents/camping-planner/tests/test_gpx_loader.py`:

```python
from gpx_loader import load_portages


PORTAGES_GPX = """<?xml version="1.0" encoding="utf-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="46.03524" lon="-81.38126">
  <name>42056</name>
  <desc>Killarney Portage 42056, ~58 meters (11 rods)</desc>
</wpt>
<wpt lat="46.03535" lon="-81.38053">
  <name>42056</name>
  <desc>Killarney Portage 42056, ~58 meters (11 rods)</desc>
</wpt>
<wpt lat="46.10000" lon="-81.50000">
  <name>99999</name>
  <desc>Orphan, no partner</desc>
</wpt>
</gpx>
"""

PORTAGES_GPX_NO_METERS = """<?xml version="1.0" encoding="utf-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="46.0000" lon="-81.0000">
  <name>42100</name>
  <desc>Killarney Portage 42100 (length unknown)</desc>
</wpt>
<wpt lat="46.0010" lon="-81.0010">
  <name>42100</name>
  <desc>Killarney Portage 42100 (length unknown)</desc>
</wpt>
</gpx>
"""


def test_load_portages_pairs_two_waypoints_per_id(tmp_path):
    gpx = tmp_path / "portages.gpx"
    gpx.write_text(PORTAGES_GPX)
    portages = load_portages(gpx)
    # Orphan 99999 is dropped; only 42056 returned.
    assert len(portages) == 1
    p = portages[0]
    assert p["name"] == "42056"
    assert p["endpoints"] == [[46.03524, -81.38126], [46.03535, -81.38053]]
    # `line` mirrors endpoints (straight line between them).
    assert p["line"] == p["endpoints"]
    assert p["source"] == "gpx"


def test_load_portages_drops_orphans_with_warning(tmp_path, caplog):
    import logging
    gpx = tmp_path / "portages.gpx"
    gpx.write_text(PORTAGES_GPX)
    with caplog.at_level(logging.WARNING):
        portages = load_portages(gpx)
    assert all(p["name"] != "99999" for p in portages)
    assert any("99999" in r.message for r in caplog.records)


def test_load_portages_parses_length_from_description(tmp_path):
    gpx = tmp_path / "portages.gpx"
    gpx.write_text(PORTAGES_GPX)
    portages = load_portages(gpx)
    # "~58 meters" → 0.058 km.
    assert abs(portages[0]["length_km"] - 0.058) < 1e-6


def test_load_portages_falls_back_to_haversine_when_no_meters(tmp_path):
    gpx = tmp_path / "portages.gpx"
    gpx.write_text(PORTAGES_GPX_NO_METERS)
    portages = load_portages(gpx)
    assert len(portages) == 1
    # Haversine of [46.0, -81.0] to [46.001, -81.001]:
    # ~0.137 km (1 deg ≈ 111 km, so 0.001 deg lat ≈ 0.111 km;
    # combined ~ sqrt(0.111^2 + 0.0772^2) ≈ 0.135-0.140).
    assert 0.10 <= portages[0]["length_km"] <= 0.20
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_gpx_loader.py -v
```

Expected: 4 new tests fail (`ImportError: cannot import name 'load_portages'`).

- [ ] **Step 3: Implement load_portages with pairing + length parsing**

Append to `/Users/alex/Documents/camping-planner/gpx_loader.py`:

```python
_METERS_RE = re.compile(r"~?\s*(\d+(?:\.\d+)?)\s*meters?", re.IGNORECASE)


def _haversine_km(a: list, b: list) -> float:
    """Distance in km between [lat, lon] points."""
    R = 6371.0
    p1 = math.radians(a[0])
    p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


def _length_km_from_desc(desc: str, endpoints: list) -> float:
    """Parse '~117 meters' from description. Fall back to haversine of
    endpoints if no match."""
    m = _METERS_RE.search(desc or "")
    if m:
        try:
            return float(m.group(1)) / 1000.0
        except ValueError:
            pass
    return _haversine_km(endpoints[0], endpoints[1])


def load_portages(path: Path) -> list:
    """Parse a portage GPX file.

    Two GPX waypoints sharing a name are paired into one portage record
    matching the OSM portage shape (so the route engine treats both
    sources identically). Orphans (single waypoint with a given name) are
    dropped with a logger warning.

    Returns: list of {
        "name": str,
        "endpoints": [[lat, lon], [lat, lon]],
        "line":      [[lat, lon], [lat, lon]],  # straight-line between endpoints
        "length_km": float,
        "source":    "gpx",
    }
    """
    _, root = _parse_gpx(path)
    # Group waypoints by name.
    by_name: dict = {}
    for wpt in root.findall("g:wpt", _NS):
        name_el = wpt.find("g:name", _NS)
        desc_el = wpt.find("g:desc", _NS)
        name = (name_el.text if name_el is not None else "") or ""
        desc = (desc_el.text if desc_el is not None else "") or ""
        lat = float(wpt.attrib["lat"])
        lon = float(wpt.attrib["lon"])
        by_name.setdefault(name, []).append(([lat, lon], desc))

    out = []
    for name, entries in by_name.items():
        if len(entries) != 2:
            logger.warning(
                "Portage %s has %d waypoint(s), expected 2 — skipping",
                name, len(entries),
            )
            continue
        endpoints = [entries[0][0], entries[1][0]]
        desc = entries[0][1] or entries[1][1] or ""
        length_km = _length_km_from_desc(desc, endpoints)
        out.append({
            "name": name,
            "endpoints": endpoints,
            "line": [list(endpoints[0]), list(endpoints[1])],
            "length_km": round(length_km, 6),
            "source": "gpx",
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_gpx_loader.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add gpx_loader.py tests/test_gpx_loader.py
git commit -m "feat: gpx_loader.load_portages with endpoint pairing + length parsing"
```

---

## Task 4: `osm_data.py` integration — campsites + `_merge_portages` (TDD)

Wire GPX into `load_killarney_features()`. Campsites replace existing. Portages merge with OSM via spatial dedup (200m midpoint distance).

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/osm_data.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_osm_data.py`

- [ ] **Step 1: Write 2 failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_osm_data.py`:

```python
def test_load_features_uses_gpx_campsites_when_present(tmp_path, monkeypatch):
    """If killarneyCampsites.gpx exists, out['campsites'] comes from it."""
    osm_cache = {"lakes": [], "portages": []}
    osm_path = tmp_path / "osm_killarney_cache.json"
    osm_path.write_text(json.dumps(osm_cache))

    campsites_gpx = tmp_path / "killarneyCampsites.gpx"
    campsites_gpx.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        '<wpt lat="46.0" lon="-81.0"><name>1</name>'
        '<desc>Killarney 1</desc></wpt>'
        '</gpx>'
    )

    monkeypatch.setattr(_osm_data, "CACHE_PATH", osm_path)
    monkeypatch.setattr(_osm_data, "JEFFS_CACHE_PATH",
                        tmp_path / "absent_jeffs.json")
    monkeypatch.setattr(_osm_data, "PATHS_CACHE_PATH",
                        tmp_path / "absent_paths.json")
    monkeypatch.setattr(_osm_data, "CAMPSITES_GPX_PATH", campsites_gpx)
    monkeypatch.setattr(_osm_data, "PORTAGES_GPX_PATH",
                        tmp_path / "absent_portages.gpx")

    out = _osm_data.load_killarney_features()
    assert len(out["campsites"]) == 1
    assert out["campsites"][0]["name"] == "1"


def test_merge_portages_dedups_near_osm_keeps_distant_osm():
    """GPX is canonical; OSM portages with midpoint within 200m of a GPX
    midpoint are dropped. Distant OSM portages are kept."""
    osm_portages = [
        # NEAR a GPX portage (will be deduped).
        {"name": "OSM near", "endpoints": [[46.0353, -81.3815], [46.0354, -81.3805]],
         "line": [[46.0353, -81.3815], [46.0354, -81.3805]], "length_km": 0.08,
         "source": "osm"},
        # FAR (in another park area).
        {"name": "OSM far", "endpoints": [[46.5, -81.0], [46.51, -81.0]],
         "line": [[46.5, -81.0], [46.51, -81.0]], "length_km": 1.1,
         "source": "osm"},
    ]
    gpx_portages = [
        {"name": "42056", "endpoints": [[46.03524, -81.38126], [46.03535, -81.38053]],
         "line": [[46.03524, -81.38126], [46.03535, -81.38053]], "length_km": 0.058,
         "source": "gpx"},
    ]
    merged = _osm_data._merge_portages(osm_portages, gpx_portages,
                                       spatial_dedup_m=200)
    names = {p["name"] for p in merged}
    # The near-OSM portage is dropped; far-OSM and GPX are kept.
    assert "OSM near" not in names
    assert "OSM far" in names
    assert "42056" in names
    assert len(merged) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_osm_data.py -v -k "campsites or merge_portages"
```

Expected: 2 failures — `AttributeError: module 'osm_data' has no attribute 'CAMPSITES_GPX_PATH'` and `_merge_portages` not defined.

- [ ] **Step 3: Add gpx_loader import + _merge_portages + integration in osm_data.py**

In `/Users/alex/Documents/camping-planner/osm_data.py`, add the import near the top (with other imports):

```python
import gpx_loader
```

Add `_merge_portages` function above `load_killarney_features()`:

```python
def _merge_portages(osm_portages: list, gpx_portages: list,
                    spatial_dedup_m: int = 200) -> list:
    """Merge OSM and GPX portages. GPX is canonical for Killarney; OSM
    portages whose midpoint is within spatial_dedup_m of any GPX portage
    midpoint are dropped as duplicates. OSM portages outside that radius
    (other parks, gaps) are kept.

    Returns the union, with GPX portages first.
    """
    def midpoint(portage):
        ep = portage.get("endpoints") or portage.get("line") or []
        if len(ep) < 2:
            return None
        return [(ep[0][0] + ep[-1][0]) / 2.0, (ep[0][1] + ep[-1][1]) / 2.0]

    gpx_mids = [midpoint(p) for p in gpx_portages]
    gpx_mids = [m for m in gpx_mids if m is not None]
    dedup_km = spatial_dedup_m / 1000.0

    kept_osm = []
    for o in osm_portages:
        om = midpoint(o)
        if om is None:
            kept_osm.append(o)
            continue
        too_close = False
        for gm in gpx_mids:
            # Cheap great-circle approximation: 1 deg lat ≈ 111 km;
            # lon scales by cos(lat). Adequate for 200m gate at our
            # latitudes (~46° N).
            dlat = (om[0] - gm[0]) * 111.0
            dlon = (om[1] - gm[1]) * 111.0 * math.cos(math.radians(om[0]))
            if (dlat * dlat + dlon * dlon) ** 0.5 <= dedup_km:
                too_close = True
                break
        if not too_close:
            kept_osm.append(o)
    return list(gpx_portages) + kept_osm
```

Update `load_killarney_features()` — find the existing function body and add GPX handling after the OSM+Jeff load and before the existing `out["paths"]` block:

```python
    # GPX campsites — canonical, replaces any existing.
    if CAMPSITES_GPX_PATH.exists():
        out["campsites"] = gpx_loader.load_campsites(CAMPSITES_GPX_PATH)

    # GPX portages — merged with OSM via spatial dedup.
    if PORTAGES_GPX_PATH.exists():
        gpx_portages = gpx_loader.load_portages(PORTAGES_GPX_PATH)
        out["portages"] = _merge_portages(out["portages"], gpx_portages,
                                          spatial_dedup_m=200)
```

(Place these lines after the `out["campsites"] = jeffs.get("campsites", [])` block in the JEFFS_CACHE_PATH-existence section, but at the same indentation level — i.e., always run, regardless of Jeff's cache existence.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_osm_data.py -v
```

Expected: all tests in test_osm_data.py pass, including the 2 new ones.

- [ ] **Step 5: Sanity-check end-to-end against real data**

```bash
cd /Users/alex/Documents/camping-planner
python3 -c "
from osm_data import load_killarney_features
osm = load_killarney_features()
print(f'lakes: {len(osm[\"lakes\"])}')
print(f'portages: {len(osm[\"portages\"])}')
print(f'campsites: {len(osm[\"campsites\"])}')
print(f'gpx-source portages: {sum(1 for p in osm[\"portages\"] if p.get(\"source\") == \"gpx\")}')
"
```

Expected output (counts depend on real GPX content but should be approximately):
```
lakes: ~81
portages: ~110  (was 11 before; now mostly GPX)
campsites: 214
gpx-source portages: 110
```

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add osm_data.py tests/test_osm_data.py
git commit -m "feat: merge GPX campsites + portages into load_killarney_features"
```

---

## Task 5: `find_campsite` helper + route_engine wiring (TDD)

Add a name-based campsite lookup helper and update `_night_point()` to use it. GPX campsites use `name`/`lat`/`lon` shape (different from prior Jeff's `ref`/`gps`/`lake` shape).

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/osm_data.py`
- Modify: `/Users/alex/Documents/camping-planner/route_engine.py:323-341`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_route_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `/Users/alex/Documents/camping-planner/tests/test_route_engine.py`:

```python
def test_build_route_resolves_site_gps_from_gpx_campsites():
    """When osm['campsites'] is GPX-shaped (name + lat + lon), the route
    engine looks up the night's site number and uses that GPS instead of
    falling back to the lake centroid."""
    osm = {
        "lakes": [
            {"name": "Killarney Lake",
             "polygon": [[46.05, -81.36], [46.05, -81.38],
                         [46.07, -81.38], [46.07, -81.36],
                         [46.05, -81.36]],
             "centroid": [46.06, -81.37]},
        ],
        "portages": [],
        "campsites": [
            {"name": "61", "lat": 46.05199, "lon": -81.36224,
             "desc": "Killarney 61"},
        ],
    }
    nights = [
        {"date": "2026-06-01", "site": "61", "location": "Killarney Lake"},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)
    site_markers = [m for m in out.get("markers", []) if m["kind"] == "site"]
    assert len(site_markers) == 1
    # Marker GPS comes from GPX campsite, not the lake centroid (46.06, -81.37).
    assert abs(site_markers[0]["lat"] - 46.05199) < 1e-5
    assert abs(site_markers[0]["lon"] - -81.36224) < 1e-5


def test_build_route_falls_back_to_centroid_when_site_not_in_campsites():
    """If the night's site number isn't found in osm['campsites'], the route
    engine falls back to the lake centroid (existing behavior preserved)."""
    osm = {
        "lakes": [
            {"name": "Killarney Lake",
             "polygon": [[46.05, -81.36], [46.05, -81.38],
                         [46.07, -81.38], [46.07, -81.36],
                         [46.05, -81.36]],
             "centroid": [46.06, -81.37]},
        ],
        "portages": [],
        "campsites": [
            {"name": "99", "lat": 46.0, "lon": -81.0, "desc": "Wrong site"},
        ],
    }
    nights = [
        {"date": "2026-06-01", "site": "61", "location": "Killarney Lake"},
    ]
    out = build_route(nights=nights, access_point="George Lake", osm=osm)
    site_markers = [m for m in out.get("markers", []) if m["kind"] == "site"]
    assert len(site_markers) == 1
    # Falls back to the centroid.
    assert site_markers[0]["lat"] == 46.06
    assert site_markers[0]["lon"] == -81.37
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py::test_build_route_resolves_site_gps_from_gpx_campsites -v
python3 -m pytest tests/test_route_engine.py::test_build_route_falls_back_to_centroid_when_site_not_in_campsites -v
```

Expected: both fail. The first because the existing code only checks `cs.get("ref")` and `cs.get("lake")`; GPX shape uses `name`/`lat`/`lon`. The second may pass already if centroid fallback exists; verify either way.

- [ ] **Step 3: Add `find_campsite()` helper to osm_data.py**

Append to `/Users/alex/Documents/camping-planner/osm_data.py` (near `_merge_portages`):

```python
def find_campsite(name: str, campsites: list):
    """Resolve a trip night's `site: <number>` → campsite dict.

    Case-insensitive string match on the `name` field. Returns None if no
    match. Caller should fall back to existing lake-centroid behavior on None.
    """
    if not name:
        return None
    needle = str(name).lower()
    for cs in campsites or []:
        if str(cs.get("name", "")).lower() == needle:
            return cs
    return None
```

- [ ] **Step 4: Update `_night_point()` in route_engine.py**

In `/Users/alex/Documents/camping-planner/route_engine.py`, find `_night_point` (around line 323). Replace the existing campsite-lookup loop:

```python
        site_ref = str(night.get("site", ""))
        location = night.get("location", "")
        for cs in osm.get("campsites", []) or []:
            if cs.get("ref") == site_ref and cs.get("lake") == location:
                return [cs["gps"][0], cs["gps"][1]]
        lake = _find_lake(location, lakes)
        return lake["centroid"] if lake else None
```

With:

```python
        site_ref = str(night.get("site", ""))
        location = night.get("location", "")
        # Try GPX-shape campsite (name/lat/lon) first.
        from osm_data import find_campsite
        cs = find_campsite(site_ref, osm.get("campsites", []))
        if cs is not None:
            return [cs["lat"], cs["lon"]]
        # Legacy Jeff's-shape fallback (ref/gps/lake) — kept for any old
        # caches that still use the original shape.
        for cs in osm.get("campsites", []) or []:
            if cs.get("ref") == site_ref and cs.get("lake") == location:
                return [cs["gps"][0], cs["gps"][1]]
        lake = _find_lake(location, lakes)
        return lake["centroid"] if lake else None
```

Also update the parallel block around `route_engine.py:543` (mentioned at "Use the same resolution priority as _night_point above") — apply the identical GPX-first lookup there for consistency.

```bash
grep -n "site_ref = str(night.get" route_engine.py
```

If 2 matches are found, both need the same update. Inspect both and apply the GPX-first lookup at each site.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v 2>&1 | tail -20
```

Expected: all route_engine tests pass, including the 2 new ones.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add osm_data.py route_engine.py tests/test_route_engine.py
git commit -m "feat: route engine resolves campsites via gpx_loader find_campsite"
```

---

## Task 6: `jeffs_paths_extractor.py` — OCR text-removal pre-pass (TDD)

Add `_remove_text()` with lazy `pytesseract` import. Whitens detected text bboxes before HSV color masking so yellow letterforms (distance labels) don't become noise polylines.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_paths_extractor.py`

- [ ] **Step 1: Write 2 failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_jeffs_paths_extractor.py`:

```python
def test_remove_text_whitens_detected_bboxes():
    """A synthetic image with rendered text → _remove_text whitens the
    pixels inside the OCR-detected bbox."""
    from jeffs_paths_extractor import _remove_text
    # Build a small white canvas with one black-text word in the middle.
    img = np.full((80, 240, 3), 255, dtype=np.uint8)
    cv2.putText(img, "HELLO", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                (0, 0, 0), 3, cv2.LINE_AA)
    # Center pixel before: black-ish (text stroke present).
    before = img[50, 100].copy()
    assert before[0] < 200  # dark
    out = _remove_text(img)
    # After: that pixel should be white (text bbox whitened).
    after = out[50, 100]
    assert after[0] >= 250 and after[1] >= 250 and after[2] >= 250


def test_remove_text_graceful_when_pytesseract_missing(monkeypatch):
    """When pytesseract import raises, _remove_text returns bgr unchanged."""
    import builtins
    from jeffs_paths_extractor import _remove_text
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pytesseract":
            raise ImportError("simulated absence")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    img = np.full((20, 40, 3), 100, dtype=np.uint8)
    out = _remove_text(img)
    assert np.array_equal(out, img)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_paths_extractor.py -v -k "remove_text"
```

Expected: 2 failures — `ImportError: cannot import name '_remove_text'`.

- [ ] **Step 3: Implement `_remove_text` and call it from `_extract_paths_from_mosaic`**

In `/Users/alex/Documents/camping-planner/jeffs_paths_extractor.py`, add `_remove_text` (place it just before `_extract_paths_from_mosaic`):

```python
def _remove_text(bgr: np.ndarray, conf_min: int = 25,
                 pad_px: int = 3) -> np.ndarray:
    """White-fill OCR-detected text bboxes before color masking.

    Lazy-imports pytesseract; returns bgr unchanged if either pytesseract or
    the underlying tesseract binary is unavailable. Distance markers like
    "0.6km" / "23m" that share Jeff's yellow path color would otherwise
    become spurious polylines.
    """
    try:
        import pytesseract
    except ImportError:
        return bgr
    try:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        data = pytesseract.image_to_data(
            gray, config="--psm 11",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        # tesseract binary missing or some other Tesseract error.
        return bgr
    out = bgr.copy()
    n = len(data["text"])
    for i in range(n):
        try:
            conf = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            conf = -1
        if conf < conf_min:
            continue
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        x = max(0, data["left"][i] - pad_px)
        y = max(0, data["top"][i] - pad_px)
        w = data["width"][i] + 2 * pad_px
        h = data["height"][i] + 2 * pad_px
        out[y:y + h, x:x + w] = (255, 255, 255)
    return out
```

In the same file, find `_extract_paths_from_mosaic` and add a parameter + a call to `_remove_text` at the top of its body:

```python
def _extract_paths_from_mosaic(mosaic_bgr: np.ndarray, palette: dict,
                               skip_text_removal: bool = False) -> list:
    """Run the full HSV → morphology → skeletonize → trace → simplify pipeline.
    Returns list of (col, row) pixel polylines.
    """
    if not skip_text_removal:
        mosaic_bgr = _remove_text(mosaic_bgr)
    # ... existing body unchanged ...
```

Add a CLI flag in `main()` (find the existing argparse block):

```python
    parser.add_argument("--skip-text-removal", action="store_true",
                        help="Skip the OCR text-removal pre-pass (debug / "
                             "use when tesseract is unavailable).")
```

And pass it through where `_extract_paths_from_mosaic` is called:

```python
        polylines_px = _extract_paths_from_mosaic(
            mosaic, palette, skip_text_removal=args.skip_text_removal)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_paths_extractor.py -v
```

Expected: all tests in `test_jeffs_paths_extractor.py` pass (the 2 new ones plus the existing end-to-end test).

- [ ] **Step 5: Update requirements.txt to note pytesseract as optional**

Append to `/Users/alex/Documents/camping-planner/requirements.txt`:

```
# OPTIONAL: enables OCR text-removal pre-pass in jeffs_paths_extractor.py
# (cleaner yellow-path masks). Falls back gracefully if missing.
# Requires the tesseract binary: `brew install tesseract` on macOS.
pytesseract>=0.3
```

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_paths_extractor.py tests/test_jeffs_paths_extractor.py requirements.txt
git commit -m "feat: OCR text-removal pre-pass in yellow path extractor"
```

---

## Task 7: Re-extract yellow paths + final integration

Run the refreshed extractor against the real KMZ and compare polyline counts. Rebuild the trip page. Audit verifies the new portage count.

**Files:**
- Regenerate: `/Users/alex/Documents/camping-planner/data/jeffs_canoe_paths.json`
- Regenerate: `/Users/alex/Documents/camping-planner/trips/killarney-2026-05/trip.html`

- [ ] **Step 1: Verify tesseract is installed (for full effect)**

```bash
which tesseract && tesseract --version | head -1
```

Expected: path printed (e.g., `/opt/homebrew/bin/tesseract`) and version like `tesseract 5.x`. If missing, install with `brew install tesseract` — the extractor will still run without it, but with the noisier output.

- [ ] **Step 2: Re-extract yellow paths against the real KMZ**

```bash
cd /Users/alex/Documents/camping-planner
python3 jeffs_paths_extractor.py \
  "Maps by Jeff - Full French River and Killarney Paddling Map v4.0 - Google Earth.kmz" \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --paths-palette paths_palette.yaml \
  --out data/jeffs_canoe_paths.json \
  --review-html /tmp/jeffs_paths_review.html \
  --zoom 7 2>&1 | tail -5
```

Expected: prints `Wrote data/jeffs_canoe_paths.json with N polylines`. Note the count.

- [ ] **Step 3: Inspect the result vs. the previous 72**

```bash
python3 -c "
import json
data = json.load(open('data/jeffs_canoe_paths.json'))
print(f'polylines: {len(data[\"paths\"])}')
lengths = sorted((p['length_km'] for p in data['paths']), reverse=True)
print(f'top 10 lengths (km): {[round(l,2) for l in lengths[:10]]}')
print(f'<0.5km: {sum(1 for l in lengths if l<0.5)}, '
      f'>=1km: {sum(1 for l in lengths if l>=1)}')
"
```

Expected: roughly 50-80 polylines (was 72; text-removal should cut some noise polylines). Top lengths should be similar to before (the long actual paddle routes survived).

- [ ] **Step 4: Rebuild the trip page**

```bash
cd /Users/alex/Documents/camping-planner
time python3 build_trip.py trips/killarney-2026-05/ 2>&1 | tail -3
```

Expected: `Wrote trips/killarney-2026-05/trip.html` and build time roughly comparable to previous (~2-3s).

- [ ] **Step 5: Verify portage and campsite counts in the rebuilt route**

```bash
python3 -c "
from osm_data import load_killarney_features
osm = load_killarney_features()
print(f'lakes:     {len(osm[\"lakes\"])}')
print(f'portages:  {len(osm[\"portages\"])}')
print(f'  from gpx: {sum(1 for p in osm[\"portages\"] if p.get(\"source\") == \"gpx\")}')
print(f'campsites: {len(osm[\"campsites\"])}')
print(f'  by name?: {\"name\" in (osm[\"campsites\"][0] if osm[\"campsites\"] else {})}')
print(f'paths:     {len(osm[\"paths\"])}')
"
```

Expected:
```
lakes:     ~81
portages:  ~110
  from gpx: 110
campsites: 214
  by name?: True
paths:     ~50-80
```

- [ ] **Step 6: Run the route-water audit (regression check)**

```bash
python3 scripts/audit_route_water.py --source both 2>&1 | tail -20
```

Expected: percentages comparable to or better than the previous run. Major paddle legs should still be high in-water %. Audit failures specifically introduced by this work would be NEW out-of-water samples — flag those for investigation, otherwise this is a strict improvement.

- [ ] **Step 7: Run the full test suite**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ --ignore=tests/test_routes.py -q 2>&1 | tail -3
```

Expected: all tests pass (around 116 after this work — was 105, +9 from `tests/test_gpx_loader.py` (5) + `tests/test_osm_data.py` (2) + `tests/test_route_engine.py` (2). Plus `tests/test_jeffs_paths_extractor.py` (2 new) brings to 11 new = 116.).

- [ ] **Step 8: Commit the regenerated data**

```bash
cd /Users/alex/Documents/camping-planner
git add data/jeffs_canoe_paths.json trips/killarney-2026-05/trip.html
git commit -m "data: re-extract yellow paths with text-removal + rebuild trip page"
```

---

## Task 8: Documentation update

Update CLAUDE.md to reflect new file layout + GPX integration.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/CLAUDE.md`

- [ ] **Step 1: Update the "Project files" section in CLAUDE.md**

In `/Users/alex/Documents/camping-planner/CLAUDE.md`, find the "Project files" subsection (under "Trip Planning Workflow" → "Project files"). Find the lines that mention these files:

```
- `parks.json` — park configs with resourceLocationId, mapId, drive times from Ajax
- `park_activities.json` — curated hikes/swimming/paddling/tips per park
- `api_attribute_filterable.json` — cached attribute definitions (55 attributes)
- `map_names_cache.json` — cached campground map names
- `osm_data.py`, `osm_killarney_cache.json` — OSM lakes/portages cache used by `route_engine.py`
- `route_engine.py` — auto-routes paddling segments + estimates from OSM data
```

Replace the OSM line with the new layout. Add new lines for the GPX loader and data directory:

```
- `parks.json` — park configs with resourceLocationId, mapId, drive times from Ajax
- `park_activities.json` — curated hikes/swimming/paddling/tips per park
- `api_attribute_filterable.json` — cached attribute definitions (55 attributes)
- `map_names_cache.json` — cached campground map names
- `osm_data.py` — loads + merges all Killarney datasets (OSM lakes/portages,
  Jeff's lake polygons, yellow paths, GPX campsites + portages)
- `gpx_loader.py` — GPX → list-of-dicts parsing for campsites and portages
- `data/` — cached + source data files (gitted):
  - `osm_killarney_cache.json` — OSM lakes (51 named) + portages (sparse)
  - `jeffs_killarney_cache.json` — Jeff's lake polygons (33 named + 30 unnamed)
  - `jeffs_canoe_paths.json` — yellow paddle paths extracted from Jeff's KMZ
  - `killarneyCampsites.gpx` — 214 numbered campsite waypoints (PaddlePlanner)
  - `killarneyPortages.gpx` — 110 portages × 2 endpoints (PaddlePlanner)
- `route_engine.py` — auto-routes paddling segments + estimates from merged data
```

- [ ] **Step 2: Add a "Data sources" note near the top of the file**

In `/Users/alex/Documents/camping-planner/CLAUDE.md`, find a logical spot near the start of the "Trip Planning Workflow" section. Add this note:

```markdown
## Data sources

| Feature | Source | Notes |
|---|---|---|
| Lake polygons | OSM Overpass + Jeff's KMZ | OSM is named-canonical; Jeff's are tighter shapes |
| Portages (110) | `data/killarneyPortages.gpx` | PaddlePlanner.com; merged with sparse OSM |
| Campsites (214) | `data/killarneyCampsites.gpx` | PaddlePlanner.com; name = site number |
| Yellow paddle paths | Jeff's KMZ raster extraction | `jeffs_paths_extractor.py` |
| Weather | Open-Meteo API | `weather.py` |
| Route maps | KML/GPX in trip dir | `route_map.py` |

`osm_data.load_killarney_features()` consolidates all of the above into one dict consumed by `route_engine` and the FastAPI layer.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for GPX loader + data/ directory layout"
```

---

## Verification checklist (after Task 8)

- [ ] `python3 -m pytest tests/ --ignore=tests/test_routes.py -q` shows all tests passing
- [ ] `gpx_loader.py` exists and is ~120 lines
- [ ] `data/` directory contains the 5 expected files
- [ ] `osm_data.load_killarney_features()['portages']` length ≈ 110 (most with `source: 'gpx'`)
- [ ] `osm_data.load_killarney_features()['campsites']` length ≈ 214 (all with `name`, `lat`, `lon`)
- [ ] `time python3 build_trip.py trips/killarney-2026-05/` < 5 seconds
- [ ] Trip page renders with campsite GPS resolved from GPX (not lake centroids)
- [ ] Audit total in-water % is ≥ previous baseline (no regression)
- [ ] CLAUDE.md "Project files" section reflects new paths

If all 8 pass, the implementation is complete.
