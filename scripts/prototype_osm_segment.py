"""
Prototype: derive water polygons from OSM tile raster (much cleaner palette
than Jeff's map). Same algorithm shape as prototype_water_from_border.py but
sourced from OSM standard tiles instead of Jeff's KMZ.

Pipeline:
  1. Fetch OSM tiles for the bbox at the given zoom.
  2. Stitch into mosaic.
  3. K-means quantize.
  4. Identify water class (most-saturated blue).
  5. Extract water mask + derived polygons.

Usage:
    python3 scripts/prototype_osm_segment.py
    python3 scripts/prototype_osm_segment.py --bbox 46.00,-81.45,46.10,-81.30 --zoom 14
"""
import argparse
import io
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_BBOX = (46.005, -81.42, 46.04, -81.38)
TILE_SIZE = 256
USER_AGENT = "camping-planner-research/1.0 (alex@local prototype)"


def deg2num(lat: float, lon: float, zoom: int) -> tuple:
    """Convert lat/lon to OSM tile (x, y) at zoom level."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return (x, y)


def num2deg(x: float, y: float, zoom: int) -> tuple:
    """Convert OSM tile (x, y) at zoom to lat/lon (north-west corner)."""
    n = 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)
    return (lat, lon)


def fetch_osm_mosaic(bbox: tuple, zoom: int) -> tuple:
    """Fetch + stitch OSM tiles covering bbox. Returns (bgr, mosaic_bounds).

    bbox = (south, west, north, east). mosaic_bounds = (south, west, north, east)
    of the actual stitched image (slightly larger than bbox due to tile grid).
    """
    import requests
    s, w, n, e = bbox
    x0_f, y0_f = deg2num(n, w, zoom)  # NW corner: (x0, y0)
    x1_f, y1_f = deg2num(s, e, zoom)  # SE corner
    x0, y0 = int(math.floor(x0_f)), int(math.floor(y0_f))
    x1, y1 = int(math.floor(x1_f)), int(math.floor(y1_f))
    n_tiles = (x1 - x0 + 1) * (y1 - y0 + 1)
    print(f"  fetching {n_tiles} OSM tiles at zoom {zoom} "
          f"({x0}..{x1} x {y0}..{y1})", file=sys.stderr)

    width = (x1 - x0 + 1) * TILE_SIZE
    height = (y1 - y0 + 1) * TILE_SIZE
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    headers = {"User-Agent": USER_AGENT}
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            url = f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"  WARN tile {tx}/{ty}: {r.status_code}",
                      file=sys.stderr)
                continue
            arr = np.frombuffer(r.content, dtype=np.uint8)
            tile = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if tile is None:
                continue
            cy = (ty - y0) * TILE_SIZE
            cx = (tx - x0) * TILE_SIZE
            canvas[cy:cy + TILE_SIZE, cx:cx + TILE_SIZE] = tile
            time.sleep(0.1)  # be polite to OSM tile server

    # Bounds of the stitched canvas.
    nw_lat, nw_lon = num2deg(x0, y0, zoom)
    se_lat, se_lon = num2deg(x1 + 1, y1 + 1, zoom)
    mosaic_bounds = (se_lat, nw_lon, nw_lat, se_lon)  # (s, w, n, e)
    return canvas, mosaic_bounds


def kmeans_quantize(bgr: np.ndarray, n_colors: int = 6) -> tuple:
    """K-means color quantization."""
    h, w = bgr.shape[:2]
    pixels = bgr.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(
        pixels, n_colors, None, criteria, attempts=4,
        flags=cv2.KMEANS_PP_CENTERS,
    )
    centers = centers.astype(np.uint8)
    quantized = centers[labels.flatten()].reshape((h, w, 3))
    label_map = labels.reshape((h, w)).astype(np.int32)
    return quantized, label_map, centers


def find_water_class(palette: np.ndarray, label_map: np.ndarray,
                     min_pct: float = 2.0) -> int:
    """OSM standard water is light-blue ~#aad3df. Among blue classes with
    at least min_pct of total pixels, pick the largest.

    The population filter avoids picking up tiny accent marks (wetland
    decoration, specific symbols) that share the saturated-blue range but
    only cover a fraction of a percent.
    """
    n = palette.shape[0]
    palette_hsv = cv2.cvtColor(palette.reshape(-1, 1, 3),
                               cv2.COLOR_BGR2HSV).reshape(-1, 3)
    total = label_map.size
    candidates = []
    for i in range(n):
        h, s, v = palette_hsv[i]
        if not (85 <= h <= 130):
            continue
        if v < 150:
            continue
        count = int(np.sum(label_map == i))
        pct = 100 * count / total
        if pct < min_pct:
            continue
        candidates.append((i, pct, h, s, v))
    if not candidates:
        return None
    # Largest blue class wins.
    candidates.sort(key=lambda c: c[1], reverse=True)
    return candidates[0][0]


def panel(images: list, labels: list) -> np.ndarray:
    if len(images) != 4:
        h = max(im.shape[0] for im in images)
        w = sum(im.shape[1] for im in images)
        out = np.full((h + 30, w, 3), 255, dtype=np.uint8)
        x = 0
        for im, lbl in zip(images, labels):
            if im.ndim == 2:
                im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
            out[30:30 + im.shape[0], x:x + im.shape[1]] = im
            cv2.putText(out, lbl, (x + 10, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2,
                        cv2.LINE_AA)
            x += im.shape[1]
        return out
    panel_h, panel_w = images[0].shape[:2]
    label_h = 30
    out = np.full((2 * (panel_h + label_h), 2 * panel_w, 3), 255,
                  dtype=np.uint8)
    for idx, (im, lbl) in enumerate(zip(images, labels)):
        if im.ndim == 2:
            im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        row = idx // 2
        col = idx % 2
        y0 = row * (panel_h + label_h)
        x0 = col * panel_w
        cv2.putText(out, lbl, (x0 + 10, y0 + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2,
                    cv2.LINE_AA)
        out[y0 + label_h:y0 + label_h + panel_h, x0:x0 + panel_w] = im
    return out


def render_palette_swatch(palette: np.ndarray, label_map: np.ndarray,
                          water_idx,
                          width_px: int = 800) -> np.ndarray:
    n = palette.shape[0]
    sw_h = 60
    img = np.full((n * sw_h, width_px, 3), 255, dtype=np.uint8)
    total = label_map.size
    palette_hsv = cv2.cvtColor(palette.reshape(-1, 1, 3),
                               cv2.COLOR_BGR2HSV).reshape(-1, 3)
    for i in range(n):
        y0 = i * sw_h
        cv2.rectangle(img, (0, y0), (200, y0 + sw_h),
                      tuple(int(c) for c in palette[i]), -1)
        count = int(np.sum(label_map == i))
        pct = 100 * count / total
        h, s, v = palette_hsv[i]
        role = " ← WATER" if i == water_idx else ""
        text = f"#{i}  HSV=({h},{s},{v})  {pct:.1f}%{role}"
        cv2.putText(img, text, (210, y0 + 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
    return img


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", default=",".join(str(x) for x in DEFAULT_BBOX))
    parser.add_argument("--zoom", type=int, default=15)
    parser.add_argument("--n-colors", type=int, default=6)
    parser.add_argument("--min-polygon-area", type=int, default=400)
    parser.add_argument("--out", default="osm_segment_prototype.jpg")
    args = parser.parse_args(argv)

    bbox = tuple(float(x) for x in args.bbox.split(","))

    bgr, mosaic_bounds = fetch_osm_mosaic(bbox, args.zoom)
    print(f"  mosaic: {bgr.shape[1]}x{bgr.shape[0]} px, "
          f"bounds={mosaic_bounds}", file=sys.stderr)

    quantized, label_map, palette = kmeans_quantize(bgr, args.n_colors)
    water_idx = find_water_class(palette, label_map)
    print(f"  water_idx={water_idx}", file=sys.stderr)
    if water_idx is None:
        print("  ERROR: no water class found in palette", file=sys.stderr)
        return 1

    water_mask = (label_map == water_idx).astype(np.uint8) * 255
    # Close small gaps from text/icons over water.
    water_mask = cv2.morphologyEx(
        water_mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
    )
    # Drop tiny noise.
    n, lbl, st, _ = cv2.connectedComponentsWithStats(water_mask, connectivity=8)
    keep = np.zeros_like(water_mask)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= args.min_polygon_area:
            keep[lbl == i] = 255
    water_mask = keep
    print(f"  water mask: {int((water_mask > 0).sum())} px "
          f"({100 * (water_mask > 0).mean():.1f}%)", file=sys.stderr)

    contours, _ = cv2.findContours(
        water_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    print(f"  derived water polygons: {len(contours)}", file=sys.stderr)

    # Visualizations.
    water_viz = bgr.copy()
    blue_layer = np.zeros_like(bgr)
    blue_layer[water_mask > 0] = (255, 80, 0)
    water_viz = cv2.addWeighted(water_viz, 0.55, blue_layer, 0.45, 0)
    water_viz[water_mask == 0] = bgr[water_mask == 0]

    contour_viz = bgr.copy()
    cv2.drawContours(contour_viz, contours, -1, (0, 255, 255), 2)

    composite = panel(
        [bgr, quantized, water_viz, contour_viz],
        ["original (OSM)", f"k-means N={args.n_colors}",
         f"water mask ({int(100*(water_mask>0).mean())}%)",
         f"derived polygons ({len(contours)})"],
    )
    out_path = REPO_ROOT / args.out
    cv2.imwrite(str(out_path), composite, [cv2.IMWRITE_JPEG_QUALITY, 88])
    swatch = render_palette_swatch(palette, label_map, water_idx)
    cv2.imwrite(str(out_path.with_name(out_path.stem + "_palette.jpg")),
                swatch, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"Wrote {out_path}", file=sys.stderr)

    html_path = out_path.with_suffix(".html")
    html_path.write_text(
        "<!DOCTYPE html><html><head><title>OSM segmentation prototype</title>"
        "<style>body{margin:0;padding:1rem;font-family:sans-serif;"
        "background:#222;color:#eee}img{max-width:100%;display:block;"
        "margin-top:0.6rem}h1{font-size:1.1rem;margin:0}.meta{color:#aaa;"
        "font-size:0.85rem}</style></head>"
        f"<body><h1>OSM segmentation prototype — zoom {args.zoom}, "
        f"N={args.n_colors}, bbox {bbox}</h1>"
        f"<div class='meta'>{bgr.shape[1]}x{bgr.shape[0]} px, "
        f"water_idx={water_idx}</div>"
        f"<img src='{out_path.name}' alt='4-panel'/>"
        f"<h2>Palette</h2>"
        f"<img src='{out_path.stem}_palette.jpg' alt='palette' "
        "style='max-width:800px'/></body></html>"
    )
    print(f"Wrote {html_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
