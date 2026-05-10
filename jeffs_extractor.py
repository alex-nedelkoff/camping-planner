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


def main():
    parser = argparse.ArgumentParser(description="Extract vector data from Jeff's Maps KMZ")
    parser.add_argument("kmz", help="Path to KMZ file")
    parser.add_argument("--bbox", required=True,
                        help="Bounding box: south,west,north,east")
    parser.add_argument("--out", default="jeffs_killarney_cache.json",
                        help="Output JSON file")
    parser.add_argument("--zoom", type=int, default=6,
                        help="Zoom level directory to use (default: 6)")
    args = parser.parse_args()

    south, west, north, east = map(float, args.bbox.split(","))
    bbox = (south, west, north, east)

    tiles = list(walk_kmz(Path(args.kmz), bbox=bbox, zoom_level=args.zoom))
    print(f"Found {len(tiles)} tiles in bbox at zoom level {args.zoom}")


if __name__ == "__main__":
    main()
