# Jeff's Maps Vectorizer (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract lake polygons and numbered campsite locations from Jeff's Killarney KMZ (Google Earth super-overlay) into a committed JSON cache that augments `osm_killarney_cache.json`, fixing the Baie Fine gap and eliminating per-night `gps:` overrides.

**Architecture:** A new `jeffs_extractor.py` walks the KMZ tile pyramid, filters tiles by bbox, runs color-segmentation lake extraction at zoom level 6 (mosaicked), and per-tile campsite icon detection + OCR at zoom level 7. Output JSON augments `osm_data.load_killarney_features()`; `route_engine._night_point()` auto-resolves site GPS from the extracted campsites.

**Tech Stack:** Python 3, OpenCV (`cv2`), Pillow (`PIL`), Tesseract via `pytesseract`, pyyaml, stdlib `zipfile`/`xml.etree.ElementTree`. No new services — all local processing.

**Spec:** `docs/superpowers/specs/2026-05-09-jeffs-maps-vectorizer-design.md`

---

## File Structure

**New files (in repo root):**
- `jeffs_extractor.py` — main module + CLI (~450 lines)
- `jeffs_killarney_overrides.yaml` — manual lake/campsite name overrides
- `lakes_palette.yaml` — HSV thresholds for lake water color
- `campsites_palette.yaml` — HSV thresholds for campsite icon color
- `jeffs_killarney_cache.json` — extracted output (created in Task 11)

**New tests:**
- `tests/test_jeffs_extractor.py` — unit tests for the algorithmic core
- `tests/fixtures/synthetic_kmz.py` — helper that programmatically builds tiny KMZs for testing

**Modified files:**
- `requirements.txt` — add `opencv-python`, `pytesseract`, `pillow`
- `.gitignore` — add `*.kmz`, `templates/jeffs_*`
- `README.md` — Tesseract install note + extractor usage paragraph
- `osm_data.py` — merge Jeff's cache into `load_killarney_features()`
- `route_engine.py` — `_night_point` auto-resolves site GPS from `osm["campsites"]`

**Out of scope:** portage line extraction, place name OCR, parks beyond Killarney/French River, generalizing the extractor to non-Jeff KMZs (it expects the specific Garmin/Google Earth super-overlay shape).

---

## Task 1: Add dependencies, gitignore, README note

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/requirements.txt`
- Modify: `/Users/alex/Documents/camping-planner/.gitignore`
- Modify: `/Users/alex/Documents/camping-planner/README.md`

- [ ] **Step 1: Append new Python dependencies**

Edit `/Users/alex/Documents/camping-planner/requirements.txt`. The current contents are:

```
requests>=2.31.0
playwright>=1.40.0
markdown==3.7
pyyaml==6.0.2
pytest>=8.0.0
```

Append:

```
opencv-python>=4.8
pytesseract>=0.3.10
pillow>=10.0
```

- [ ] **Step 2: Install the new dependencies**

```bash
cd /Users/alex/Documents/camping-planner
pip install -r requirements.txt
```

Expected: pip installs `opencv-python`, `pytesseract`, `pillow` (others already present). Print `Successfully installed ...` lines.

- [ ] **Step 3: Verify imports work**

```bash
python3 -c "import cv2, pytesseract, PIL; print(cv2.__version__, pytesseract.__version__, PIL.__version__)"
```

Expected: prints three version strings, no ImportError. If `pytesseract` raises `TesseractNotFoundError` later (it's a Python wrapper, the binary install is separate), Step 4 covers it.

- [ ] **Step 4: Append KMZ ignore rules to `.gitignore`**

Edit `/Users/alex/Documents/camping-planner/.gitignore`. Append (existing rules unchanged):

```
*.kmz
templates/jeffs_*.png
```

(The `*.kmz` rule prevents accidental commit of paid Jeff's Map files. The `templates/jeffs_*.png` rule covers the optional icon template used for Stage C1 fallback.)

- [ ] **Step 5: Append Tesseract install note + extractor overview to README**

Edit `/Users/alex/Documents/camping-planner/README.md`. Append a new section at the bottom:

```markdown
## Jeff's Maps vectorizer (optional)

If you have a Jeff's Maps KMZ for Killarney/French River (paid product),
you can extract its lake polygons and campsite locations into a cache
that augments the OSM data.

System dependency — Tesseract OCR binary:

- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr`

Run the extractor (one-shot, only when the map version changes):

```bash
python3 jeffs_extractor.py path/to/jeffs.kmz \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --out jeffs_killarney_cache.json
```

The KMZ itself is gitignored; only the extracted JSON is committed.
```

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add requirements.txt .gitignore README.md
git commit -m "chore: add OpenCV, pytesseract, pillow + KMZ ignore rules"
```

---

## Task 2: KMZ traversal (Stage A') with TDD

Walk the KMZ tile pyramid, parse each tile's `LatLonBox`, filter by target bbox.

**Files:**
- Create: `/Users/alex/Documents/camping-planner/jeffs_extractor.py`
- Create: `/Users/alex/Documents/camping-planner/tests/fixtures/synthetic_kmz.py`
- Create: `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`

- [ ] **Step 1: Create the synthetic KMZ test helper**

Create `/Users/alex/Documents/camping-planner/tests/fixtures/synthetic_kmz.py`:

```python
"""Build tiny KMZ archives at test time for jeffs_extractor unit tests.

Mirrors Jeff's Google Earth super-overlay structure:
- doc.kml at root (NetworkLink to first level — we don't actually need
  this for walk_kmz tests since walk_kmz scans the level directory directly)
- per-tile KML files under <level>/<x>/<y>.kml
- per-tile image files alongside their KML
"""
import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw


def _make_solid_image(width: int, height: int, color: tuple) -> bytes:
    """Return PNG bytes of a solid-color image."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _kml_for_tile(image_filename: str, bounds: tuple) -> str:
    """Build a per-tile KML referencing image_filename with given (n, s, e, w) bounds."""
    n, s, e, w = bounds
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <GroundOverlay>
      <Icon><href>{image_filename}</href></Icon>
      <LatLonBox>
        <north>{n}</north>
        <south>{s}</south>
        <east>{e}</east>
        <west>{w}</west>
        <rotation>0</rotation>
      </LatLonBox>
    </GroundOverlay>
  </Document>
</kml>
"""


def write_synthetic_kmz(out_path: Path, tiles: list, level: int = 6) -> Path:
    """Write a KMZ with the given tiles to out_path.

    Each tile in `tiles` is a dict:
      {"filename": "tile_a.png", "bounds": (n, s, e, w),
       "image": optional bytes (defaults to a 100x100 solid white PNG)}

    KMZ layout:
      doc.kml                    — root (minimal, doesn't matter for tests)
      <level>/0/<index>.kml      — per-tile KML referencing the image
      <level>/0/<filename>       — image file
    """
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", _root_kml())
        for i, tile in enumerate(tiles):
            kml_path = f"{level}/0/{i}.kml"
            img_path = f"{level}/0/{tile['filename']}"
            z.writestr(kml_path, _kml_for_tile(tile["filename"], tile["bounds"]))
            img_bytes = tile.get("image") or _make_solid_image(100, 100, (255, 255, 255))
            z.writestr(img_path, img_bytes)
    return out_path


