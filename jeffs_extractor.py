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
