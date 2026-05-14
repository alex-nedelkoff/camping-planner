#!/usr/bin/env python3
"""Build a full-park Jeff's Maps raster mosaic for the route editor overlay.

The existing data/.../jeffs_osm_overlay_raster.jpg only covers part of the
park because the original overlay was built with a tight bbox. This rebuilds
it covering the whole Killarney area used by the planner.

Output:
    data/jeffs_killarney_mosaic.jpg     — BGR JPEG, max width auto-sized
    data/jeffs_killarney_mosaic.json    — {filename, bounds: [[s,w],[n,e]]}

Usage:
    python3 scripts/build_jeffs_mosaic.py \\
      --kmz "Maps by Jeff - Full French River and Killarney Paddling Map v4.0 - Google Earth.kmz"

The default --bbox covers Killarney (45.92,-81.7472 → 46.18,-81.05) at zoom 6,
producing a ~9kx3.4k JPG (~5 MB). This is the trip-planner-relevant area.

The KMZ also covers French River extending east to ~-79.75, so to grab the
full KMZ pass --bbox 45.822,-81.7472,46.2824,-79.7503. At zoom 6 that's
~25kx6k px / ~17 MB JPG — manageable on disk but the browser has to keep
~600 MB of decoded RGBA in memory, which scales the imageOverlay down
aggressively and can wash out fine detail. Drop to --zoom 5 to balance.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _mercator_y(lat_deg: float) -> float:
    """Spherical Web Mercator y, in radians (lon-equivalent units)."""
    return math.log(math.tan(math.pi / 4 + math.radians(lat_deg) / 2))


def _inv_mercator_y(y: float) -> float:
    """Inverse of _mercator_y — returns latitude in degrees."""
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def build_mercator_mosaic(tiles: list):
    """Stitch tiles directly in Web Mercator pixel space.

    The KMZ tiles are themselves Web Mercator tiles at a fixed zoom level —
    their LatLonBox is the lat/lon footprint of a Mercator pixel rectangle.
    Stitching uniformly in plate carrée (what jeffs_extractor.build_mosaic
    does) accumulates a few percent of horizontal-vs-vertical error at
    Killarney's latitude, so lakes don't line up with the OSM polygons.

    Here we project every tile's corners through Mercator and stitch in
    Mercator pixel coordinates. Pixel scale is set so 1 unit = 1 longitude-
    radian (square pixels in Mercator), matching what L.imageOverlay
    expects when handed lat/lon bounds.

    Returns (mosaic_array, (north, south, east, west)).
    """
    import cv2
    import numpy as np
    from PIL import Image as _PIL_Image

    if not tiles:
        raise ValueError("build_mercator_mosaic: no tiles provided")

    # Outer lat/lon bounds (same as jeffs_extractor.build_mosaic).
    n = max(t.north for t in tiles)
    s = min(t.south for t in tiles)
    e = max(t.east for t in tiles)
    w = min(t.west for t in tiles)

    # Pick a horizontal pixel-per-radian scale from the first tile's image
    # width — keeps the output at native KMZ resolution. Width is linear in
    # Mercator x (= longitude in radians).
    sample = tiles[0]
    sample_img = np.array(_PIL_Image.open(sample.image_path).convert("RGB"))
    sample_h, sample_w = sample_img.shape[:2]
    px_per_rad = sample_w / math.radians(sample.east - sample.west)

    y_n = _mercator_y(n)
    y_s = _mercator_y(s)
    mosaic_w = max(1, round(math.radians(e - w) * px_per_rad))
    mosaic_h = max(1, round((y_n - y_s) * px_per_rad))
    mosaic = np.full((mosaic_h, mosaic_w, 3), 255, dtype=np.uint8)

    for tile in tiles:
        # Position of this tile's corners in the output mosaic, in Mercator
        # pixel coords.
        x0 = round(math.radians(tile.west - w) * px_per_rad)
        x1 = round(math.radians(tile.east - w) * px_per_rad)
        # y axis grows DOWN; Mercator y grows UP — so flip.
        y0 = round((y_n - _mercator_y(tile.north)) * px_per_rad)
        y1 = round((y_n - _mercator_y(tile.south)) * px_per_rad)
        tw, th = x1 - x0, y1 - y0
        if tw <= 0 or th <= 0:
            continue
        img = np.array(_PIL_Image.open(tile.image_path).convert("RGB"))
        # PIL is RGB; numpy/cv2 mosaic is BGR — convert before placement.
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        # Resize the tile image to its target Mercator footprint.
        if img.shape[1] != tw or img.shape[0] != th:
            img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        # Clip to mosaic bounds.
        sx0, sy0 = max(0, -x0), max(0, -y0)
        dx0, dy0 = max(0, x0), max(0, y0)
        dx1 = min(mosaic_w, x0 + tw)
        dy1 = min(mosaic_h, y0 + th)
        if dx1 <= dx0 or dy1 <= dy0:
            continue
        crop = img[sy0:sy0 + (dy1 - dy0), sx0:sx0 + (dx1 - dx0)]
        mosaic[dy0:dy1, dx0:dx1] = crop

    return mosaic, (n, s, e, w)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kmz", required=True, help="KMZ file (absolute or relative to repo root)")
    # Killarney area covering the full N-S extent of the KMZ in this region
    # (north reaches 46.2824 per the union of every tile's LatLonBox). Pass
    # a wider --bbox to include French River east of Killarney, or a
    # tighter one for just the park's interior.
    parser.add_argument("--bbox", default="45.92,-81.7472,46.30,-81.05",
                        help="south,west,north,east — defaults to Killarney area")
    parser.add_argument("--zoom", type=int, default=6,
                        help="KMZ zoom level (lower=fewer, larger tiles; default 6)")
    parser.add_argument("--out", default="data/jeffs_killarney_mosaic.jpg",
                        help="Output JPG path (relative to repo root)")
    parser.add_argument("--jpeg-quality", type=int, default=78)
    parser.add_argument("--no-mercator", action="store_true",
                        help="Use jeffs_extractor.build_mosaic (plate carrée, "
                             "legacy). The result will be visibly stretched on "
                             "Leaflet's Mercator map.")
    args = parser.parse_args()

    import cv2
    from jeffs_extractor import walk_kmz, build_mosaic

    kmz = Path(args.kmz)
    if not kmz.is_absolute():
        # Try relative to repo root or its parent (worktrees).
        for base in (REPO_ROOT, REPO_ROOT.parents[2] if len(REPO_ROOT.parents) >= 3 else REPO_ROOT):
            if (base / kmz).is_file():
                kmz = base / kmz
                break
    if not kmz.is_file():
        print(f"KMZ not found: {kmz}", file=sys.stderr)
        return 2

    south, west, north, east = (float(x) for x in args.bbox.split(","))
    bbox = (south, west, north, east)
    print(f"bbox: S={south} W={west} N={north} E={east}, zoom={args.zoom}", flush=True)

    # walk_kmz cleans its temp dir when the generator is exhausted, which
    # invalidates the image paths needed by build_mosaic. Hand it an explicit
    # extract_dir we control so the tile JPGs stick around for stitching.
    with tempfile.TemporaryDirectory(prefix="kmz_mosaic_") as extract_dir:
        extract_path = Path(extract_dir)
        print("walking kmz…", flush=True)
        tiles = list(walk_kmz(kmz, bbox=bbox, zoom_level=args.zoom, extract_dir=extract_path))
        print(f"  {len(tiles)} tiles intersect bbox", flush=True)
        if not tiles:
            print("no tiles — bbox may not intersect the KMZ contents", file=sys.stderr)
            return 1

        if args.no_mercator:
            print("building mosaic (plate carrée — legacy)…", flush=True)
            mosaic, (n, s, e, w) = build_mosaic(tiles)
        else:
            print("building mosaic (Web Mercator)…", flush=True)
            mosaic, (n, s, e, w) = build_mercator_mosaic(tiles)
    h, wpx = mosaic.shape[:2]
    print(f"  mosaic: {wpx}x{h} px, bounds N={n:.4f} S={s:.4f} E={e:.4f} W={w:.4f}", flush=True)

    out_jpg = REPO_ROOT / args.out
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_jpg), mosaic, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
    size_kb = out_jpg.stat().st_size // 1024
    print(f"  wrote {out_jpg}  ({size_kb} KB)", flush=True)

    # Sidecar JSON — Leaflet wants [[south, west], [north, east]].
    side = out_jpg.with_suffix(".json")
    side.write_text(json.dumps({
        "filename": out_jpg.name,
        "bounds": [[s, w], [n, e]],
        "pixels": [wpx, h],
    }, indent=2))
    print(f"  wrote {side}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