def _root_kml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document><name>synthetic test kmz</name></Document>
</kml>
"""
```

- [ ] **Step 2: Write the failing tests**

Create `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`:

```python
"""Tests for jeffs_extractor.py."""
from pathlib import Path

import pytest

from tests.fixtures.synthetic_kmz import write_synthetic_kmz
from jeffs_extractor import walk_kmz, tile_pixel_to_gps


def test_walk_kmz_yields_tiles_in_bbox(tmp_path):
    kmz = tmp_path / "synthetic.kmz"
    # Four tiles: two inside target bbox, two outside.
    write_synthetic_kmz(kmz, level=6, tiles=[
        # Inside bbox (45.0..46.0, -82.0..-81.0):
        {"filename": "a.png", "bounds": (45.5, 45.4, -81.5, -81.6)},
        {"filename": "b.png", "bounds": (45.7, 45.6, -81.3, -81.4)},
        # Outside bbox:
        {"filename": "c.png", "bounds": (50.0, 49.9, -81.5, -81.6)},  # north of bbox
        {"filename": "d.png", "bounds": (45.5, 45.4, -70.0, -70.1)},  # east of bbox
    ])

    bbox = (45.0, -82.0, 46.0, -81.0)  # (south, west, north, east)
    tiles = list(walk_kmz(kmz, bbox=bbox, zoom_level=6))
    names = sorted(t.image_path.name for t in tiles)
    assert names == ["a.png", "b.png"]


def test_tile_pixel_to_gps_linear_interpolation():
    # Tile covering 1 deg x 1 deg, image 100x100. Pixel (50, 50) is center.
    class FakeTile:
        north = 46.0
        south = 45.0
        east = -81.0
        west = -82.0

    lat, lon = tile_pixel_to_gps(FakeTile, 50, 50, img_w=100, img_h=100)
    assert abs(lat - 45.5) < 0.001
    assert abs(lon - -81.5) < 0.001

    # Top-left pixel (0, 0) should be (north, west) = (46.0, -82.0).
    lat, lon = tile_pixel_to_gps(FakeTile, 0, 0, img_w=100, img_h=100)
    assert abs(lat - 46.0) < 0.001
    assert abs(lon - -82.0) < 0.001

    # Bottom-right pixel (100, 100) should be (south, east) = (45.0, -81.0).
    lat, lon = tile_pixel_to_gps(FakeTile, 100, 100, img_w=100, img_h=100)
    assert abs(lat - 45.0) < 0.001
    assert abs(lon - -81.0) < 0.001


def test_walk_kmz_rejects_rotated_tiles(tmp_path):
    """Non-zero rotation requires homography; we hard-fail rather than silently skew."""
    kmz = tmp_path / "synthetic.kmz"
    write_synthetic_kmz(kmz, level=6, tiles=[
        {"filename": "a.png", "bounds": (45.5, 45.4, -81.5, -81.6)},
    ])
    # Patch the KML to set rotation=15 instead of 0.
    import zipfile
    with zipfile.ZipFile(kmz, "r") as z:
        contents = {n: z.read(n) for n in z.namelist()}
    for name in list(contents):
        if name.endswith(".kml") and name != "doc.kml":
            contents[name] = contents[name].replace(b"<rotation>0</rotation>",
                                                    b"<rotation>15</rotation>")
    with zipfile.ZipFile(kmz, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in contents.items():
            z.writestr(n, b)

    bbox = (45.0, -82.0, 46.0, -81.0)
    with pytest.raises(ValueError, match="rotation"):
        list(walk_kmz(kmz, bbox=bbox, zoom_level=6))
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: 3 tests fail with `ModuleNotFoundError: No module named 'jeffs_extractor'`.

- [ ] **Step 4: Implement walk_kmz + tile_pixel_to_gps**

Create `/Users/alex/Documents/camping-planner/jeffs_extractor.py`:

```python
"""
Extract lake polygons and numbered campsites from Jeff's Maps KMZ.

Augments osm_killarney_cache.json with vector data derived from the
purchased Jeff's Killarney Paddling Map (Google Earth super-overlay
format). One-shot extraction; output JSON is committed.

Usage:
  python3 jeffs_extractor.py path/to/jeffs.kmz \\
    --bbox 45.92,-81.60,46.12,-81.25 \\
    --out jeffs_killarney_cache.json
