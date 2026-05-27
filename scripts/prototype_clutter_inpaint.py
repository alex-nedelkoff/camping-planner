"""
Prototype v2: per-color clutter detection on Jeff's KMZ raster.

Strategy:
  1. Per-color candidate masks: black text, red icons/labels, yellow labels
     (path-aware — long thin yellow stays).
  2. Shape filter on each candidate: keep components that look like
     text/icons (small area, consistent stroke width via distance transform).
  3. Halo dilation: extend the text mask to include the surrounding halo.
  4. Inpaint with cv2.inpaint (TELEA).

Output: a 4-panel JPG showing original | per-color candidates |
text/icon mask | inpainted.

Usage:
    python3 scripts/prototype_clutter_inpaint.py
    python3 scripts/prototype_clutter_inpaint.py --bbox 46.005,-81.42,46.04,-81.38
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

# George Lake corridor — known to have lake-name labels + campsite numbers
# overlapping water from the audit results.
DEFAULT_BBOX = (46.005, -81.42, 46.04, -81.38)


def color_mask_black(bgr: np.ndarray) -> np.ndarray:
    """Pixels that are dark gray to black (text + outlines)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 80, 90]))


def color_mask_red(bgr: np.ndarray) -> np.ndarray:
    """Red pixels (icons, info markers, some labels)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lo1 = cv2.inRange(hsv, np.array([0, 100, 80]), np.array([10, 255, 255]))
    lo2 = cv2.inRange(hsv, np.array([170, 100, 80]), np.array([180, 255, 255]))
    return cv2.bitwise_or(lo1, lo2)


def color_mask_yellow(bgr: np.ndarray) -> np.ndarray:
    """Yellow pixels (path color AND yellow text — disambiguated by shape later)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([22, 100, 150]), np.array([38, 255, 255]))


def color_mask_blue_text(bgr: np.ndarray) -> np.ndarray:
    """Bright/saturated cyan-blue (lake-name labels), excluding water tones.

    Water in Jeff's map is a softer pale blue (low-mid saturation). Label
    text is high-saturation cyan/blue. Hue range 90-110, S>120, V>150.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([90, 120, 150]), np.array([115, 255, 255]))


def text_shape_filter(mask: np.ndarray,
                      min_area: int = 6,
                      max_area: int = 600,
                      max_dim: int = 35,
                      stroke_width_max: float = 4.5,
                      stroke_width_min: float = 0.8) -> np.ndarray:
    """Keep connected components that look like text glyphs or small icons.

    Heuristics:
    - Bounding box: small (max dim ≤ max_dim).
    - Area in [min_area, max_area].
    - Stroke width: distance transform's mean-on-mask should be small + consistent
      (text has thin strokes, ~2-3 px). Fat blobs (filled lake polygons,
      buildings) have larger mean distances.
    """
    if mask.sum() == 0:
        return mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = np.zeros_like(mask)
    if n <= 1:
        return out
    # Distance transform of the binary mask.
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        if area < min_area or area > max_area:
            continue
        if max(w, h) > max_dim:
            continue
        comp_dist = dist[labels == i]
        mean_sw = float(comp_dist.mean()) if comp_dist.size else 0.0
        if mean_sw > stroke_width_max:
            continue  # too thick — probably a filled blob, not a glyph
        if mean_sw < stroke_width_min:
            continue  # too thin — probably noise/single pixel
        out[labels == i] = 255
    return out


def text_cluster_filter(mask: np.ndarray, neighbor_radius: int = 12,
                        min_neighbors: int = 2) -> np.ndarray:
    """Keep only components that have other components nearby.

    Words/labels are clusters of glyphs within ~12 px. Standalone tiny dark
    blobs are usually noise.
    """
    if mask.sum() == 0:
        return mask
    # Dilate then count neighbours via labeling.
    dilated = cv2.dilate(mask, np.ones((neighbor_radius, neighbor_radius),
                                        np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = np.zeros_like(mask)
    # Number of components in each dilated blob.
    n_d, labels_d, _, _ = cv2.connectedComponentsWithStats(dilated, connectivity=8)
    counts_per_dlabel = np.zeros(n_d, dtype=np.int32)
    # For each component i (i>=1), find its dilated label and bump count.
    for i in range(1, n):
        cx = int(stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] // 2)
        cy = int(stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] // 2)
        d_lbl = labels_d[cy, cx]
        if d_lbl > 0:
            counts_per_dlabel[d_lbl] += 1
    # Keep components whose dilated cluster has >= min_neighbors components.
    for i in range(1, n):
        cx = int(stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] // 2)
        cy = int(stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] // 2)
        d_lbl = labels_d[cy, cx]
        if d_lbl > 0 and counts_per_dlabel[d_lbl] >= min_neighbors:
            out[labels == i] = 255
    return out


def detect_filled_rect_labels(bgr: np.ndarray,
                              min_area: int = 800,
                              aspect_min: float = 1.3,
                              aspect_max: float = 10.0,
                              extent_min: float = 0.65) -> np.ndarray:
    """Filled dark-box labels (e.g., 'George Lake Campground', 'Liftover').

    Detect contours of a dark threshold; keep ones that are big, rectangular
    (extent = area / bbox_area > 0.65), and have a long-thin aspect ratio.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)
    # Close small gaps so "boxed label" connects through the white text.
    binary = cv2.morphologyEx(
        binary, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3)),
    )
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(gray)
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if h <= 0 or w <= 0:
            continue
        aspect = w / h
        if not (aspect_min <= aspect <= aspect_max):
            continue
        bbox_area = w * h
        extent = area / bbox_area
        if extent < extent_min:
            continue
        # Fill the bbox so we capture both the dark border AND inner text.
        cv2.rectangle(out, (x, y), (x + w, y + h), 255, -1)
    return out


