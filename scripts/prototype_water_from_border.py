"""
Prototype: derive water regions from Jeff's darker-blue shoreline border.

Pipeline:
  1. K-means color quantization to N classes (Inkscape Trace Bitmap analogue).
  2. Identify the "shoreline" class — darker blue at the water boundary.
  3. Close small gaps in the border, find contours, flood-fill enclosed area.
  4. Output a clean water mask + cleaned basemap (water + land + paths kept,
     text/icons dropped).

Output: a 4-panel JPG: original | k-means quantized | water mask | basemap.

Usage:
    python3 scripts/prototype_water_from_border.py
    python3 scripts/prototype_water_from_border.py --bbox 46.005,-81.42,46.04,-81.38
    python3 scripts/prototype_water_from_border.py --n-colors 8
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

KMZ_PATH = (
    REPO_ROOT
    / "Maps by Jeff - Full French River and Killarney Paddling Map v4.0 - Google Earth.kmz"
)

DEFAULT_BBOX = (46.005, -81.42, 46.04, -81.38)


def kmeans_quantize(bgr: np.ndarray, n_colors: int = 6) -> tuple:
    """K-means color quantization. Returns (quantized_bgr, label_map, palette).

    palette: shape (n_colors, 3), BGR order, sorted so the labels are stable.
    label_map: shape (h, w), each pixel = palette index.
    """
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


def _bgr_to_hsv_one(bgr_color: np.ndarray) -> np.ndarray:
    """Convert a single BGR pixel to HSV (returns shape (3,))."""
    return cv2.cvtColor(bgr_color.reshape(1, 1, 3), cv2.COLOR_BGR2HSV)[0, 0]


def find_water_classes(palette: np.ndarray) -> tuple:
    """From the k-means palette, identify (water_interior_idx, shoreline_idx).

    Heuristic: water interior is the bluest-with-medium-V class; shoreline is
    a slightly darker blue (lower V) with similar hue. Returns (interior_idx,
    shoreline_idx); either can be None if the heuristic fails.
    """
    n = palette.shape[0]
    # Score each class by "blueness": HSV hue near 100 + reasonable S.
    scores = []
    for i in range(n):
        h, s, v = _bgr_to_hsv_one(palette[i])
        is_blue = 80 <= h <= 130 and s >= 25
        scores.append((i, h, s, v, is_blue))
    blues = [s for s in scores if s[4]]
    if not blues:
        return None, None
    # Sort by V (brightness): bright = interior water, dark = shoreline.
    blues.sort(key=lambda x: x[3], reverse=True)
    interior = blues[0][0]
    shoreline = blues[-1][0] if len(blues) > 1 else None
    if shoreline == interior:
        shoreline = None
    return interior, shoreline


def water_mask_from_border(label_map: np.ndarray, shoreline_idx: int,
                           interior_idx: int = None,
                           interior_pct_min: float = 0.55,
                           min_polygon_area_px: int = 800,
                           close_kernel_px: int = 3,
                           erode_px: int = 0) -> tuple:
    """Build trusted water polygons by combining shoreline + interior classes.

    Tunables:
      close_kernel_px: kernel size for morph-close that bridges small gaps
        in the shoreline+interior mask. LARGER = catches more lakes but
        balloons polygons into nearby text/icons. SMALLER = stricter, may
        miss lakes whose shoreline has gaps.
      interior_pct_min: minimum fraction of a contour-filled region that
        must be the interior-water class. HIGHER = stricter validation.
      erode_px: pixels to erode trusted polygons after fill — pulls
        boundaries inward, away from text halos that touched the polygon.
      min_polygon_area_px: drop tiny noise contours below this area.
    """
    h, w = label_map.shape
    interior_full = (label_map == interior_idx).astype(np.uint8) * 255 \
        if interior_idx is not None else np.zeros((h, w), dtype=np.uint8)
    shoreline_full = (label_map == shoreline_idx).astype(np.uint8) * 255

    water_y = cv2.bitwise_or(shoreline_full, interior_full)
    if close_kernel_px > 0:
        closed = cv2.morphologyEx(
            water_y, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_RECT, (close_kernel_px, close_kernel_px)),
        )
    else:
        closed = water_y
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
    trusted = np.zeros((h, w), dtype=np.uint8)
    for c in contours:
        if cv2.contourArea(c) < min_polygon_area_px:
            continue
        test = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(test, [c], -1, 255, thickness=cv2.FILLED)
        inside_n = int(np.sum(test > 0))
        if inside_n == 0:
            continue
        if interior_idx is not None:
            inside_water_n = int(np.sum((test > 0) & (interior_full > 0)))
            if (inside_water_n / inside_n) < interior_pct_min:
                continue
        cv2.drawContours(trusted, [c], -1, 255, thickness=cv2.FILLED)

    # Erode polygons inward to back away from any text halos that touched
    # the polygon boundary.
    if erode_px > 0:
        trusted = cv2.erode(
            trusted,
            cv2.getStructuringElement(
                cv2.MORPH_RECT, (2 * erode_px + 1, 2 * erode_px + 1)),
        )

    interior_outside = cv2.bitwise_and(
        interior_full, cv2.bitwise_not(trusted))
    return trusted, interior_outside


def detect_text_via_ocr(bgr: np.ndarray, conf_min: int = 25,
                        pad_px: int = 4) -> np.ndarray:
    """OCR-based text detection (psm 11 sparse only — psm 6 was over-aggressive)."""
    try:
        import pytesseract
    except ImportError:
        return np.zeros(bgr.shape[:2], dtype=np.uint8)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    data = pytesseract.image_to_data(
        gray, config="--psm 11",
        output_type=pytesseract.Output.DICT,
    )
    mask = np.zeros(bgr.shape[:2], dtype=np.uint8)
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
        w_box = data["width"][i] + 2 * pad_px
        h_box = data["height"][i] + 2 * pad_px
        cv2.rectangle(mask, (x, y), (x + w_box, y + h_box), 255, -1)
    return mask


def build_clean_basemap(bgr: np.ndarray, label_map: np.ndarray,
                        palette: np.ndarray,
                        water_mask: np.ndarray,
                        text_mask: np.ndarray) -> np.ndarray:
    """Reconstruct a clean basemap.

    Three regions:
      - Yellow + red pixels: PRESERVE (paths + trails).
      - Inside water_mask (and not preserved): paint interior-water color.
      - Text mask outside water_mask: paint dominant-land color.

    No cv2.inpaint — just direct color replacement, so no blur.
    """
    h, w = bgr.shape[:2]
    interior_idx, _ = find_water_classes(palette)
    interior_color = palette[interior_idx] if interior_idx is not None \
        else np.array([220, 200, 150], dtype=np.uint8)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([20, 100, 150]),
                         np.array([40, 255, 255]))
    red1 = cv2.inRange(hsv, np.array([0, 100, 80]),
                       np.array([10, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([170, 100, 80]),
                       np.array([180, 255, 255]))
    preserve = cv2.bitwise_or(yellow, cv2.bitwise_or(red1, red2))

    out = bgr.copy()
    # Water: paint uniformly, except preserved colors.
    paint_water = (water_mask > 0) & (preserve == 0)
    out[paint_water] = interior_color

    # Land color = dominant non-water non-dark class.
    palette_hsv = cv2.cvtColor(palette.reshape(-1, 1, 3),
                               cv2.COLOR_BGR2HSV).reshape(-1, 3)
    dark_idx = int(np.argmin(palette_hsv[:, 2]))
    land_candidates = [
        i for i in range(palette.shape[0])
        if i != interior_idx and i != dark_idx
    ]
    land_color = np.array([200, 220, 200], dtype=np.uint8)
    if land_candidates:
        counts = [int(np.sum(label_map == i)) for i in land_candidates]
        land_idx = land_candidates[int(np.argmax(counts))]
        land_color = palette[land_idx]

    # Text outside water → paint with land color (where label sits on land).
    text_on_land = (text_mask > 0) & (water_mask == 0) & (preserve == 0)
    out[text_on_land] = land_color
    # Text on water → paint water color (where label sits on water but the
    # OCR box extended slightly past the lake polygon edge).
    text_on_water = (text_mask > 0) & (water_mask > 0) & (preserve == 0)
    out[text_on_water] = interior_color
    return out


def panel(images: list, labels: list) -> np.ndarray:
    """2x2 grid layout (assumes 4 images of equal size)."""
    if len(images) != 4:
        # Fallback: horizontal strip.
        h = max(im.shape[0] for im in images)
        w = sum(im.shape[1] for im in images)
        out = np.full((h + 30, w, 3), 255, dtype=np.uint8)
        x = 0
        for im, label in zip(images, labels):
            if im.ndim == 2:
                im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
            out[30:30 + im.shape[0], x:x + im.shape[1]] = im
            cv2.putText(out, label, (x + 10, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
            x += im.shape[1]
        return out
    panel_h, panel_w = images[0].shape[:2]
    label_h = 30
    out = np.full((2 * (panel_h + label_h), 2 * panel_w, 3), 255, dtype=np.uint8)
    for idx, (im, label) in enumerate(zip(images, labels)):
        if im.ndim == 2:
            im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        row = idx // 2
        col = idx % 2
        y0 = row * (panel_h + label_h)
        x0 = col * panel_w
        cv2.putText(out, label, (x0 + 10, y0 + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
        out[y0 + label_h:y0 + label_h + panel_h, x0:x0 + panel_w] = im
    return out


def render_palette_swatch(palette: np.ndarray, label_map: np.ndarray,
                          interior_idx, shoreline_idx,
                          width_px: int = 800) -> np.ndarray:
    """Draw a palette legend with class indices, counts, and roles."""
    n = palette.shape[0]
    sw_h = 60
    img = np.full((n * sw_h, width_px, 3), 255, dtype=np.uint8)
    total = label_map.size
    for i in range(n):
        y0 = i * sw_h
        cv2.rectangle(img, (0, y0), (200, y0 + sw_h),
                      tuple(int(c) for c in palette[i]), -1)
        count = int(np.sum(label_map == i))
        pct = 100 * count / total
        h, s, v = _bgr_to_hsv_one(palette[i])
        role = ""
        if i == interior_idx:
            role = " ← INTERIOR water"
        elif i == shoreline_idx:
            role = " ← SHORELINE"
        text = f"#{i}  HSV=({h},{s},{v})  {pct:.1f}%{role}"
        cv2.putText(img, text, (210, y0 + 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
    return img


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", default=",".join(str(x) for x in DEFAULT_BBOX))
    parser.add_argument("--zoom", type=int, default=7)
    parser.add_argument("--n-colors", type=int, default=8,
                        help="K-means classes (default 8). Higher = more "
                             "fine-grained semantic separation but slower.")
    parser.add_argument("--close-kernel", type=int, default=3,
                        help="Morph-close kernel for shoreline+interior "
                             "combination (default 3). LARGER = bridges "
                             "more shoreline gaps but balloons polygons "
                             "into nearby text. SMALLER = stricter.")
    parser.add_argument("--interior-pct-min", type=float, default=0.55,
                        help="Min fraction of polygon that must be interior-"
                             "water class (default 0.55). HIGHER = stricter "
                             "validation, drops more text-block FPs.")
    parser.add_argument("--erode-px", type=int, default=3,
                        help="Erode trusted polygons inward by N px after "
                             "fill (default 3). Pulls boundaries away from "
                             "text halos.")
    parser.add_argument("--min-polygon-area", type=int, default=800,
                        help="Drop polygons smaller than this many px "
                             "(default 800).")
    parser.add_argument("--yellow-water-pct", type=float, default=0.40,
                        help="Min fraction of yellow component crossing "
                             "trusted water polygons to count as a paddle "
                             "path (default 0.40).")
    parser.add_argument("--ocr-conf", type=int, default=25,
                        help="Min Tesseract confidence (default 25).")
    parser.add_argument("--out", default="water_border_prototype.jpg")
    args = parser.parse_args(argv)
    print(f"  params: n_colors={args.n_colors} close_kernel={args.close_kernel} "
          f"interior_pct_min={args.interior_pct_min} erode_px={args.erode_px} "
          f"min_poly={args.min_polygon_area} yellow_pct={args.yellow_water_pct} "
          f"ocr_conf={args.ocr_conf}", file=sys.stderr)

    bbox = tuple(float(x) for x in args.bbox.split(","))

    from overlay_osm_jeffs import _build_raster_mosaic
    raster_jpg = REPO_ROOT / "water_border_prototype_raster.jpg"
    s, w, n, e = _build_raster_mosaic(KMZ_PATH, bbox, args.zoom, raster_jpg)
    print(f"  mosaic GPS bounds: S{s} W{w} N{n} E{e}", file=sys.stderr)

    bgr = cv2.imread(str(raster_jpg))
    print(f"  size: {bgr.shape[1]}x{bgr.shape[0]}", file=sys.stderr)

    quantized, label_map, palette = kmeans_quantize(bgr, args.n_colors)
    interior_idx, shoreline_idx = find_water_classes(palette)
    print(f"  k-means: {args.n_colors} colors. "
          f"interior={interior_idx}, shoreline={shoreline_idx}",
          file=sys.stderr)
    if interior_idx is None and shoreline_idx is None:
        print("  WARN: no blue classes found", file=sys.stderr)

    trusted = np.zeros(bgr.shape[:2], dtype=np.uint8)
    interior_outside = np.zeros(bgr.shape[:2], dtype=np.uint8)
    if shoreline_idx is not None:
        # Get un-eroded trusted polygons for yellow validation (paths often
        # run near shores). Erode happens separately for the final output.
        trusted_full, interior_outside = water_mask_from_border(
            label_map, shoreline_idx, interior_idx,
            interior_pct_min=args.interior_pct_min,
            min_polygon_area_px=args.min_polygon_area,
            close_kernel_px=args.close_kernel,
            erode_px=0,  # done below if requested
        )
        if args.erode_px > 0:
            trusted = cv2.erode(
                trusted_full,
                cv2.getStructuringElement(
                    cv2.MORPH_RECT,
                    (2 * args.erode_px + 1, 2 * args.erode_px + 1)),
            )
        else:
            trusted = trusted_full
    else:
        trusted_full = trusted = np.zeros(bgr.shape[:2], dtype=np.uint8)
        if interior_idx is not None:
            interior_outside = (label_map == interior_idx).astype(np.uint8) * 255
    print(f"  trusted polygons: {int(100 * (trusted > 0).mean()):.1f}% | "
          f"interior outside: {int(100 * (interior_outside > 0).mean()):.1f}%",
          file=sys.stderr)

    text_mask = detect_text_via_ocr(bgr, conf_min=args.ocr_conf)
    print(f"  text mask: {int((text_mask > 0).sum())} px "
          f"({100 * (text_mask > 0).mean():.1f}%)", file=sys.stderr)

    # Refine water mask:
    # - trusted polygons (validated closed contours) — solid, no text holes
    # - interior-class pixels OUTSIDE trusted polygons — subtract OCR text
    #   (drops blue-text halos on land), keep only large connected components
    # - yellow paths that mostly cross water — buffered, added back
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    yellow_paths = cv2.inRange(hsv, np.array([20, 100, 150]),
                               np.array([40, 255, 255]))

    # Identify "large water polygons" from the un-eroded trusted mask
    # (so paths along shores still count as crossing water).
    base_n, base_lbl, base_st, _ = cv2.connectedComponentsWithStats(
        trusted_full, connectivity=8)
    large_water = np.zeros_like(trusted_full)
    LARGE_LAKE_PX = 1500
    for i in range(1, base_n):
        if base_st[i, cv2.CC_STAT_AREA] >= LARGE_LAKE_PX:
            large_water[base_lbl == i] = 255
    large_water_buf = cv2.dilate(
        large_water,
        cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))

    # Connected components of yellow (thick stroke, no skeletonization —
    # short components get path-typical area-to-bbox-aspect filtering).
    n_y, lbl_y, st_y, _ = cv2.connectedComponentsWithStats(
        yellow_paths, connectivity=8)
    yellow_water_components = np.zeros_like(yellow_paths)
    YELLOW_THROUGH_WATER_PCT = args.yellow_water_pct
    YELLOW_MIN_AREA = 40
    kept = 0
    pcts = []
    for i in range(1, n_y):
        area = st_y[i, cv2.CC_STAT_AREA]
        if area < YELLOW_MIN_AREA:
            continue
        comp = (lbl_y == i)
        in_water = int(np.sum(comp & (large_water_buf > 0)))
        pct = in_water / area
        pcts.append(pct)
        if pct >= YELLOW_THROUGH_WATER_PCT:
            yellow_water_components[comp] = 255
            kept += 1
    if pcts:
        pcts.sort(reverse=True)
        print(f"  yellow components: {len(pcts)} sized, {kept} cross water "
              f">= {int(100*YELLOW_THROUGH_WATER_PCT)}% "
              f"(top pcts: {[round(p,2) for p in pcts[:8]]})",
              file=sys.stderr)
    else:
        print(f"  yellow components: 0 sized", file=sys.stderr)
    yellow_buf = cv2.dilate(yellow_water_components,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))

    # Layer the mask:
    # 1. Trusted polygons (no text subtraction — text inside a closed
    #    shoreline is just a label OVER water, the polygon stays solid)
    # 2. Interior-outside-polygons MINUS text mask (text-halo extensions
    #    on land get pruned). Keep only sufficiently large connected blobs.
    interior_outside_clean = cv2.bitwise_and(
        interior_outside, cv2.bitwise_not(text_mask))
    n_io, lbl_io, st_io, _ = cv2.connectedComponentsWithStats(
        interior_outside_clean, connectivity=8)
    interior_outside_keep = np.zeros_like(interior_outside_clean)
    for i in range(1, n_io):
        if st_io[i, cv2.CC_STAT_AREA] >= 800:
            interior_outside_keep[lbl_io == i] = 255

    water_refined = cv2.bitwise_or(trusted, interior_outside_keep)
    water_refined = cv2.bitwise_or(water_refined, yellow_buf)
    # Final cleanup: drop tiny disconnected blobs.
    n, lbl, st, _ = cv2.connectedComponentsWithStats(water_refined, connectivity=8)
    keep = np.zeros_like(water_refined)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 600:
            keep[lbl == i] = 255
    water_refined = keep
    print(f"  refined water mask: {int((water_refined > 0).sum())} px "
          f"({100 * (water_refined > 0).mean():.1f}%)", file=sys.stderr)

    # Trace contours of the refined water mask — these are the derived
    # water polygons we'd hand to the route engine.
    derived_contours, _ = cv2.findContours(
        water_refined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_viz = bgr.copy()
    cv2.drawContours(contour_viz, derived_contours, -1, (0, 255, 255), 2)
    print(f"  derived water polygons: {len(derived_contours)}", file=sys.stderr)

    basemap = build_clean_basemap(bgr, label_map, palette, water_refined, text_mask)

    # Visualize refined water mask.
    water_viz = bgr.copy()
    # Translucent overlay: 50% blue tint where water.
    blue_layer = np.zeros_like(bgr)
    blue_layer[water_refined > 0] = (255, 80, 0)
    water_viz = cv2.addWeighted(water_viz, 0.55, blue_layer, 0.45, 0)
    water_viz[water_refined == 0] = bgr[water_refined == 0]

    # Palette swatch.
    swatch = render_palette_swatch(
        palette, label_map, interior_idx, shoreline_idx)

    composite = panel(
        [bgr, water_viz, contour_viz, basemap],
        ["original",
         f"refined water mask ({int(100*(water_refined>0).mean())}%)",
         f"derived polygons ({len(derived_contours)} contours)",
         "clean basemap (sideshow)"],
    )
    out_path = REPO_ROOT / args.out
    cv2.imwrite(str(out_path), composite, [cv2.IMWRITE_JPEG_QUALITY, 88])
    swatch_path = out_path.with_name(out_path.stem + "_palette.jpg")
    cv2.imwrite(str(swatch_path), swatch, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"Wrote {out_path}", file=sys.stderr)
    print(f"Wrote {swatch_path}", file=sys.stderr)

    html_path = out_path.with_suffix(".html")
    html_path.write_text(
        "<!DOCTYPE html><html><head><title>Water-from-border prototype</title>"
        "<style>body{margin:0;padding:1rem;font-family:sans-serif;"
        "background:#222;color:#eee}img{max-width:100%;display:block;"
        "margin-top:0.6rem}h1{font-size:1.1rem;margin:0}.meta{color:#aaa;"
        "font-size:0.85rem}</style></head>"
        f"<body><h1>Water-from-border prototype — bbox {bbox}, "
        f"N={args.n_colors}</h1>"
        f"<div class='meta'>{bgr.shape[1]}x{bgr.shape[0]} px, "
        f"interior_idx={interior_idx}, shoreline_idx={shoreline_idx}</div>"
        f"<img src='{out_path.name}' alt='4-panel'/>"
        f"<h2 style='margin-top:1rem'>Palette</h2>"
        f"<img src='{swatch_path.name}' alt='palette' style='max-width:800px'/>"
        "</body></html>"
    )
    print(f"Wrote {html_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
