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


import cv2
import numpy as np
from PIL import Image as _PIL_Image


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
    sample_img = np.array(_PIL_Image.open(sample.image_path).convert("RGB"))
    sample_h, sample_w = sample_img.shape[:2]
    px_per_deg_lon = sample_w / (sample.east - sample.west)
    px_per_deg_lat = sample_h / (sample.north - sample.south)

    mosaic_w = max(1, round((e - w) * px_per_deg_lon))
    mosaic_h = max(1, round((n - s) * px_per_deg_lat))
    mosaic = np.full((mosaic_h, mosaic_w, 3), 255, dtype=np.uint8)

    for tile in tiles:
        img = np.array(_PIL_Image.open(tile.image_path).convert("RGB"))
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
    import shutil
    extract_dir = Path(tempfile.mkdtemp(prefix="jeffs_lakes_"))
    try:
        tiles = list(walk_kmz(kmz_path, bbox=bbox, zoom_level=zoom,
                              extract_dir=extract_dir))
        if not tiles:
            return []
        mosaic, mosaic_bounds = build_mosaic(tiles)
        raw = extract_lakes_from_mosaic(mosaic, mosaic_bounds, lakes_palette)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
    osm_lakes = _load_osm_lakes_for_naming()
    named = assign_lake_names(raw, osm_lakes, overrides)
    # Warn about polygons that didn't resolve to a name (keep them in output).
    out = []
    for poly in named:
        if "name" not in poly:
            print(
                f"  Unnamed polygon at {poly['centroid']} "
                f"({len(poly['polygon'])} vertices) — add to overrides.lakes",
                file=sys.stderr,
            )
        out.append(poly)
    return out


def _extract_campsites_pipeline(kmz_path: Path, bbox: tuple, zoom: int,
                                campsites_palette: dict, lakes: list,
                                overrides: dict) -> list:
    """Full campsite extraction: walk KMZ → per-tile detect+OCR → aggregate."""
    raw_icons: list = []
    for tile in walk_kmz(kmz_path, bbox=bbox, zoom_level=zoom):
        image = np.array(_PIL_Image.open(tile.image_path).convert("RGB"))
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