def detect_text_paragraph_blocks(bgr: np.ndarray,
                                 min_area: int = 4000,
                                 fill_max: float = 0.35) -> np.ndarray:
    """Multi-line dark-on-light text paragraphs (description blocks at corners).

    Strategy: heavily horizontally dilate the dark-text mask so consecutive
    glyphs and lines merge into a paragraph blob, then keep large blobs with
    moderate fill (not solid filled rectangles, not sparse).
    """
    blk = color_mask_black(bgr)
    # Tight shape filter on glyphs first.
    glyphs = text_shape_filter(blk, max_dim=60)
    # Horizontal-dilate aggressively so words within a line merge, plus
    # vertical dilate so lines within a paragraph merge.
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 9))
    merged = cv2.dilate(glyphs, h_kernel, iterations=1)
    merged = cv2.dilate(merged, v_kernel, iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    out = np.zeros_like(merged)
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area:
            continue
        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        bbox_area = w * h
        fill = area / bbox_area
        # Paragraphs have moderate fill — not super dense (filled rectangles)
        # and not extremely sparse (random scattered text).
        if fill > fill_max:
            continue
        cv2.rectangle(out, (x, y), (x + w, y + h), 255, -1)
    return out


def detect_non_water_inside_lakes(bgr: np.ndarray,
                                  lake_polygons_px: list,
                                  erode_px: int = 4,
                                  island_min_area: int = 600) -> np.ndarray:
    """Polygon-prior clutter: inside a water polygon, anything NOT water-blue
    AND NOT a path/trail color AND NOT a large island-shaped land blob is
    overlay clutter (text, icons, callouts).

    Exemptions:
    - Red + yellow pixels (paddle paths, dashed trails crossing water).
    - Large green/tan connected regions (islands).
    - Polygon mask is eroded by `erode_px` so OSM/Jeff boundary mismatch
      doesn't bleed land into water.
    """
    h, w = bgr.shape[:2]
    if not lake_polygons_px:
        return np.zeros((h, w), dtype=np.uint8)
    # Polygon mask (1 inside any lake), then erode to stay clear of boundaries.
    poly_mask = np.zeros((h, w), dtype=np.uint8)
    for poly in lake_polygons_px:
        if len(poly) < 3:
            continue
        pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(poly_mask, [pts], 255)
    if erode_px > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (2 * erode_px + 1, 2 * erode_px + 1))
        poly_mask = cv2.erode(poly_mask, kernel)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # Water-blue: Jeff's pale-mid blue.
    water_blue = cv2.inRange(hsv, np.array([85, 25, 150]),
                             np.array([130, 200, 255]))
    # Trail/path colors to exempt.
    yellow = color_mask_yellow(bgr)
    red = color_mask_red(bgr)
    trails = cv2.bitwise_or(yellow, red)

    # Land tones (green/tan) — pixels that COULD be islands.
    green = cv2.inRange(hsv, np.array([30, 30, 60]), np.array([85, 200, 220]))
    tan = cv2.inRange(hsv, np.array([10, 20, 120]), np.array([30, 180, 230]))
    land_tone = cv2.bitwise_or(green, tan)
    # Find large connected land regions inside polygon — those are islands.
    inside_land = cv2.bitwise_and(poly_mask, land_tone)
    # Close small gaps so an island fragmented by anti-aliasing stays whole.
    inside_land = cv2.morphologyEx(
        inside_land, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
    )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        inside_land, connectivity=8)
    island_mask = np.zeros((h, w), dtype=np.uint8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= island_min_area:
            island_mask[labels == i] = 255

    # Clutter = inside polygon AND not (water-blue OR trail OR island).
    exempt = cv2.bitwise_or(water_blue, cv2.bitwise_or(trails, island_mask))
    inside_clutter = cv2.bitwise_and(poly_mask, cv2.bitwise_not(exempt))
    return inside_clutter


def latlon_polygons_to_pixels(lake_polygons_latlon: list,
                              mosaic_bounds: tuple,
                              shape: tuple) -> list:
    """Project lat/lon polygons into pixel coords for the mosaic.

    mosaic_bounds = (south, west, north, east). shape = (h, w, ...).
    """
    s, w_lon, n, e = mosaic_bounds
    h, w_px = shape[:2]
    out = []
    for poly in lake_polygons_latlon:
        if not poly:
            continue
        pts = []
        for lat, lon in poly:
            # Skip points outside the mosaic.
            x = (lon - w_lon) / (e - w_lon) * w_px
            y = (n - lat) / (n - s) * h
            pts.append((int(round(x)), int(round(y))))
        if len(pts) >= 3:
            out.append(pts)
    return out


def detect_text_via_ocr(bgr: np.ndarray, conf_min: int = 20,
                        pad_px: int = 4) -> np.ndarray:
    """OCR-based text detection — two passes (sparse + dense) merged.

    psm 11 = sparse text (find as many words as possible; good for scattered
    map labels). psm 6 = uniform text block (catches dense paragraph blocks
    where psm 11 sometimes splits or misses).
    """
    try:
        import pytesseract
    except ImportError:
        return np.zeros(bgr.shape[:2], dtype=np.uint8)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    def _run(config: str) -> np.ndarray:
        data = pytesseract.image_to_data(
            gray, config=config,
            output_type=pytesseract.Output.DICT,
        )
        m = np.zeros(bgr.shape[:2], dtype=np.uint8)
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
            cv2.rectangle(m, (x, y), (x + w, y + h), 255, -1)
        return m

    sparse = _run("--psm 11")
    dense = _run("--psm 6")
    return cv2.bitwise_or(sparse, dense)


def detect_solid_icons(bgr: np.ndarray, color_mask: np.ndarray,
                       min_area: int = 6, max_area: int = 600,
                       circularity_min: float = 0.45) -> np.ndarray:
    """Filled circular/square icons in a given color (campsite dots, info markers)."""
    contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(color_mask)
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue
        per = cv2.arcLength(c, True)
        if per <= 0:
            continue
        circ = 4 * np.pi * area / (per * per)
        if circ >= circularity_min:
            cv2.drawContours(out, [c], -1, 255, -1)
    return out


def build_clutter_mask(bgr: np.ndarray, lake_polygons_px: list = None) -> tuple:
    """Returns (final_mask, debug_layers).

    lake_polygons_px: optional list of pixel-coord lake polygons. If provided,
    enables the polygon-prior layer (inside-lake non-blue = clutter).
    """
    blk = color_mask_black(bgr)
    red = color_mask_red(bgr)
    yel = color_mask_yellow(bgr)
    blu = color_mask_blue_text(bgr)

    # Black text: shape-filter for thin strokes, then cluster.
    blk_text = text_shape_filter(blk, max_dim=60)
    blk_text = text_cluster_filter(blk_text)

    # Red: icons (filled circles, small dots) + small label glyphs.
    red_icon = detect_solid_icons(bgr, red, min_area=4)
    red_text = text_shape_filter(red, max_dim=60)

    # Yellow: only consider text-shaped (small + thin), preserving long
    # path lines.
    yel_text = text_shape_filter(yel, min_area=8, max_area=300, max_dim=25)
    yel_text = text_cluster_filter(yel_text)

    # Blue: high-saturation cyan label text (lake names).
    blu_text = text_shape_filter(blu, max_dim=80, max_area=1500,
                                 stroke_width_max=6.0)
    blu_text = text_cluster_filter(blu_text, neighbor_radius=20)

    # Filled dark-box labels (e.g. "George Lake Campground").
    boxes = detect_filled_rect_labels(bgr)

    # Multi-line dark text paragraphs (description blocks at corners).
    paragraphs = detect_text_paragraph_blocks(bgr)

    # OCR-based text detection — catches all fonts/colors in one pass.
    ocr = detect_text_via_ocr(bgr)

    # Polygon-prior: inside a water polygon, non-blue = overlay clutter.
    poly_clutter = detect_non_water_inside_lakes(bgr, lake_polygons_px or [])

    combined = cv2.bitwise_or(blk_text,
        cv2.bitwise_or(red_icon,
        cv2.bitwise_or(red_text,
        cv2.bitwise_or(yel_text,
        cv2.bitwise_or(blu_text,
        cv2.bitwise_or(boxes,
        cv2.bitwise_or(paragraphs,
        cv2.bitwise_or(ocr, poly_clutter))))))))
    # Dilate so inpaint covers full glyph + halo.
    final = cv2.dilate(combined, np.ones((3, 3), np.uint8), iterations=2)

    debug = {
        "black_raw": blk,
        "red_raw": red,
        "yellow_raw": yel,
        "blue_raw": blu,
        "black_text": blk_text,
        "red_icons": red_icon,
        "red_text": red_text,
        "yellow_text": yel_text,
        "blue_text": blu_text,
        "boxes": boxes,
        "paragraphs": paragraphs,
        "ocr": ocr,
        "poly_clutter": poly_clutter,
        "final": final,
    }
    return final, debug


def colorize_layers(debug: dict, shape: tuple) -> np.ndarray:
    """Render the per-color text/icon detections in vivid colors for review."""
    h, w = shape[:2]
    out = np.full((h, w, 3), 255, dtype=np.uint8)
    # Polygon-prior gets a distinct teal so we can see the "inside-lake non-blue" hits.
    out[debug.get("poly_clutter", np.zeros_like(out[:, :, 0])) > 0] = (200, 200, 100)
    # Order: broad detections (OCR, paragraphs) under, then specific detectors over.
    out[debug["ocr"] > 0] = (200, 255, 200)         # light green (OCR)
    out[debug["paragraphs"] > 0] = (200, 200, 255)  # pink (paragraphs)
    out[debug["boxes"] > 0] = (180, 180, 180)       # gray (filled boxes)
    out[debug["black_text"] > 0] = (0, 0, 0)
    out[debug["red_icons"] > 0] = (0, 0, 255)       # red BGR
    out[debug["red_text"] > 0] = (0, 100, 255)      # orange
    out[debug["yellow_text"] > 0] = (0, 200, 255)   # gold
    out[debug["blue_text"] > 0] = (255, 0, 0)       # blue BGR
    return out


def inpaint(bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return cv2.inpaint(bgr, mask, inpaintRadius=4, flags=cv2.INPAINT_TELEA)


def panel(images: list, labels: list) -> np.ndarray:
    """Stack images horizontally with text labels."""
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", default=",".join(str(x) for x in DEFAULT_BBOX))
    parser.add_argument("--zoom", type=int, default=7)
    parser.add_argument("--out", default="clutter_prototype.jpg")
    args = parser.parse_args(argv)

    bbox = tuple(float(x) for x in args.bbox.split(","))
    if len(bbox) != 4:
        print("--bbox needs 4 comma-separated values", file=sys.stderr)
        return 2

    from overlay_osm_jeffs import _build_raster_mosaic
    raster_jpg = REPO_ROOT / "clutter_prototype_raster.jpg"
    s, w, n, e = _build_raster_mosaic(KMZ_PATH, bbox, args.zoom, raster_jpg)
    print(f"  mosaic GPS bounds: S{s} W{w} N{n} E{e}", file=sys.stderr)

    bgr = cv2.imread(str(raster_jpg))
    print(f"  original size: {bgr.shape[1]}x{bgr.shape[0]} px", file=sys.stderr)

    # Pull lake polygons from OSM cache + Jeff's cache, project to pixels.
    from osm_data import load_killarney_features
    osm = load_killarney_features()
    lakes_latlon = []
    for lake in osm.get("lakes", []):
        poly = lake.get("polygon") or []
        if poly:
            lakes_latlon.append(poly)
    mosaic_bounds = (s, w, n, e)
    lakes_px = latlon_polygons_to_pixels(lakes_latlon, mosaic_bounds, bgr.shape)
    print(f"  lake polygons projected: {len(lakes_px)}", file=sys.stderr)

    mask, debug = build_clutter_mask(bgr, lake_polygons_px=lakes_px)
    n_mask = int(np.sum(mask > 0))
    print(f"  clutter mask: {n_mask} px ({100*n_mask/mask.size:.2f}%)",
          file=sys.stderr)

    layers_viz = colorize_layers(debug, bgr.shape)

    overlay = bgr.copy()
    overlay[mask > 0] = (0, 0, 255)

    inpainted = inpaint(bgr, mask)

    composite = panel(
        [bgr, layers_viz, overlay, inpainted],
        ["original", "per-color (blk=text, red=icon, orange=red-text, gold=yellow-text)",
         "final mask (red)", "inpainted"],
    )
    out_path = REPO_ROOT / args.out
    cv2.imwrite(str(out_path), composite, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"Wrote {out_path}", file=sys.stderr)

    html_path = out_path.with_suffix(".html")
    html_path.write_text(
        "<!DOCTYPE html><html><head><title>Clutter inpaint v2</title>"
        "<style>body{margin:0;padding:1rem;font-family:sans-serif;background:#222;color:#eee}"
        "img{max-width:100%;display:block;margin-top:0.6rem}"
        "h1{font-size:1.1rem;margin:0}.meta{color:#aaa;font-size:0.85rem}</style></head>"
        f"<body><h1>Clutter inpaint v2 — bbox {bbox}</h1>"
        f"<div class='meta'>{bgr.shape[1]}x{bgr.shape[0]} px, "
        f"{n_mask} clutter pixels ({100*n_mask/mask.size:.2f}%)</div>"
        f"<img src='{out_path.name}' alt='before / per-color / mask / after'/></body></html>"
    )
    print(f"Wrote {html_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
