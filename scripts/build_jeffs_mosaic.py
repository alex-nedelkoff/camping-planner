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

The default --bbox covers the KMZ's full extent (Killarney + French River),
derived from the union of every tile's <LatLonBox> in doc.kml. At zoom 6 that
produces a ~25kx6k JPG (~18 MB). Pass --zoom 5 to shrink it, or a tighter
--bbox to restrict to Killarney proper (45.92,-81.75,46.12,-81.24).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kmz", required=True, help="KMZ file (absolute or relative to repo root)")
    # Full KMZ extent (Killarney + French River) — union of every tile's
    # LatLonBox in doc.kml. Pass --bbox 45.92,-81.75,46.12,-81.24 for
    # Killarney-only.
    parser.add_argument("--bbox", default="45.822,-81.7472,46.2824,-79.7503",
                        help="south,west,north,east — defaults to full KMZ extent")
    parser.add_argument("--zoom", type=int, default=6,
                        help="KMZ zoom level (lower=fewer, larger tiles; default 6)")
    parser.add_argument("--out", default="data/jeffs_killarney_mosaic.jpg",
                        help="Output JPG path (relative to repo root)")
    parser.add_argument("--jpeg-quality", type=int, default=78)
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
