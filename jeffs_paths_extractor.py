"""
Extract Jeff's yellow canoe-route polylines from the KMZ raster.

Output: jeffs_canoe_paths.json — a list of GPS polylines that
paddle_router.route_paddle_leg snaps to as the preferred routing source.

Usage:
  python3 jeffs_paths_extractor.py path/to/jeffs.kmz \\
    --bbox 45.92,-81.60,46.12,-81.25 \\
    --paths-palette paths_palette.yaml \\
    --out jeffs_canoe_paths.json \\
    --review-html jeffs_paths_review.html
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


def _skeletonize(mask: np.ndarray) -> np.ndarray:
    """Reduce a binary mask to a 1-pixel-wide centerline.

    Tries cv2.ximgproc.thinning first (fast, C++); falls back to a pure-
    Python Zhang-Suen implementation if `ximgproc` isn't available.
    """
    try:
        import cv2.ximgproc as xip
        return xip.thinning(mask, thinningType=xip.THINNING_GUOHALL)
    except (ImportError, AttributeError):
        return _zhang_suen_thinning(mask)


def _zhang_suen_thinning(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen iterative thinning. Pure NumPy, slower than OpenCV's C++."""
    img = (mask > 0).astype(np.uint8)
    prev = np.zeros_like(img)
    while True:
        # Subiteration 1
        marker = np.zeros_like(img)
        h, w = img.shape
        # Build neighbor stack (P2..P9 in Zhang-Suen notation)
        # Using slicing for speed.
        p2 = np.zeros_like(img); p2[1:, :] = img[:-1, :]
        p3 = np.zeros_like(img); p3[1:, :-1] = img[:-1, 1:]
        p4 = np.zeros_like(img); p4[:, :-1] = img[:, 1:]
        p5 = np.zeros_like(img); p5[:-1, :-1] = img[1:, 1:]
        p6 = np.zeros_like(img); p6[:-1, :] = img[1:, :]
        p7 = np.zeros_like(img); p7[:-1, 1:] = img[1:, :-1]
        p8 = np.zeros_like(img); p8[:, 1:] = img[:, :-1]
        p9 = np.zeros_like(img); p9[1:, 1:] = img[:-1, :-1]
        b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
        # Transitions p2->p3->...->p9->p2 in cyclic order
        a = ((p2 == 0) & (p3 == 1)).astype(np.uint8)
        a += ((p3 == 0) & (p4 == 1)).astype(np.uint8)
        a += ((p4 == 0) & (p5 == 1)).astype(np.uint8)
        a += ((p5 == 0) & (p6 == 1)).astype(np.uint8)
        a += ((p6 == 0) & (p7 == 1)).astype(np.uint8)
        a += ((p7 == 0) & (p8 == 1)).astype(np.uint8)
        a += ((p8 == 0) & (p9 == 1)).astype(np.uint8)
        a += ((p9 == 0) & (p2 == 1)).astype(np.uint8)
        cond = (
            (img == 1) & (b >= 2) & (b <= 6) & (a == 1)
            & (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
        )
        marker[cond] = 1
        img[marker == 1] = 0
        # Subiteration 2 (similar but P2*P4*P8=0 and P2*P6*P8=0)
        marker2 = np.zeros_like(img)
        p2 = np.zeros_like(img); p2[1:, :] = img[:-1, :]
        p3 = np.zeros_like(img); p3[1:, :-1] = img[:-1, 1:]
        p4 = np.zeros_like(img); p4[:, :-1] = img[:, 1:]
        p5 = np.zeros_like(img); p5[:-1, :-1] = img[1:, 1:]
        p6 = np.zeros_like(img); p6[:-1, :] = img[1:, :]
        p7 = np.zeros_like(img); p7[:-1, 1:] = img[1:, :-1]
        p8 = np.zeros_like(img); p8[:, 1:] = img[:, :-1]
        p9 = np.zeros_like(img); p9[1:, 1:] = img[:-1, :-1]
        b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
        a = ((p2 == 0) & (p3 == 1)).astype(np.uint8)
        a += ((p3 == 0) & (p4 == 1)).astype(np.uint8)
        a += ((p4 == 0) & (p5 == 1)).astype(np.uint8)
        a += ((p5 == 0) & (p6 == 1)).astype(np.uint8)
        a += ((p6 == 0) & (p7 == 1)).astype(np.uint8)
        a += ((p7 == 0) & (p8 == 1)).astype(np.uint8)
        a += ((p8 == 0) & (p9 == 1)).astype(np.uint8)
        a += ((p9 == 0) & (p2 == 1)).astype(np.uint8)
        cond = (
            (img == 1) & (b >= 2) & (b <= 6) & (a == 1)
            & (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
        )
        marker2[cond] = 1
        img[marker2 == 1] = 0
        if np.array_equal(img, prev):
            break
        prev = img.copy()
    return (img * 255).astype(np.uint8)


def _trace_skeleton_polylines(skel: np.ndarray, min_length_px: int = 30) -> list:
    """Walk a skeletonized binary mask into polylines.

    Returns list of polylines, each a list of (col, row) integer tuples.
    Points where degree != 2 (endpoints, junctions) are treated as polyline
    boundaries — branches at junctions become separate polylines.

    Drops polylines shorter than min_length_px (Manhattan length is fine
    for filtering noise; we don't need true Euclidean length here).
    """
    # Build set of white-pixel coords.
    ys, xs = np.where(skel > 0)
    if len(xs) == 0:
        return []
    pixels = set(zip(xs.tolist(), ys.tolist()))
    h, w = skel.shape

    def neighbors(p):
        x, y = p
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                np_ = (x + dx, y + dy)
                if np_ in pixels:
                    out.append(np_)
        return out

    def degree(p):
        return len(neighbors(p))

    # Endpoints (degree 1) and junctions (degree ≥ 3) are walk boundaries.
    boundaries = {p for p in pixels if degree(p) != 2}

    visited_edges = set()  # set of frozenset({a, b}) edges already walked
    polylines = []

    def walk_from(start, first_step):
        path = [start, first_step]
        visited_edges.add(frozenset({start, first_step}))
        prev, curr = start, first_step
        while curr not in boundaries:
            nbrs = [n for n in neighbors(curr) if n != prev]
            if not nbrs:
                break
            nxt = nbrs[0]
            if frozenset({curr, nxt}) in visited_edges:
                break
            visited_edges.add(frozenset({curr, nxt}))
            path.append(nxt)
            prev, curr = curr, nxt
        return path

    # Walk from every boundary along each unvisited neighbor.
    for b in list(boundaries):
        for n in neighbors(b):
            if frozenset({b, n}) in visited_edges:
                continue
            path = walk_from(b, n)
            if len(path) >= min_length_px:
                polylines.append(path)

    # Pixels in degree-2 chains with no boundary (closed loops) — pick any
    # remaining pixel and walk both directions.
    remaining = pixels - {pt for path in polylines for pt in path}
    for p in list(remaining):
        if any(frozenset({p, n}) in visited_edges for n in neighbors(p)):
            continue
        nbrs = neighbors(p)
        if not nbrs:
            continue
        path = walk_from(p, nbrs[0])
        if len(path) >= min_length_px:
            polylines.append(path)

    return polylines


import yaml
from PIL import Image

# Reuse existing infrastructure.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jeffs_extractor import walk_kmz, build_mosaic


def _polyline_pixel_to_gps(polyline_px, mosaic_bounds, mosaic_shape):
    """Project a list of (col, row) pixel coords through the mosaic transform."""
    n, s, e, w = mosaic_bounds
    h, mosaic_w = mosaic_shape[:2]
    out = []
    for col, row in polyline_px:
        lon = w + (col / mosaic_w) * (e - w)
        lat = n - (row / h) * (n - s)
        out.append([lat, lon])
    return out


def _polyline_length_km(polyline_gps):
    """Sum haversine distances along a GPS polyline."""
    R = 6371.0
    total = 0.0
    for i in range(1, len(polyline_gps)):
        a, b = polyline_gps[i - 1], polyline_gps[i]
        import math
        p1 = math.radians(a[0])
        p2 = math.radians(b[0])
        dp = math.radians(b[0] - a[0])
        dl = math.radians(b[1] - a[1])
        h = (math.sin(dp / 2) ** 2
             + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
        total += R * 2 * math.asin(math.sqrt(h))
    return total


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


def _extract_paths_from_mosaic(mosaic_bgr: np.ndarray, palette: dict,
                               skip_text_removal: bool = False) -> list:
    """Run the full HSV → morphology → skeletonize → trace → simplify pipeline.
    Returns list of (col, row) pixel polylines.
    """
    if not skip_text_removal:
        mosaic_bgr = _remove_text(mosaic_bgr)
    hsv = cv2.cvtColor(mosaic_bgr, cv2.COLOR_BGR2HSV)
    low = np.array([palette["hue"][0], palette["saturation"][0], palette["value"][0]])
    high = np.array([palette["hue"][1], palette["saturation"][1], palette["value"][1]])
    mask = cv2.inRange(hsv, low, high)

    open_px = int(palette.get("open_kernel_px", 0) or 0)
    if open_px > 0:
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (open_px, open_px)),
        )
    close_px = int(palette.get("close_kernel_px", 0) or 0)
    if close_px > 0:
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (close_px, close_px)),
        )

    skel = _skeletonize(mask)
    min_len = int(palette.get("min_length_px", 30))
    polylines_px = _trace_skeleton_polylines(skel, min_length_px=min_len)
    eps = float(palette.get("simplify_eps_px", 3))
    simplified = []
    for poly in polylines_px:
        arr = np.array([[[p[0], p[1]]] for p in poly], dtype=np.int32)
        approx = cv2.approxPolyDP(arr, eps, closed=False)
        simplified.append([(int(pt[0][0]), int(pt[0][1])) for pt in approx])
    return simplified