"""
import argparse
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


KML_NS = {"k": "http://www.opengis.net/kml/2.2"}


@dataclass
class Tile:
    """One georeferenced raster tile from the KMZ pyramid."""
    image_path: Path
    north: float
    south: float
    east: float
    west: float


def _bboxes_intersect(a, b) -> bool:
    """Return True if two (south, west, north, east) bboxes overlap."""
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _parse_tile_kml(kml_path: Path) -> Optional[Tile]:
    """Parse a per-tile KML and return a Tile, or None if no GroundOverlay."""
    tree = ET.parse(kml_path)
    root = tree.getroot()
    overlay = root.find(".//k:GroundOverlay", KML_NS)
    if overlay is None:
        return None
    icon = overlay.find("k:Icon/k:href", KML_NS)
    box = overlay.find("k:LatLonBox", KML_NS)
    if icon is None or box is None or icon.text is None:
        return None
    rotation_txt = box.findtext("k:rotation", default="0", namespaces=KML_NS).strip()
    if float(rotation_txt) != 0:
        raise ValueError(
            f"{kml_path}: GroundOverlay has rotation={rotation_txt}; "
            "only axis-aligned tiles are supported."
        )
    north = float(box.findtext("k:north", namespaces=KML_NS))
    south = float(box.findtext("k:south", namespaces=KML_NS))
    east = float(box.findtext("k:east", namespaces=KML_NS))
    west = float(box.findtext("k:west", namespaces=KML_NS))
    image_path = (kml_path.parent / icon.text).resolve()
    return Tile(image_path=image_path,
                north=north, south=south, east=east, west=west)


def walk_kmz(kmz_path: Path, bbox: tuple, zoom_level: int,
             extract_dir: Optional[Path] = None) -> Iterable[Tile]:
    """Walk a Jeff's Maps KMZ at the given zoom level, yield bbox-overlapping Tiles.

    bbox is (south, west, north, east). zoom_level corresponds to the
    numbered subdirectory inside the KMZ (e.g., 6 for level-6 tiles).

    If extract_dir is None, a temp dir is created and CLEANED UP when the
    iterator is exhausted. Pass a persistent dir for inspection.
    """
    kmz_path = Path(kmz_path)
    cleanup = False
    if extract_dir is None:
        extract_dir = Path(tempfile.mkdtemp(prefix="jeffs_kmz_"))
        cleanup = True
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(kmz_path) as z:
            z.extractall(extract_dir)
        level_dir = extract_dir / str(zoom_level)
        if not level_dir.is_dir():
            return
        for kml_path in sorted(level_dir.rglob("*.kml")):
            tile = _parse_tile_kml(kml_path)
            if tile is None:
                continue
            tile_bbox = (tile.south, tile.west, tile.north, tile.east)
            if _bboxes_intersect(tile_bbox, bbox):
                yield tile
    finally:
        if cleanup:
            import shutil
            shutil.rmtree(extract_dir, ignore_errors=True)


def tile_pixel_to_gps(tile: Tile, px: float, py: float,
                      img_w: int, img_h: int) -> tuple:
    """Linear pixel -> (lat, lon) within an axis-aligned tile."""
    lon = tile.west + (px / img_w) * (tile.east - tile.west)
    lat = tile.north - (py / img_h) * (tile.north - tile.south)
    return (lat, lon)
```

- [ ] **Step 5: Make tests/fixtures importable as a package**

```bash
cd /Users/alex/Documents/camping-planner
test -f tests/fixtures/__init__.py || touch tests/fixtures/__init__.py
```

(`tests/__init__.py` already exists.)

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: 3 tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_extractor.py tests/fixtures/__init__.py tests/fixtures/synthetic_kmz.py tests/test_jeffs_extractor.py
git commit -m "feat: KMZ traversal + tile pixel-to-GPS for Jeff's Maps extractor"
```

---

## Task 3: Lake mosaic + extraction (Stage B core, TDD)

Stitch level-6 tiles into a mosaic, run color-segmentation lake extraction.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`
- Create: `/Users/alex/Documents/camping-planner/lakes_palette.yaml`

- [ ] **Step 1: Write the lakes palette YAML**

Create `/Users/alex/Documents/camping-planner/lakes_palette.yaml`:

```yaml
# HSV thresholds for Jeff's lake water color. Tune empirically against
# the actual KMZ on first run; defaults are starting points.
hue:        [85, 110]
saturation: [40, 200]
value:      [180, 255]

# Minimum contour area in pixels (drops label boxes, decorative water symbols)
min_area_px: 500
```

- [ ] **Step 2: Write the failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`:

```python
import io

import numpy as np
from PIL import Image, ImageDraw

from jeffs_extractor import build_mosaic, extract_lakes_from_mosaic


def _solid_blue_tile_bytes(w=200, h=200, blue=(220, 200, 100)):
    """200x200 PNG, mostly white, with a blue circle in the middle (HSV blue range)."""
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Note: PIL uses RGB; OpenCV reads BGR. Choose color so HSV-blue triggers.
    draw.ellipse((40, 40, 160, 160), fill=blue)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_build_mosaic_pastes_tiles_at_correct_positions(tmp_path):
    kmz = tmp_path / "synthetic.kmz"
    write_synthetic_kmz(kmz, level=6, tiles=[
        # 2-tile horizontal strip: (45.0..46.0, -82.0..-81.5) and (45.0..46.0, -81.5..-81.0).
        {"filename": "left.png",
         "bounds": (46.0, 45.0, -81.5, -82.0),
         "image": _solid_blue_tile_bytes(100, 100)},
        {"filename": "right.png",
         "bounds": (46.0, 45.0, -81.0, -81.5),
         "image": _solid_blue_tile_bytes(100, 100)},
    ])

    bbox = (45.0, -82.0, 46.0, -81.0)
    tiles = list(walk_kmz(kmz, bbox=bbox, zoom_level=6,
                          extract_dir=tmp_path / "extracted"))
    mosaic, mosaic_bounds = build_mosaic(tiles)
    # Mosaic should be wider than tall (covers 1 deg lat, 1 deg lon at lat 45):
    assert mosaic.shape[0] > 0 and mosaic.shape[1] > 0
    # Bounds should match the union of tile bounds.
    n, s, e, w = mosaic_bounds
    assert abs(n - 46.0) < 1e-6
    assert abs(s - 45.0) < 1e-6
    assert abs(e - -81.0) < 1e-6
    assert abs(w - -82.0) < 1e-6


def test_extract_lakes_finds_synthetic_blue_blob(tmp_path):
    """One blue circle in a tile should produce one lake polygon."""
    kmz = tmp_path / "synthetic.kmz"
    write_synthetic_kmz(kmz, level=6, tiles=[
        {"filename": "a.png",
         "bounds": (46.0, 45.0, -81.0, -82.0),
         "image": _solid_blue_tile_bytes(200, 200)},
    ])
    bbox = (45.0, -82.0, 46.0, -81.0)
    tiles = list(walk_kmz(kmz, bbox=bbox, zoom_level=6,
                          extract_dir=tmp_path / "extracted"))
    mosaic, mosaic_bounds = build_mosaic(tiles)
    palette = {"hue": [90, 130], "saturation": [80, 255], "value": [80, 255],
               "min_area_px": 100}
    lakes = extract_lakes_from_mosaic(mosaic, mosaic_bounds, palette)
    assert len(lakes) == 1
    lake = lakes[0]
    # Centroid should be near the center of the tile (lat 45.5, lon -81.5).
    cx, cy = lake["centroid"]
    assert 45.4 < cx < 45.6
    assert -81.6 < cy < -81.4
    # Polygon has at least 4 vertices.
    assert len(lake["polygon"]) >= 4
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: the 2 new tests fail with `ImportError: cannot import name 'build_mosaic'` etc. The 3 existing tests still pass.

- [ ] **Step 4: Implement build_mosaic and extract_lakes_from_mosaic**

Append to `/Users/alex/Documents/camping-planner/jeffs_extractor.py`:

```python
import cv2
import numpy as np
from PIL import Image


def build_mosaic(tiles: list) -> tuple:
    """Stitch tiles into one BGR numpy mosaic.

    Returns (mosaic_array, mosaic_bounds) where mosaic_bounds is
    (north, south, east, west) of the union of all tile bounds.

    The mosaic's pixel scale is taken from the first tile (tiles at the
    same zoom level have the same pixels-per-degree, so this is consistent).
    """
    if not tiles:
        raise ValueError("build_mosaic: no tiles provided")

    norths = [t.north for t in tiles]
    souths = [t.south for t in tiles]
    easts = [t.east for t in tiles]
    wests = [t.west for t in tiles]
    bounds = (max(norths), min(souths), max(easts), min(wests))
    n, s, e, w = bounds

    # Determine pixels-per-degree from the first tile.
    sample = tiles[0]
    sample_img = np.array(Image.open(sample.image_path).convert("RGB"))
    sample_h, sample_w = sample_img.shape[:2]
    px_per_deg_lon = sample_w / (sample.east - sample.west)
    px_per_deg_lat = sample_h / (sample.north - sample.south)

    mosaic_w = max(1, round((e - w) * px_per_deg_lon))
    mosaic_h = max(1, round((n - s) * px_per_deg_lat))
    mosaic = np.full((mosaic_h, mosaic_w, 3), 255, dtype=np.uint8)

    for tile in tiles:
        img = np.array(Image.open(tile.image_path).convert("RGB"))
        h, w_px = img.shape[:2]
        # Top-left of tile in mosaic pixel coords:
        x0 = round((tile.west - w) * px_per_deg_lon)
        y0 = round((n - tile.north) * px_per_deg_lat)
        x1 = x0 + w_px
        y1 = y0 + h
        # Clip to mosaic bounds.
        sx0, sy0 = max(0, -x0), max(0, -y0)
        dx0, dy0 = max(0, x0), max(0, y0)
        dx1, dy1 = min(mosaic_w, x1), min(mosaic_h, y1)
        if dx1 <= dx0 or dy1 <= dy0:
            continue
        crop = img[sy0:sy0 + (dy1 - dy0), sx0:sx0 + (dx1 - dx0)]
        # PIL gave us RGB; OpenCV expects BGR. Convert before pasting.
        mosaic[dy0:dy1, dx0:dx1] = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)

    return mosaic, bounds


def _mosaic_pixel_to_gps(mosaic_bounds: tuple, mosaic_shape: tuple,
                         px: float, py: float) -> tuple:
    """Inverse of mosaic pixel placement."""
    n, s, e, w = mosaic_bounds
    h, w_px = mosaic_shape[:2]
    lon = w + (px / w_px) * (e - w)
    lat = n - (py / h) * (n - s)
    return (lat, lon)


def extract_lakes_from_mosaic(mosaic, mosaic_bounds: tuple, palette: dict) -> list:
    """Find lake polygons via HSV color seg + contour finding.

    Returns a list of dicts:
      {"polygon": [[lat, lon], ...], "centroid": [lat, lon]}

    Names are NOT assigned here — that's a separate naming step.
    """
    hsv = cv2.cvtColor(mosaic, cv2.COLOR_BGR2HSV)
    low = np.array([palette["hue"][0], palette["saturation"][0], palette["value"][0]])
    high = np.array([palette["hue"][1], palette["saturation"][1], palette["value"][1]])
    mask = cv2.inRange(hsv, low, high)

    # Clean: close holes, then open to drop specks.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    min_area = palette.get("min_area_px", 500)
    lakes = []
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        # Simplify.
        epsilon = 0.001 * cv2.arcLength(c, closed=True)
        approx = cv2.approxPolyDP(c, epsilon, closed=True)
        # Project to GPS.
        polygon_gps = []
        for pt in approx:
            px, py = float(pt[0][0]), float(pt[0][1])
            lat, lon = _mosaic_pixel_to_gps(mosaic_bounds, mosaic.shape, px, py)
            polygon_gps.append([lat, lon])
        # Centroid: simple average of vertices.
        cx = sum(p[0] for p in polygon_gps) / len(polygon_gps)
        cy = sum(p[1] for p in polygon_gps) / len(polygon_gps)
        lakes.append({
            "polygon": polygon_gps,
            "centroid": [cx, cy],
        })
    return lakes
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: 5 tests pass total.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_extractor.py tests/test_jeffs_extractor.py lakes_palette.yaml
git commit -m "feat: mosaic builder + HSV lake polygon extraction"
```

---

## Task 4: Lake naming with OSM auto-match + overrides (TDD)

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`
- Create: `/Users/alex/Documents/camping-planner/jeffs_killarney_overrides.yaml`

- [ ] **Step 1: Create the overrides YAML stub**

Create `/Users/alex/Documents/camping-planner/jeffs_killarney_overrides.yaml`:

```yaml
# Manual overrides for the Jeff's Maps extractor.
# Add entries for lakes/campsites where automatic detection or naming fails.

lakes:
  # Example: name a polygon Jeff has but OSM doesn't know.
  # - centroid_near: [46.012, -81.540]
  #   name: Baie Fine

campsites:
  # Example: force a ref when OCR fails on a particular icon.
  # - centroid_near: [46.044, -81.503]
  #   ref: '82'
```

- [ ] **Step 2: Write the failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`:

```python
from jeffs_extractor import assign_lake_names


def test_assign_lake_names_uses_osm_within_500m():
    jeffs_lakes = [
        {"polygon": [[1, 1]], "centroid": [46.05, -81.40]},  # near OSM
        {"polygon": [[1, 1]], "centroid": [46.06, -81.30]},  # near OSM
        {"polygon": [[1, 1]], "centroid": [50.00, -70.00]},  # nowhere near anything
    ]
    osm_lakes = [
        {"name": "Killarney Lake", "centroid": [46.05, -81.40]},
        {"name": "Freeland Lake",  "centroid": [46.06, -81.30]},
    ]
    overrides = {"lakes": []}
    named = assign_lake_names(jeffs_lakes, osm_lakes, overrides)
    names = sorted(l.get("name", "?") for l in named)
    # First two get OSM names; third is unnamed.
    assert "Killarney Lake" in names
    assert "Freeland Lake" in names
    assert "?" in names  # third polygon unnamed


def test_assign_lake_names_uses_overrides_for_unmatched():
    jeffs_lakes = [
        {"polygon": [[1, 1]], "centroid": [46.022, -81.510]},  # not in OSM
    ]
    osm_lakes = []
    overrides = {"lakes": [
        {"centroid_near": [46.020, -81.510], "name": "Baie Fine"},
    ]}
    named = assign_lake_names(jeffs_lakes, osm_lakes, overrides)
    assert named[0]["name"] == "Baie Fine"


def test_assign_lake_names_osm_wins_over_override_when_both_match():
    """If OSM has a match within 500m, use it. Overrides are for unmatched only."""
    jeffs_lakes = [
        {"polygon": [[1, 1]], "centroid": [46.05, -81.40]},
    ]
    osm_lakes = [{"name": "Killarney Lake", "centroid": [46.05, -81.40]}]
    overrides = {"lakes": [{"centroid_near": [46.05, -81.40], "name": "Wrong Override"}]}
    named = assign_lake_names(jeffs_lakes, osm_lakes, overrides)
    assert named[0]["name"] == "Killarney Lake"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: 3 new tests fail with `ImportError: cannot import name 'assign_lake_names'`.

- [ ] **Step 4: Implement assign_lake_names**

Append to `/Users/alex/Documents/camping-planner/jeffs_extractor.py`:

```python
import math


def _haversine_km(a, b):
    """Distance in km between (lat, lon) tuples or [lat, lon] lists."""
    R = 6371.0
    p1 = math.radians(a[0])
    p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


_NAME_MATCH_TOLERANCE_KM = 0.5
_OVERRIDE_MATCH_TOLERANCE_KM = 0.5


def assign_lake_names(jeffs_lakes: list, osm_lakes: list, overrides: dict) -> list:
    """Tag each Jeff's polygon with a name using OSM auto-match + overrides.

    Resolution order:
      1. Closest OSM lake centroid within 0.5 km wins.
      2. Override entry whose centroid_near is within 0.5 km wins.
      3. Otherwise, polygon stays unnamed (no `name` key).

    Returns the polygon list with `name` keys added where matched.
    """
    out = []
    override_entries = (overrides or {}).get("lakes", []) or []

    for poly in jeffs_lakes:
        new_poly = dict(poly)
        centroid = poly["centroid"]

        # Try OSM auto-match first.
        best_name = None
        best_dist = _NAME_MATCH_TOLERANCE_KM
        for osm in osm_lakes:
            d = _haversine_km(centroid, osm["centroid"])
            if d < best_dist:
                best_dist = d
                best_name = osm["name"]

        # If no OSM match, try overrides.
        if best_name is None:
            for ov in override_entries:
                near = ov.get("centroid_near")
                if near is None or "name" not in ov:
                    continue
                if _haversine_km(centroid, near) <= _OVERRIDE_MATCH_TOLERANCE_KM:
                    best_name = ov["name"]
                    break

        if best_name is not None:
            new_poly["name"] = best_name
        out.append(new_poly)

    return out
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: 8 tests pass total.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_extractor.py tests/test_jeffs_extractor.py jeffs_killarney_overrides.yaml
git commit -m "feat: lake naming via OSM auto-match + manual overrides"
```

---

## Task 5: Wire Jeff's lakes into `osm_data.load_killarney_features()`

Make the existing route engine consume Jeff's data when present.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/osm_data.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_osm_data.py`

- [ ] **Step 1: Read current osm_data.py to find the load function**

```bash
grep -n "def load_killarney_features\|CACHE_PATH" /Users/alex/Documents/camping-planner/osm_data.py
```

Expected: shows the function and `CACHE_PATH = Path(__file__).parent / "osm_killarney_cache.json"` near the top.

- [ ] **Step 2: Write a failing test for the merge behavior**

Append to `/Users/alex/Documents/camping-planner/tests/test_osm_data.py`:

```python
import json

import osm_data as _osm_data


def test_load_features_merges_jeffs_when_present(tmp_path, monkeypatch):
    """When jeffs_killarney_cache.json exists, its lakes win on name conflict
    and its campsites surface as a top-level key."""
    osm_cache = {
        "lakes": [
            {"name": "Killarney Lake", "polygon": [[1, 1]], "centroid": [46.05, -81.40]},
            {"name": "Other Lake", "polygon": [[2, 2]], "centroid": [46.0, -81.5]},
        ],
        "portages": [{"name": "X", "line": [[0, 0]], "length_km": 1.0,
                      "endpoints": [[0, 0], [1, 1]]}],
    }
    jeffs_cache = {
        "lakes": [
            {"name": "Killarney Lake", "polygon": [[9, 9]], "centroid": [46.05, -81.40]},
            {"name": "Baie Fine", "polygon": [[8, 8]], "centroid": [46.02, -81.51]},
        ],
        "campsites": [
            {"ref": "61", "lake": "OSA Lake", "gps": [46.063, -81.392]},
        ],
    }
    osm_path = tmp_path / "osm_killarney_cache.json"
    jeffs_path = tmp_path / "jeffs_killarney_cache.json"
    osm_path.write_text(json.dumps(osm_cache))
    jeffs_path.write_text(json.dumps(jeffs_cache))

    monkeypatch.setattr(_osm_data, "CACHE_PATH", osm_path)
    monkeypatch.setattr(_osm_data, "JEFFS_CACHE_PATH", jeffs_path)

    out = _osm_data.load_killarney_features()
    names = sorted(l["name"] for l in out["lakes"])
    # Killarney Lake from Jeff's wins; Other Lake (OSM-only) preserved;
    # Baie Fine added.
    assert names == ["Baie Fine", "Killarney Lake", "Other Lake"]
    killarney = next(l for l in out["lakes"] if l["name"] == "Killarney Lake")
    # Verify Jeff's polygon, not OSM's.
    assert killarney["polygon"] == [[9, 9]]
    # Campsites surfaced.
    assert out["campsites"] == jeffs_cache["campsites"]
    # Portages still from OSM.
    assert len(out["portages"]) == 1


def test_load_features_works_without_jeffs(tmp_path, monkeypatch):
    osm_cache = {
        "lakes": [{"name": "X", "polygon": [[1, 1]], "centroid": [0, 0]}],
        "portages": [],
    }
    osm_path = tmp_path / "osm_killarney_cache.json"
    jeffs_path = tmp_path / "jeffs_killarney_cache.json"  # does NOT exist
    osm_path.write_text(json.dumps(osm_cache))

    monkeypatch.setattr(_osm_data, "CACHE_PATH", osm_path)
    monkeypatch.setattr(_osm_data, "JEFFS_CACHE_PATH", jeffs_path)

    out = _osm_data.load_killarney_features()
    assert len(out["lakes"]) == 1
    assert out["campsites"] == []
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_osm_data.py -v
```

Expected: the 2 new tests fail with `AttributeError: module 'osm_data' has no attribute 'JEFFS_CACHE_PATH'`.

- [ ] **Step 4: Modify osm_data.py to merge Jeff's cache**

Edit `/Users/alex/Documents/camping-planner/osm_data.py`. Near the top, alongside the existing `CACHE_PATH = ...` line, add:

```python
JEFFS_CACHE_PATH = Path(__file__).parent / "jeffs_killarney_cache.json"
```

Find the existing `def load_killarney_features()` function. Replace its body so it reads:

```python
def load_killarney_features() -> dict:
    """Read cached features. Merges Jeff's cache when present.

    Lakes: Jeff's wins on name conflict.
    Portages: OSM only (Phase 1 doesn't extract portages).
    Campsites: Jeff's only (new top-level key; absent OSM-only loads).

    Raises FileNotFoundError if the OSM cache is missing.
    """
    if not CACHE_PATH.exists():
        raise FileNotFoundError(
            f"{CACHE_PATH}: cache missing. "
            "Run `python3 build_trip.py --refresh-osm <trip-dir>` to populate."
        )
    osm = json.loads(CACHE_PATH.read_text())
    out = {
        "lakes": list(osm.get("lakes", [])),
        "portages": list(osm.get("portages", [])),
        "campsites": [],
    }

    if JEFFS_CACHE_PATH.exists():
        jeffs = json.loads(JEFFS_CACHE_PATH.read_text())
        jeffs_lakes = jeffs.get("lakes", [])
        jeffs_names = {l["name"] for l in jeffs_lakes if "name" in l}
        out["lakes"] = (
            [l for l in out["lakes"] if l.get("name") not in jeffs_names]
            + jeffs_lakes
        )
        out["campsites"] = jeffs.get("campsites", [])

    return out
```

- [ ] **Step 5: Run all tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all tests pass (existing + new). The existing build_trip integration tests pass because their fixture has no jeffs cache to merge.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add osm_data.py tests/test_osm_data.py
git commit -m "feat: merge Jeff's cache into load_killarney_features when present"
```

---

## Task 6: Campsite icon detection (Stage C1, TDD)

Per-tile color-segmentation detection of small campsite icons.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`
- Create: `/Users/alex/Documents/camping-planner/campsites_palette.yaml`

- [ ] **Step 1: Create the campsites palette YAML**

Create `/Users/alex/Documents/camping-planner/campsites_palette.yaml`:

```yaml
# HSV thresholds for Jeff's campsite icon color (typically red/orange).
# Tune empirically against the actual KMZ on first run.
hue:        [0, 15]
saturation: [120, 255]
value:      [120, 255]

# Connected-component blob filter
min_area_px: 50
max_area_px: 2000
min_aspect:  0.5    # min width/height ratio
max_aspect:  2.0    # max width/height ratio
```

- [ ] **Step 2: Write the failing test**

Append to `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`:

```python
from jeffs_extractor import detect_icons_in_image


def _tile_with_red_dots(tile_w=400, tile_h=400, dot_centers=((100, 100), (300, 300))):
    """Draw red dots (~20px) on a white background — simulates Jeff's campsite icons."""
    img = np.full((tile_h, tile_w, 3), 255, dtype=np.uint8)  # white BGR
    for cx, cy in dot_centers:
        # OpenCV uses BGR. Pure red is (0, 0, 255).
        cv2.circle(img, (cx, cy), 12, (0, 0, 255), thickness=-1)
    return img


def test_detect_icons_finds_each_red_dot():
    img = _tile_with_red_dots(dot_centers=((100, 100), (300, 300)))
    palette = {"hue": [0, 15], "saturation": [120, 255], "value": [120, 255],
               "min_area_px": 50, "max_area_px": 2000,
               "min_aspect": 0.5, "max_aspect": 2.0}
    icons = detect_icons_in_image(img, palette)
    assert len(icons) == 2
    centers = sorted((round(i["pixel_center"][0]), round(i["pixel_center"][1]))
                     for i in icons)
    assert centers == [(100, 100), (300, 300)]


def test_detect_icons_filters_by_area():
    """A tiny dot below min_area should be ignored."""
    img = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.circle(img, (100, 100), 2, (0, 0, 255), thickness=-1)  # ~12px² area
    palette = {"hue": [0, 15], "saturation": [120, 255], "value": [120, 255],
               "min_area_px": 50, "max_area_px": 2000,
               "min_aspect": 0.5, "max_aspect": 2.0}
    icons = detect_icons_in_image(img, palette)
    assert icons == []
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: the 2 new tests fail with `ImportError: cannot import name 'detect_icons_in_image'`.

- [ ] **Step 4: Implement detect_icons_in_image**

Append to `/Users/alex/Documents/camping-planner/jeffs_extractor.py`:

```python
def detect_icons_in_image(image_bgr: np.ndarray, palette: dict) -> list:
    """HSV color-seg + connected components to find campsite icons in one image.

    Returns a list of dicts:
      {"pixel_center": (px, py), "bbox": (x, y, w, h)}
    Coordinates are in the image's local pixel space.
    """
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    low = np.array([palette["hue"][0], palette["saturation"][0], palette["value"][0]])
    high = np.array([palette["hue"][1], palette["saturation"][1], palette["value"][1]])
    mask = cv2.inRange(hsv, low, high)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )

    min_a = palette.get("min_area_px", 50)
    max_a = palette.get("max_area_px", 2000)
    min_r = palette.get("min_aspect", 0.5)
    max_r = palette.get("max_aspect", 2.0)

    icons = []
    # Skip label 0 (background).
    for i in range(1, num_labels):
        x, y, w, h, area = stats[i]
        if area < min_a or area > max_a:
            continue
        aspect = w / h if h > 0 else 0
        if aspect < min_r or aspect > max_r:
            continue
        cx, cy = centroids[i]
        icons.append({
            "pixel_center": (float(cx), float(cy)),
            "bbox": (int(x), int(y), int(w), int(h)),
        })
    return icons
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: 10 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_extractor.py tests/test_jeffs_extractor.py campsites_palette.yaml
git commit -m "feat: campsite icon color-seg detection per tile"
```

---

## Task 7: OCR for icon numbers + override application (TDD)

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`

- [ ] **Step 1: Write the failing test**

Append to `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`:

```python
from unittest.mock import patch

from jeffs_extractor import ocr_icon_number


_FAKE_OCR_GOOD = {
    "level": [1, 2, 3, 4, 5, 5, 5],
    "conf":  [-1, -1, -1, -1, 92, 88, 70],
    "text":  ["", "", "", "", "8", "2", ""],
}

_FAKE_OCR_LOW_CONF = {
    "level": [1, 2, 3, 4, 5, 5],
    "conf":  [-1, -1, -1, -1, 30, 25],
    "text":  ["", "", "", "", "8", "2"],
}


def test_ocr_icon_number_returns_string_when_confident():
    image = np.full((50, 50, 3), 255, dtype=np.uint8)  # blank crop
    with patch("jeffs_extractor.pytesseract.image_to_data",
               return_value=_FAKE_OCR_GOOD):
        ref = ocr_icon_number(image)
    assert ref == "82"


def test_ocr_icon_number_returns_none_when_unconfident():
    image = np.full((50, 50, 3), 255, dtype=np.uint8)
    with patch("jeffs_extractor.pytesseract.image_to_data",
               return_value=_FAKE_OCR_LOW_CONF):
        ref = ocr_icon_number(image)
    assert ref is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: the 2 new tests fail with `ImportError: cannot import name 'ocr_icon_number'`.

- [ ] **Step 3: Implement ocr_icon_number**

Append to `/Users/alex/Documents/camping-planner/jeffs_extractor.py`:

```python
import pytesseract


_OCR_MIN_CONFIDENCE = 60


def ocr_icon_number(image_crop: np.ndarray) -> Optional[str]:
    """Run Tesseract on a small image crop, return the digit string or None.

    Pre-processes (grayscale + blur + Otsu binarize) before invoking
    pytesseract.image_to_data with PSM=7 and a digit whitelist. Filters
    individual character results below MIN_CONFIDENCE.
    """
    gray = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    config = "--psm 7 -c tessedit_char_whitelist=0123456789"
    data = pytesseract.image_to_data(
        binary, config=config, output_type=pytesseract.Output.DICT,
    )
    confs = data.get("conf", [])
    texts = data.get("text", [])
    digits = []
    for conf, text in zip(confs, texts):
        try:
            conf_n = int(conf)
        except (TypeError, ValueError):
            continue
        if conf_n < _OCR_MIN_CONFIDENCE:
            continue
        clean = "".join(ch for ch in str(text) if ch.isdigit())
        if clean:
            digits.append(clean)
    if not digits:
        return None
    return "".join(digits)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_extractor.py tests/test_jeffs_extractor.py
git commit -m "feat: OCR campsite icon numbers with confidence filter"
```

---

## Task 8: Aggregate campsites — dedupe + lake assignment (Stage C3, TDD)

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`

- [ ] **Step 1: Write failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`:

```python
from jeffs_extractor import aggregate_campsites


def test_aggregate_campsites_dedups_within_10m():
    """Two icons at GPS 1m apart with same ref produce a single output."""
    icons = [
        {"gps": [46.0440, -81.5040], "ref": "82"},
        {"gps": [46.04400001, -81.50400001], "ref": "82"},  # ~1m away
    ]
    lakes = []  # no lake assignment matters for this test
    overrides = {"campsites": []}
    out = aggregate_campsites(icons, lakes, overrides)
    assert len(out) == 1
    assert out[0]["ref"] == "82"


def test_aggregate_campsites_keeps_distinct_far_icons():
    icons = [
        {"gps": [46.0440, -81.5040], "ref": "82"},
        {"gps": [46.0500, -81.5100], "ref": "61"},  # >100m away
    ]
    out = aggregate_campsites(icons, lakes=[], overrides={"campsites": []})
    refs = sorted(c["ref"] for c in out)
    assert refs == ["61", "82"]


def test_aggregate_campsites_assigns_lake_via_point_in_polygon():
    icons = [
        {"gps": [46.05, -81.40], "ref": "12"},
    ]
    lakes = [
        {"name": "Killarney Lake",
         "polygon": [[46.04, -81.41], [46.06, -81.41], [46.06, -81.39],
                     [46.04, -81.39], [46.04, -81.41]],
         "centroid": [46.05, -81.40]},
    ]
    out = aggregate_campsites(icons, lakes, overrides={"campsites": []})
    assert out[0]["lake"] == "Killarney Lake"


def test_aggregate_campsites_applies_override_for_failed_ocr():
    icons = [
        {"gps": [46.044, -81.503], "ref": None},  # OCR failed
    ]
    overrides = {"campsites": [
        {"centroid_near": [46.044, -81.503], "ref": "82"},
    ]}
    out = aggregate_campsites(icons, lakes=[], overrides=overrides)
    assert out[0]["ref"] == "82"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: the 4 new tests fail with `ImportError: cannot import name 'aggregate_campsites'`.

- [ ] **Step 3: Implement aggregate_campsites**

Append to `/Users/alex/Documents/camping-planner/jeffs_extractor.py`:

```python
_DEDUP_RADIUS_KM = 0.01     # 10 m
_OVERRIDE_RADIUS_KM = 0.05  # 50 m


def _point_in_polygon(point, polygon) -> bool:
    """Ray-casting test. Polygon is a closed ring of [lat, lon]."""
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


def aggregate_campsites(icons: list, lakes: list, overrides: dict) -> list:
    """Combine per-tile icons into final campsites: dedupe, override, assign lake.

    Each icon dict must have:
      gps: [lat, lon]
      ref: string or None

    Output list of dicts:
      {ref, lake (or None), gps}
    plus an optional "warning" key when OCR failed and no override matched.
    """
    # 1. Apply overrides first — they correct OCR results.
    override_entries = (overrides or {}).get("campsites", []) or []
    for icon in icons:
        for ov in override_entries:
            near = ov.get("centroid_near")
            if near is None or "ref" not in ov:
                continue
            if _haversine_km(icon["gps"], near) <= _OVERRIDE_RADIUS_KM:
                icon["ref"] = ov["ref"]
                break

    # 2. Dedupe icons within 10m of each other.
    deduped: list = []
    for icon in icons:
        merged = False
        for existing in deduped:
            if _haversine_km(icon["gps"], existing["gps"]) <= _DEDUP_RADIUS_KM:
                # Same physical campsite seen in two tiles. Prefer non-None ref.
                if existing.get("ref") is None and icon.get("ref") is not None:
                    existing["ref"] = icon["ref"]
                merged = True
                break
        if not merged:
            deduped.append(dict(icon))

    # 3. Assign lake by point-in-polygon.
    out: list = []
    for icon in deduped:
        record = {
            "ref": icon.get("ref"),
            "gps": icon["gps"],
            "lake": None,
        }
        for lake in lakes:
            if _point_in_polygon(icon["gps"], lake["polygon"]):
                record["lake"] = lake.get("name")
                break
        if record["ref"] is None:
            record["warning"] = "OCR failed; add to overrides"
        out.append(record)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py -v
```

Expected: 16 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_extractor.py tests/test_jeffs_extractor.py
git commit -m "feat: campsite aggregation with dedupe, override, lake assignment"
```

---

## Task 9: Wire campsites into `route_engine._night_point()`

Auto-resolve site GPS from extracted campsites; manual `gps:` override still wins.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/route_engine.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_route_engine.py`

- [ ] **Step 1: Read the existing _night_point function**

```bash
grep -n -A 10 "def _night_point" /Users/alex/Documents/camping-planner/route_engine.py
```

Expected: shows the closure inside `build_route` returning a [lat, lon] from `night.get("gps")` else lake centroid.

- [ ] **Step 2: Write a failing test**

Append to `/Users/alex/Documents/camping-planner/tests/test_route_engine.py`:

```python
def test_build_route_resolves_site_gps_from_campsites_when_no_override():
    """Campsite extracted from Jeff's data fills in the marker GPS by ref+lake."""
    osm = {
        "lakes": [
            {"name": "OSA Lake",
             "polygon": [[46.05, -81.40], [46.05, -81.38],
                         [46.07, -81.38], [46.07, -81.40],
                         [46.05, -81.40]],
             "centroid": [46.06, -81.39]},
        ],
        "portages": [],
        "campsites": [
            {"ref": "61", "lake": "OSA Lake", "gps": [46.063, -81.392]},
        ],
    }
    nights = [
        {"date": "2026-05-15", "site": "61", "location": "OSA Lake"},
        # No gps: override.
    ]
    out = build_route(nights=nights, access_point="OSA Lake", osm=osm)
    site_marker = [m for m in out["markers"] if m["kind"] == "site"][0]
    # Marker should be at the campsite GPS, not the OSA Lake centroid.
    assert abs(site_marker["lat"] - 46.063) < 1e-4
    assert abs(site_marker["lon"] - -81.392) < 1e-4


def test_build_route_frontmatter_gps_wins_over_campsite():
    osm = {
        "lakes": [
            {"name": "OSA Lake",
             "polygon": [[46.05, -81.40], [46.05, -81.38],
                         [46.07, -81.38], [46.07, -81.40],
                         [46.05, -81.40]],
             "centroid": [46.06, -81.39]},
        ],
        "portages": [],
        "campsites": [
            {"ref": "61", "lake": "OSA Lake", "gps": [46.063, -81.392]},
        ],
    }
    nights = [
        {"date": "2026-05-15", "site": "61", "location": "OSA Lake",
         "gps": [99.0, -99.0]},  # explicit override
    ]
    out = build_route(nights=nights, access_point="OSA Lake", osm=osm)
    site_marker = [m for m in out["markers"] if m["kind"] == "site"][0]
    # Frontmatter override wins.
    assert site_marker["lat"] == 99.0
    assert site_marker["lon"] == -99.0
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_route_engine.py -v 2>&1 | tail -10
```

Expected: 2 new tests fail (the marker still resolves to the lake centroid because campsite-lookup isn't wired up).

- [ ] **Step 4: Modify _night_point and the night-marker builder**

Edit `/Users/alex/Documents/camping-planner/route_engine.py`. Find `_night_point` (a closure inside `build_route`):

```python
    def _night_point(night: dict) -> Optional[list]:
        """Best [lat, lon] for a night: gps override > lake centroid > None."""
        gps = night.get("gps")
        if gps and len(gps) == 2:
            return [gps[0], gps[1]]
        lake = _find_lake(night["location"], lakes)
        return lake["centroid"] if lake else None
```

Replace with:

```python
    def _night_point(night: dict) -> Optional[list]:
        """Best [lat, lon] for a night.

        Resolution order:
          1. Frontmatter `gps:` override.
          2. Auto-resolve from osm['campsites'] by (ref, lake).
          3. Lake centroid.
          4. None if even the lake doesn't resolve.
        """
        gps = night.get("gps")
        if gps and len(gps) == 2:
            return [gps[0], gps[1]]
        site_ref = str(night.get("site", ""))
        location = night.get("location", "")
        for cs in osm.get("campsites", []) or []:
            if cs.get("ref") == site_ref and cs.get("lake") == location:
                return [cs["gps"][0], cs["gps"][1]]
        lake = _find_lake(location, lakes)
        return lake["centroid"] if lake else None
```

Then find the night-marker construction loop later in `build_route()`. It currently looks like:

```python
    for night in nights:
        gps = night.get("gps")
        if gps and len(gps) == 2:
            markers.append({
                "label": f"Site {night['site']}, {night['location']}",
                "lat": gps[0],
                "lon": gps[1],
                "kind": "site",
            })
            continue
        lake = _find_lake(night["location"], lakes)
        if lake:
            markers.append({
                "label": f"Site {night['site']}, {night['location']} (lake center)",
                "lat": lake["centroid"][0],
                "lon": lake["centroid"][1],
                "kind": "site",
            })
```

Replace with:

```python
    for night in nights:
        # Use the same resolution priority as _night_point above.
        gps = night.get("gps")
        if gps and len(gps) == 2:
            markers.append({
                "label": f"Site {night['site']}, {night['location']}",
                "lat": gps[0],
                "lon": gps[1],
                "kind": "site",
            })
            continue
        site_ref = str(night.get("site", ""))
        location = night.get("location", "")
        campsite = next(
            (cs for cs in (osm.get("campsites") or [])
             if cs.get("ref") == site_ref and cs.get("lake") == location),
            None,
        )
        if campsite:
            markers.append({
                "label": f"Site {night['site']}, {night['location']}",
                "lat": campsite["gps"][0],
                "lon": campsite["gps"][1],
                "kind": "site",
            })
            continue
        lake = _find_lake(location, lakes)
        if lake:
            markers.append({
                "label": f"Site {night['site']}, {night['location']} (lake center)",
                "lat": lake["centroid"][0],
                "lon": lake["centroid"][1],
                "kind": "site",
            })
```

- [ ] **Step 5: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add route_engine.py tests/test_route_engine.py
git commit -m "feat: route_engine auto-resolves site GPS from Jeff's campsites"
```

---

## Task 10: CLI assembly + review HTML + extractor main()

Glue together all stages behind the CLI; produce `jeffs_review.html` for visual verification.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/jeffs_extractor.py`
- Modify: `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`

- [ ] **Step 1: Write a failing CLI integration test**

Append to `/Users/alex/Documents/camping-planner/tests/test_jeffs_extractor.py`:

```python
import json as _json

from jeffs_extractor import main as extractor_main


def test_extractor_main_writes_cache_with_lake_polygon(tmp_path, monkeypatch):
    """End-to-end: tiny synthetic KMZ with a blue blob → cache JSON with one lake."""
    kmz = tmp_path / "synthetic.kmz"
    write_synthetic_kmz(kmz, level=6, tiles=[
        {"filename": "a.png",
         "bounds": (46.0, 45.0, -81.0, -82.0),
         "image": _solid_blue_tile_bytes(200, 200)},
    ])
    overrides_yaml = tmp_path / "overrides.yaml"
    overrides_yaml.write_text("lakes: []\ncampsites: []\n")
    lakes_palette_yaml = tmp_path / "lakes_palette.yaml"
    lakes_palette_yaml.write_text(
        "hue: [90, 130]\nsaturation: [80, 255]\nvalue: [80, 255]\n"
        "min_area_px: 100\n"
    )
    campsites_palette_yaml = tmp_path / "campsites_palette.yaml"
    campsites_palette_yaml.write_text(
        "hue: [0, 15]\nsaturation: [120, 255]\nvalue: [120, 255]\n"
        "min_area_px: 50\nmax_area_px: 2000\n"
        "min_aspect: 0.5\nmax_aspect: 2.0\n"
    )
    out_json = tmp_path / "out.json"

    rc = extractor_main([
        str(kmz),
        "--bbox", "45.0,-82.0,46.0,-81.0",
        "--overrides", str(overrides_yaml),
        "--lakes-palette", str(lakes_palette_yaml),
        "--campsites-palette", str(campsites_palette_yaml),
        "--out", str(out_json),
        "--zoom-lakes", "6",
        "--lakes-only",  # synthetic KMZ has no campsite icons; skip stage C
    ])
    assert rc == 0
    data = _json.loads(out_json.read_text())
    assert "lakes" in data
    assert len(data["lakes"]) == 1
    # The blue blob centroid should be near the tile's center (45.5, -81.5).
    cx, cy = data["lakes"][0]["centroid"]
    assert 45.4 < cx < 45.6
    assert -81.6 < cy < -81.4
```

(The test exercises the `--lakes-only` path so we don't need a synthetic campsite icon in the test fixture.)

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_jeffs_extractor.py::test_extractor_main_writes_cache_with_lake_polygon -v
```

Expected: fails with `ImportError: cannot import name 'main' from 'jeffs_extractor'`.

- [ ] **Step 3: Implement main() + the rest of the pipeline**

Append to `/Users/alex/Documents/camping-planner/jeffs_extractor.py`:

```python
import json
from datetime import datetime, timezone

import yaml


def _load_yaml(path: Path) -> dict:
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def _load_osm_lakes_for_naming() -> list:
    """Load OSM cache for naming Jeff's polygons (best-effort)."""
    repo_root = Path(__file__).parent
    osm_path = repo_root / "osm_killarney_cache.json"
    if not osm_path.exists():
        return []
    osm = json.loads(osm_path.read_text())
    return list(osm.get("lakes", []))


def _extract_lakes_pipeline(kmz_path: Path, bbox: tuple, zoom: int,
                            lakes_palette: dict, overrides: dict) -> list:
    """Full lake extraction: walk KMZ → mosaic → segment → name."""
    tiles = list(walk_kmz(kmz_path, bbox=bbox, zoom_level=zoom))
    if not tiles:
        return []
    mosaic, mosaic_bounds = build_mosaic(tiles)
    raw = extract_lakes_from_mosaic(mosaic, mosaic_bounds, lakes_palette)
    osm_lakes = _load_osm_lakes_for_naming()
    named = assign_lake_names(raw, osm_lakes, overrides)
    # Drop polygons that didn't resolve to a name (warn for visibility).
    out = []
    for poly in named:
        if "name" in poly:
            out.append(poly)
        else:
            print(
                f"  Unnamed polygon at {poly['centroid']} "
                f"({len(poly['polygon'])} vertices) — add to overrides.lakes",
                file=sys.stderr,
            )
    return out


def _extract_campsites_pipeline(kmz_path: Path, bbox: tuple, zoom: int,
                                campsites_palette: dict, lakes: list,
                                overrides: dict) -> list:
    """Full campsite extraction: walk KMZ → per-tile detect+OCR → aggregate."""
    raw_icons: list = []
    for tile in walk_kmz(kmz_path, bbox=bbox, zoom_level=zoom):
        image = np.array(Image.open(tile.image_path).convert("RGB"))
        image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        h, w = image_bgr.shape[:2]
        icons = detect_icons_in_image(image_bgr, campsites_palette)
        for icon in icons:
            cx, cy = icon["pixel_center"]
            lat, lon = tile_pixel_to_gps(tile, cx, cy, img_w=w, img_h=h)
            # OCR on the bbox region.
            x, y, bw, bh = icon["bbox"]
            x0 = max(0, x - 30)
            y0 = max(0, y - 30)
            x1 = min(w, x + bw + 30)
            y1 = min(h, y + bh + 30)
            crop = image_bgr[y0:y1, x0:x1]
            ref = ocr_icon_number(crop) if crop.size else None
            raw_icons.append({"gps": [lat, lon], "ref": ref})
    return aggregate_campsites(raw_icons, lakes, overrides)


def _write_review_html(out_path: Path, lakes: list, campsites: list) -> None:
    """Minimal review page: lists what was extracted with counts and centroids."""
    rows_lakes = "".join(
        f"<tr><td>{l.get('name', '<i>(unnamed)</i>')}</td>"
        f"<td>{l['centroid'][0]:.4f}, {l['centroid'][1]:.4f}</td>"
        f"<td>{len(l['polygon'])}</td></tr>"
        for l in lakes
    )
    rows_sites = "".join(
        f"<tr><td>{c.get('ref') or '<i>?</i>'}</td>"
        f"<td>{c.get('lake') or '<i>(unassigned)</i>'}</td>"
        f"<td>{c['gps'][0]:.4f}, {c['gps'][1]:.4f}</td></tr>"
        for c in campsites
    )
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Jeff's extractor review</title>"
        "<style>body{font-family:sans-serif;max-width:900px;margin:2rem auto;padding:1rem}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "th,td{border-bottom:1px solid #ddd;padding:0.4rem 0.6rem;text-align:left}"
        "th{background:#f0f4ee}"
        "</style></head><body>"
        f"<h1>Jeff's extractor — review</h1>"
        f"<h2>Lakes ({len(lakes)})</h2>"
        "<table><thead><tr><th>Name</th><th>Centroid</th><th>Vertices</th>"
        f"</tr></thead><tbody>{rows_lakes}</tbody></table>"
        f"<h2>Campsites ({len(campsites)})</h2>"
        "<table><thead><tr><th>Ref</th><th>Lake</th><th>GPS</th>"
        f"</tr></thead><tbody>{rows_sites}</tbody></table>"
        "</body></html>"
    )
    out_path.write_text(html)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kmz", help="Path to Jeff's KMZ")
    parser.add_argument("--bbox", required=True,
                        help="Target bbox as 'south,west,north,east'")
    parser.add_argument("--overrides", help="overrides YAML path")
    parser.add_argument("--lakes-palette", required=True)
    parser.add_argument("--campsites-palette", required=True)
    parser.add_argument("--out", required=True, help="output JSON path")
    parser.add_argument("--review-html", help="optional review HTML output path")
    parser.add_argument("--zoom-lakes", type=int, default=6)
    parser.add_argument("--zoom-campsites", type=int, default=7)
    parser.add_argument("--lakes-only", action="store_true")
    parser.add_argument("--campsites-only", action="store_true")
    args = parser.parse_args(argv)

    bbox = tuple(float(x) for x in args.bbox.split(","))
    if len(bbox) != 4:
        print("--bbox must have 4 comma-separated values", file=sys.stderr)
        return 2

    overrides = _load_yaml(Path(args.overrides)) if args.overrides else {}
    lakes_palette = _load_yaml(Path(args.lakes_palette))
    campsites_palette = _load_yaml(Path(args.campsites_palette))
    kmz_path = Path(args.kmz)

    lakes: list = []
    campsites: list = []

    if not args.campsites_only:
        print(f"Extracting lakes at zoom {args.zoom_lakes}...", file=sys.stderr)
        lakes = _extract_lakes_pipeline(
            kmz_path, bbox, args.zoom_lakes, lakes_palette, overrides,
        )
        print(f"  {len(lakes)} lakes extracted", file=sys.stderr)

    if not args.lakes_only:
        print(f"Extracting campsites at zoom {args.zoom_campsites}...", file=sys.stderr)
        campsites = _extract_campsites_pipeline(
            kmz_path, bbox, args.zoom_campsites, campsites_palette,
            lakes, overrides,
        )
        ocr_failed = sum(1 for c in campsites if c.get("ref") is None)
        print(f"  {len(campsites)} campsites ({ocr_failed} OCR failed)",
              file=sys.stderr)

    out = {
        "lakes": lakes,
        "campsites": campsites,
        "_meta": {
            "source_kmz": kmz_path.name,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "bbox": list(bbox),
            "lakes_zoom": args.zoom_lakes,
            "campsites_zoom": args.zoom_campsites,
            "lakes_count": len(lakes),
            "campsites_count": len(campsites),
            "campsites_ocr_failed": sum(1 for c in campsites
                                        if c.get("ref") is None),
        },
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.out}", file=sys.stderr)

    if args.review_html:
        _write_review_html(Path(args.review_html), lakes, campsites)
        print(f"Wrote {args.review_html}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all tests pass (existing + the new CLI integration test).

- [ ] **Step 5: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_extractor.py tests/test_jeffs_extractor.py
git commit -m "feat: jeffs_extractor CLI + review HTML output"
```

---

## Task 11: First real run, palette tuning, regenerate trip page

This task is the **empirical loop** — running against the user's actual KMZ, tuning HSV palettes until lakes and campsites extract cleanly. It's not pure TDD; success is judged by visual review.

**Files:**
- Modify: `/Users/alex/Documents/camping-planner/lakes_palette.yaml` (palette tuning)
- Modify: `/Users/alex/Documents/camping-planner/campsites_palette.yaml` (palette tuning)
- Modify: `/Users/alex/Documents/camping-planner/jeffs_killarney_overrides.yaml` (manual fixes)
- Create: `/Users/alex/Documents/camping-planner/jeffs_killarney_cache.json`
- Modify: `/Users/alex/Documents/camping-planner/trips/killarney-2026-05/trip.html` (regenerated)
- Modify: `/Users/alex/Documents/camping-planner/trips/killarney-2026-05/trip.md` (drop manual `gps:` for site 82 once auto-resolved)

- [ ] **Step 1: Verify Tesseract is installed system-side**

```bash
which tesseract && tesseract --version | head -1
```

Expected: prints a path and version. If not found, run `brew install tesseract` (macOS) or `apt install tesseract-ocr` (Linux) and re-check.

- [ ] **Step 2: Run the lake-only extraction**

```bash
cd /Users/alex/Documents/camping-planner
python3 jeffs_extractor.py \
  "/Users/alex/Documents/camping-planner/Maps by Jeff - Full French River and Killarney Paddling Map v4.0 - Google Earth.kmz" \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --overrides jeffs_killarney_overrides.yaml \
  --lakes-palette lakes_palette.yaml \
  --campsites-palette campsites_palette.yaml \
  --out jeffs_killarney_cache.json \
  --review-html jeffs_review.html \
  --lakes-only
```

Expected output to stderr:
```
Extracting lakes at zoom 6...
  Unnamed polygon at [...] (...) — add to overrides.lakes
  ...
  N lakes extracted
Wrote jeffs_killarney_cache.json
Wrote jeffs_review.html
```

- [ ] **Step 3: Open jeffs_review.html and visually verify lake count**

```bash
open /Users/alex/Documents/camping-planner/jeffs_review.html
```

Expected count: somewhere between 30 and 80 named lakes (tunable). If lakes are missing or wildly wrong:
- Re-tune `lakes_palette.yaml` — adjust hue/sat/val ranges. Re-run Step 2.
- Add lake-name overrides for Baie Fine and any other unnamed major water:

```yaml
# in jeffs_killarney_overrides.yaml
lakes:
  - centroid_near: [<from stderr warning>]
    name: Baie Fine
```

Re-run Step 2 until satisfied. **Budget 1-2 hours for this loop.**

- [ ] **Step 4: Run the full extraction (lakes + campsites)**

```bash
cd /Users/alex/Documents/camping-planner
python3 jeffs_extractor.py \
  "/Users/alex/Documents/camping-planner/Maps by Jeff - Full French River and Killarney Paddling Map v4.0 - Google Earth.kmz" \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --overrides jeffs_killarney_overrides.yaml \
  --lakes-palette lakes_palette.yaml \
  --campsites-palette campsites_palette.yaml \
  --out jeffs_killarney_cache.json \
  --review-html jeffs_review.html
```

Expected: now prints campsite count + OCR failures.

- [ ] **Step 5: Verify campsites in review HTML**

Open `jeffs_review.html` and confirm:
- Campsites for the Killarney trip exist: site 12 on Killarney Lake, 61 on OSA Lake, 82 on Baie Fine.
- OCR-failed campsites are listed with `?` for ref. For each, find the GPS in the table and add an override:

```yaml
# in jeffs_killarney_overrides.yaml
campsites:
  - centroid_near: [<from review>]
    ref: '<correct number>'
```

Re-run Step 4 until accuracy is acceptable. **Budget 1-2 hours.**

- [ ] **Step 6: Verify the trip page picks up the new data**

```bash
cd /Users/alex/Documents/camping-planner
python3 build_trip.py trips/killarney-2026-05/
```

Expected: `Wrote trips/killarney-2026-05/trip.html`. The OSA → Baie Fine and Baie Fine → Killarney Lake legs should now use the proper Baie Fine polygon (no longer falling back to approx for that reason). Marker for site 82 should match what's in `jeffs_killarney_cache.json`.

- [ ] **Step 7: Drop the manual `gps:` override for site 82**

Edit `/Users/alex/Documents/camping-planner/trips/killarney-2026-05/trip.md`. Remove the line:

```yaml
    gps: [46.044041, -81.503845]
```

(under the site 82 entry).

Re-run `python3 build_trip.py trips/killarney-2026-05/`. Verify the site 82 marker still lands at the same place (auto-resolved from `jeffs_killarney_cache.json`'s campsite ref 82 on Baie Fine).

- [ ] **Step 8: Smoke-test the regenerated HTML**

```bash
cd /Users/alex/Documents/camping-planner
python3 -c "
from pathlib import Path
import re
html = Path('trips/killarney-2026-05/trip.html').read_text()
print(f'approx cells: {html.count(\"(approx)\")}')
print(f'warning markers: {html.count(\"⚠\")}')
m = re.search(r'<strong>(\d+\.\d+) km</strong>.*?<strong>(\d+\.\d+) km</strong>', html)
if m:
    print(f'Total paddle: {m.group(1)} km, portage: {m.group(2)} km')
"
```

Expected: approx-cells count is lower than before (Baie Fine legs now have a real polygon containing them, so they don't fall to lake-unmatched approx).

- [ ] **Step 9: Browser verification**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m http.server 8000 &
sleep 1
open "http://localhost:8000/trips/killarney-2026-05/trip.html"
```

Confirm visually:
- Baie Fine appears as a polygon, not just a centroid pin.
- Site 82 marker is at the right place.
- Other site markers (12, 61) also pin at sensible locations.

Stop the server when done: `kill %1`.

- [ ] **Step 10: Commit cache + regenerated HTML + trip.md change**

```bash
cd /Users/alex/Documents/camping-planner
git add jeffs_killarney_cache.json jeffs_killarney_overrides.yaml \
        lakes_palette.yaml campsites_palette.yaml \
        trips/killarney-2026-05/trip.html trips/killarney-2026-05/trip.md
git commit -m "feat: extract Killarney lakes + campsites from Jeff's Maps KMZ"
```

- [ ] **Step 11: Push**

```bash
cd /Users/alex/Documents/camping-planner
git pull --rebase && git push
```

Expected: pushes to origin/main. pizza-zip pulls and gets identical rendering.

---

## Verification checklist (run after Task 11)

- [ ] `python3 -m pytest tests/ -v` shows all tests passing (50 + ~16 new = ~66)
- [ ] `jeffs_killarney_cache.json` is committed and < 500 KB
- [ ] `trips/killarney-2026-05/trip.html` shows Baie Fine area with reduced approx cells
- [ ] Site 82 marker is auto-resolved (no `gps:` in trip.md)
- [ ] `git log --oneline | head -12` shows the 11 task commits

If all five pass, the feature is complete.
