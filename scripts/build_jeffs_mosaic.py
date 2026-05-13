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


def reproject_plate_carree_to_mercator(mosaic, n: float, s: float):
    """Resample a plate-carrée image vertically into Web Mercator pixel space.

    Leaflet's L.imageOverlay assumes the source image is uniform in Mercator
    coords, but jeffs_extractor stitches tiles uniformly in plate carrée
    (1° lat = 1° lon in pixels). At Killarney's latitude that introduces a
    ~44% horizontal-vs-vertical stretch when Leaflet projects the lat/lon
    corners onto a Mercator map. This rewrites the image so each pixel row
    corresponds to a Mercator-y interval, eliminating the distortion.

    Width is preserved (longitude IS linear in Mercator). Height is chosen
    so 1 Mercator-y unit = 1 longitude-radian unit (square pixels in
    Mercator), giving Leaflet a 1:1 placement.
    """
    import cv2
    import numpy as np

    h_in, w_in = mosaic.shape[:2]
    y_north = _mercator_y(n)
    y_south = _mercator_y(s)
    merc_y_span = y_north - y_south
    # Aspect ratio target: the input represents (e - w) degrees of lon
    # (linear) and (n - s) degrees of lat. We don't know e/w here, but the
    # input pixel ratio already encodes them via plate-carrée — so the
    # vertical stretch factor we need is merc_y_span / lat_span_in_radians.
    lat_span_rad = math.radians(n - s)
    stretch = merc_y_span / lat_span_rad   # ~1.44 at Killarney
    h_out = int(round(h_in * stretch))

    # For each output row, compute its Mercator y, invert to lat, then to
    # source-row index. Build a 1D map and use cv2.remap for speed.
    rows = np.arange(h_out, dtype=np.float32)
    y_at_row = y_north - (rows / max(h_out - 1, 1)) * merc_y_span
    # Vectorised inverse Mercator: lat = degrees(2*atan(exp(y)) - π/2)
    lat_at_row = np.degrees(2 * np.arctan(np.exp(y_at_row)) - np.pi / 2)
    src_y_at_row = (n - lat_at_row) / (n - s) * (h_in - 1)
    map_x = np.broadcast_to(
        np.arange(w_in, dtype=np.float32), (h_out, w_in),
    )
    map_y = np.broadcast_to(src_y_at_row[:, None], (h_out, w_in)).astype(np.float32)
    return cv2.remap(mosaic, map_x, map_y, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kmz", required=True, help="KMZ file (absolute or relative to repo root)")
    # Killarney area at the western/eastern extent of the dense map data —
    # the western edge (-81.7472) is the true KMZ west, captured by walking
    # every tile's LatLonBox. Pass a wider bbox to include French River, or
    # a tighter one for just the park's interior.
    parser.add_argument("--bbox", default="45.92,-81.7472,46.18,-81.05",
                        help="south,west,north,east — defaults to Killarney area")
    parser.add_argument("--zoom", type=int, default=6,
                        help="KMZ zoom level (lower=fewer, larger tiles; default 6)")
    parser.add_argument("--out", default="data/jeffs_killarney_mosaic.jpg",
                        help="Output JPG path (relative to repo root)")
    parser.add_argument("--jpeg-quality", type=int, default=78)
    parser.add_argument("--no-mercator", action="store_true",
                        help="Skip the plate-carrée → Web Mercator reprojection. "
                             "Leaflet's imageOverlay will then visibly stretch "
                             "the image vertically at non-equator latitudes.")
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

        print("building mosaic…", flush=True)
        mosaic, (n, s, e, w) = build_mosaic(tiles)
    h, wpx = mosaic.shape[:2]
    print(f"  mosaic (plate carrée): {wpx}x{h} px, bounds N={n:.4f} S={s:.4f} E={e:.4f} W={w:.4f}", flush=True)

    if not args.no_mercator:
        print("reprojecting plate carrée → Web Mercator…", flush=True)
        mosaic = reproject_plate_carree_to_mercator(mosaic, n=n, s=s)
        h, wpx = mosaic.shape[:2]
        print(f"  mosaic (mercator):    {wpx}x{h} px (same lat/lon corners, taller in pixels)",
              flush=True)

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