def _write_review_html(out_path: Path, paths: list) -> None:
    """Minimal review listing: counts + per-path centroid + length."""
    rows = "".join(
        f"<tr><td>{p['id']}</td><td>{p['length_km']:.2f}</td>"
        f"<td>{p['points'][0][0]:.4f}, {p['points'][0][1]:.4f}</td>"
        f"<td>{len(p['points'])}</td></tr>"
        for p in paths
    )
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Jeff's path extractor review</title>"
        "<style>body{font-family:sans-serif;max-width:900px;margin:2rem auto;"
        "padding:1rem}table{border-collapse:collapse;width:100%}"
        "th,td{border-bottom:1px solid #ddd;padding:0.4rem 0.6rem;text-align:left}"
        "th{background:#f0f4ee}</style></head><body>"
        f"<h1>Yellow paths ({len(paths)})</h1>"
        "<table><thead><tr><th>id</th><th>length_km</th>"
        "<th>first GPS</th><th>vertices</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></body></html>"
    )
    out_path.write_text(html)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kmz", help="Path to Jeff's KMZ")
    parser.add_argument("--bbox", required=True,
                        help="south,west,north,east")
    parser.add_argument("--paths-palette", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--zoom", type=int, default=7)
    parser.add_argument("--review-html")
    parser.add_argument("--skip-text-removal", action="store_true",
                        help="Skip the OCR text-removal pre-pass (debug / "
                             "use when tesseract is unavailable).")
    args = parser.parse_args(argv)

    bbox = tuple(float(x) for x in args.bbox.split(","))
    if len(bbox) != 4:
        print("--bbox needs 4 comma-separated values", file=sys.stderr)
        return 2

    palette = yaml.safe_load(Path(args.paths_palette).read_text()) or {}

    import shutil
    import tempfile
    extract_dir = Path(tempfile.mkdtemp(prefix="jeffs_paths_"))
    try:
        tiles = list(walk_kmz(Path(args.kmz), bbox=bbox,
                              zoom_level=args.zoom, extract_dir=extract_dir))
        if not tiles:
            print(f"No tiles in bbox {bbox} at zoom {args.zoom}",
                  file=sys.stderr)
            return 3
        print(f"  walking KMZ at zoom {args.zoom}: {len(tiles)} tiles",
              file=sys.stderr)
        mosaic, mosaic_bounds = build_mosaic(tiles)
        polylines_px = _extract_paths_from_mosaic(
            mosaic, palette, skip_text_removal=args.skip_text_removal)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    paths = []
    for i, poly_px in enumerate(polylines_px):
        gps = _polyline_pixel_to_gps(poly_px, mosaic_bounds, mosaic.shape)
        paths.append({
            "id": i,
            "points": gps,
            "length_km": round(_polyline_length_km(gps), 3),
        })

    out_data = {
        "paths": paths,
        "_meta": {
            "source_kmz": Path(args.kmz).name,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "zoom": args.zoom,
            "bbox": list(bbox),
            "count": len(paths),
        },
    }
    Path(args.out).write_text(json.dumps(out_data, indent=2))
    print(f"Wrote {args.out} with {len(paths)} polylines", file=sys.stderr)

    if args.review_html:
        _write_review_html(Path(args.review_html), paths)
        print(f"Wrote {args.review_html}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
