"""
Prototype: extract Jeff's curated annotations from the KMZ raster.

Detectors:
  1. Campsites: small filled black/dark triangles + nearby digit OCR.
  2. Yellow canoe paths (already validated, included for completeness).
  3. Brown/red dashed trails (portages + hiking trails).

Output: 4-panel JPG showing detections per layer.

Usage:
    python3 scripts/prototype_jeffs_features.py
    python3 scripts/prototype_jeffs_features.py --bbox 46.005,-81.42,46.04,-81.38
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


# ---- Campsite triangle detection ---------------------------------------

def filter_clustered_triangles(triangles: list,
                               cluster_radius_px: int = 35,
                               max_neighbors: int = 1) -> list:
    """Drop triangles that have too many other triangles within a small
    radius. Real campsite markers are isolated; QR-code corners and label
    decorations cluster densely.
    """
    out = []
    for i, t in enumerate(triangles):
        cx, cy = t["center"]
        neighbors = 0
        for j, other in enumerate(triangles):
            if j == i:
                continue
            ocx, ocy = other["center"]
            d = ((ocx - cx) ** 2 + (ocy - cy) ** 2) ** 0.5
            if d <= cluster_radius_px:
                neighbors += 1
        if neighbors <= max_neighbors:
            out.append(t)
    return out


def load_campsites_gpx(gpx_path: Path) -> list:
    """Parse a Killarney campsites GPX file. Returns list of
    {"name": str, "lat": float, "lon": float}.
    """
    import xml.etree.ElementTree as ET
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    tree = ET.parse(str(gpx_path))
    root = tree.getroot()
    out = []
    for wpt in root.findall("g:wpt", ns):
        lat = float(wpt.attrib["lat"])
        lon = float(wpt.attrib["lon"])
        name_el = wpt.find("g:name", ns)
        name = name_el.text if name_el is not None else ""
        out.append({"name": name, "lat": lat, "lon": lon})
    return out


def label_triangles_via_gpx(triangles: list, campsites: list,
                            mosaic_bounds: tuple, mosaic_shape: tuple,
                            max_dist_km: float = 0.3) -> list:
    """For each detected triangle, find nearest campsite GPS from GPX and
    assign its name as the label. Threshold prevents wild matches.

    mosaic_bounds = (south, west, north, east).
    """
    import math
    s, w, n, e = mosaic_bounds
    h, mw = mosaic_shape[:2]

    def pixel_to_gps(px, py):
        lon = w + (px / mw) * (e - w)
        lat = n - (py / h) * (n - s)
        return (lat, lon)

    def haversine_km(a, b):
        R = 6371.0
        lat1, lon1 = a
        lat2, lon2 = b
        p1 = math.radians(lat1); p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * \
            math.sin(dl / 2) ** 2
        return R * 2 * math.asin(math.sqrt(x))

    out = []
    for t in triangles:
        cx, cy = t["center"]
        gps = pixel_to_gps(cx, cy)
        best = None
        best_d = float("inf")
        for c in campsites:
            d = haversine_km(gps, (c["lat"], c["lon"]))
            if d < best_d:
                best_d = d
                best = c
        if best is not None and best_d <= max_dist_km:
            out.append({**t, "label": best["name"],
                        "label_dist_km": round(best_d, 3),
                        "gps": gps})
        else:
            out.append({**t, "label": "", "label_dist_km": None,
                        "gps": gps})
    return out


def filter_dense_region_triangles(bgr: np.ndarray, triangles: list,
                                  region_size: int = 60,
                                  max_dark_pct: float = 0.30) -> list:
    """Drop triangles surrounded by high-density dark pixels (QR codes, dark
    label boxes, dense print). A real campsite triangle sits on water/land
    with only ~5-10% dark pixels in its local region.
    """
    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    dark_mask = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 100, 80]))
    out = []
    half = region_size // 2
    for t in triangles:
        cx, cy = t["center"]
        x0 = max(0, cx - half)
        y0 = max(0, cy - half)
        x1 = min(w, cx + half)
        y1 = min(h, cy + half)
        region = dark_mask[y0:y1, x0:x1]
        if region.size == 0:
            continue
        dark_pct = float(np.sum(region > 0)) / region.size
        if dark_pct > max_dark_pct:
            continue
        out.append({**t, "local_dark_pct": round(dark_pct, 3)})
    return out


def remove_text_from_raster(bgr: np.ndarray, conf_min: int = 25,
                            pad_px: int = 3) -> np.ndarray:
    """Return a copy of bgr with all OCR-detected text regions replaced
    by white. Use this BEFORE running color-based shape detection so glyphs
    don't pollute the color masks.

    pad_px: extend each text bbox by this many pixels to also catch glyph
    halos / anti-aliased edges.
    """
    try:
        import pytesseract
    except ImportError:
        return bgr.copy()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    data = pytesseract.image_to_data(
        gray, config="--psm 11",
        output_type=pytesseract.Output.DICT,
    )
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


def _is_equilateral_ish(approx: np.ndarray, bbox: tuple,
                        aspect_min: float = 0.55,
                        aspect_max: float = 1.8,
                        fill_min: float = 0.30) -> bool:
    """Triangle-quality checks. Relaxed thresholds because small triangles
    get distorted by JPEG compression + anti-aliasing — strict equilateral
    matching loses genuine markers. Convexity check dropped for the same
    reason (tiny triangles with aliased corners may not be perfectly convex).
    """
    x, y, w, h = bbox
    if h <= 0 or w <= 0:
        return False
    aspect = w / h
    if not (aspect_min <= aspect <= aspect_max):
        return False
    area = cv2.contourArea(approx)
    fill = area / (w * h)
    if fill < fill_min:
        return False
    return True


def detect_campsite_triangles(bgr: np.ndarray,
                              min_area: int = 14,
                              max_area: int = 350,
                              max_dim: int = 28,
                              triangle_tolerance: float = 0.06) -> list:
    """Find small solid-filled black/dark-gray triangles."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    dark = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 100, 80]))
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
    triangles = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if max(w, h) > max_dim:
            continue
        per = cv2.arcLength(c, True)
        if per <= 0:
            continue
        approx = cv2.approxPolyDP(c, triangle_tolerance * per, closed=True)
        if len(approx) != 3:
            continue
        if not _is_equilateral_ish(approx, (x, y, w, h)):
            continue
        cx = x + w // 2
        cy = y + h // 2
        triangles.append({
            "center": (cx, cy),
            "bbox": (x, y, w, h),
            "area": int(area),
            "vertices": approx.reshape(-1, 2).tolist(),
        })
    return triangles


def detect_red_campsite_triangles(bgr: np.ndarray,
                                  min_area: int = 14,
                                  max_area: int = 350,
                                  max_dim: int = 28,
                                  triangle_tolerance: float = 0.06) -> list:
    """RED triangle peak markers (H1, H51, etc. in Killarney)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, np.array([0, 100, 80]), np.array([10, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([170, 100, 80]),
                       np.array([180, 255, 255]))
    red = cv2.bitwise_or(red1, red2)
    contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
    triangles = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if max(w, h) > max_dim:
            continue
        per = cv2.arcLength(c, True)
        if per <= 0:
            continue
        approx = cv2.approxPolyDP(c, triangle_tolerance * per, closed=True)
        if len(approx) != 3:
            continue
        if not _is_equilateral_ish(approx, (x, y, w, h)):
            continue
        cx = x + w // 2
        cy = y + h // 2
        triangles.append({
            "center": (cx, cy),
            "bbox": (x, y, w, h),
            "area": int(area),
            "vertices": approx.reshape(-1, 2).tolist(),
        })
    return triangles


# ---- Number OCR near triangles -----------------------------------------

def ocr_label_per_triangle(bgr: np.ndarray, triangles: list,
                           roi_radius: int = 30,
                           upscale: float = 4.0) -> list:
    """Per-triangle ROI OCR: crop a small region around each triangle and OCR
    just that crop at high magnification. Far more reliable for tiny digits
    than running OCR on the whole image.
    """
    try:
        import pytesseract
    except ImportError:
        return [{**t, "label": ""} for t in triangles]
    h, w = bgr.shape[:2]
    out = []
    for t in triangles:
        cx, cy = t["center"]
        # ROI around the triangle's center, padded.
        x0 = max(0, cx - roi_radius)
        y0 = max(0, cy - roi_radius)
        x1 = min(w, cx + roi_radius)
        y1 = min(h, cy + roi_radius)
        roi = bgr[y0:y1, x0:x1]
        if roi.size == 0:
            out.append({**t, "label": ""})
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, None, fx=upscale, fy=upscale,
                         interpolation=cv2.INTER_CUBIC)
        # PSM 8 = single word. Whitelist digits + H.
        text = pytesseract.image_to_string(
            big,
            config="--psm 8 -c tessedit_char_whitelist=0123456789Hh",
        ).strip()
        # Tesseract sometimes returns junk; require digit + reasonable length.
        if not text or len(text) > 4 or not any(c.isdigit() for c in text):
            text = ""
        out.append({**t, "label": text})
    return out


def ocr_digits_near_triangles(bgr: np.ndarray, triangles: list,
                              search_radius_px: int = 40,
                              upscale: float = 2.0) -> list:
    """For each triangle, find the nearest digit-only text within radius.

    Upscales the image before OCR (small digits OCR much better at 2x).
    Uses Tesseract with whitelist for digits + 'H' (peak labels like 'H51').
    """
    try:
        import pytesseract
    except ImportError:
        return [{**t, "label": ""} for t in triangles]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if upscale > 1.0:
        gray_big = cv2.resize(gray, None, fx=upscale, fy=upscale,
                              interpolation=cv2.INTER_CUBIC)
    else:
        gray_big = gray
    data = pytesseract.image_to_data(
        gray_big,
        config="--psm 11 -c tessedit_char_whitelist=0123456789Hh",
        output_type=pytesseract.Output.DICT,
    )
    # Build list of detected text boxes with center + label. Accept ALL
    # confidences — proximity-match to triangle filters out noise.
    # But require text to look like a plausible site label (1-3 chars,
    # contains at least one digit).
    text_boxes = []
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text or len(text) > 3:
            continue
        # Require at least one digit (drops "h", "hhhh" noise).
        if not any(c.isdigit() for c in text):
            continue
        x = int(data["left"][i] / upscale)
        y = int(data["top"][i] / upscale)
        w = int(data["width"][i] / upscale)
        h = int(data["height"][i] / upscale)
        # Drop unreasonably large boxes (those are usually misdetections
        # spanning multiple actual labels).
        if w > 60 or h > 30:
            continue
        text_boxes.append({
            "text": text,
            "center": (x + w // 2, y + h // 2),
            "bbox": (x, y, w, h),
        })

    out = []
    for t in triangles:
        tcx, tcy = t["center"]
        best = None
        best_dist = float("inf")
        for tb in text_boxes:
            tbcx, tbcy = tb["center"]
            d = ((tbcx - tcx) ** 2 + (tbcy - tcy) ** 2) ** 0.5
            if d < best_dist and d <= search_radius_px:
                best_dist = d
                best = tb
        out.append({**t, "label": best["text"] if best else "",
                    "label_dist": best_dist if best else None})
    return out


# ---- Canoe path detection (reuse simplified) ---------------------------

def detect_canoe_paths(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([20, 100, 150]),
                         np.array([40, 255, 255]))
    # Component filter: keep line-like components (long vs wide).
    n, lbl, st, _ = cv2.connectedComponentsWithStats(yellow, connectivity=8)
    out = np.zeros_like(yellow)
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        w = st[i, cv2.CC_STAT_WIDTH]
        h = st[i, cv2.CC_STAT_HEIGHT]
        if area < 30:
            continue
        # Length-to-width-ish ratio.
        long_dim = max(w, h)
        short_dim = max(1, min(w, h))
        if long_dim / short_dim < 1.5:
            continue
        out[lbl == i] = 255
    return out


# ---- Portage / trail dashed-line detection -----------------------------

def detect_portages_trails(bgr: np.ndarray,
                           text_mask: np.ndarray = None) -> np.ndarray:
    """Reddish-brown dashed lines (portage/hiking trails).

    Strategy:
      1. Color mask: brown/red HSV.
      2. Subtract OCR text mask (removes red label glyphs from the input)
         WITHOUT destroying the surrounding raster (so adjacent dashes
         remain intact).
      3. Morph-close to merge dashes into one line per trail.
      4. Filter post-merge by line-likeness (aspect ratio, fill).
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    brown1 = cv2.inRange(hsv, np.array([0, 60, 80]), np.array([15, 200, 200]))
    brown2 = cv2.inRange(hsv, np.array([170, 60, 80]),
                         np.array([180, 200, 200]))
    brown = cv2.bitwise_or(brown1, brown2)

    # Subtract OCR text regions (red labels like "Dam", "Liftover",
    # "Backpacking Trail Starting Point" disappear; dashes near them
    # survive because we only subtract within text bboxes).
    if text_mask is not None:
        brown = cv2.bitwise_and(brown, cv2.bitwise_not(text_mask))

    closed = cv2.morphologyEx(
        brown, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11)),
    )
    n, lbl, st, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    out = np.zeros_like(closed)
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        w = st[i, cv2.CC_STAT_WIDTH]
        h = st[i, cv2.CC_STAT_HEIGHT]
        if area < 80:
            continue
        long_dim = max(w, h)
        short_dim = max(1, min(w, h))
        if long_dim < 50:
            continue
        if long_dim / short_dim < 2.5:
            continue
        bbox_area = w * h
        fill = area / bbox_area
        if fill > 0.50:
            continue
        out[lbl == i] = 255
    return out


def _build_text_mask(bgr: np.ndarray, conf_min: int = 25,
                     pad_px: int = 3) -> np.ndarray:
    """Return a binary mask of OCR-detected text regions (no in-painting)."""
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
        w = data["width"][i] + 2 * pad_px
        h = data["height"][i] + 2 * pad_px
        cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
    return mask


# ---- Visualization -----------------------------------------------------

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


def draw_campsite_overlay(bgr: np.ndarray, sites: list,
                          color: tuple = (0, 0, 255)) -> np.ndarray:
    """Draw circle + label for each detected campsite."""
    out = bgr.copy()
    for s in sites:
        cx, cy = s["center"]
        cv2.circle(out, (cx, cy), 14, color, 2)
        label = s.get("label", "")
        if label:
            cv2.putText(out, label, (cx + 16, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2,
                        cv2.LINE_AA)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox",
                        default=",".join(str(x) for x in DEFAULT_BBOX))
    parser.add_argument("--zoom", type=int, default=7)
    parser.add_argument("--gpx", default=str(REPO_ROOT / "killarneyCampsites.gpx"),
                        help="GPX file of campsites for GPS-based labelling.")
    parser.add_argument("--gpx-max-dist-km", type=float, default=0.15,
                        help="Max GPS distance for matching a triangle to a "
                             "GPX campsite (default 0.15 km).")
    parser.add_argument("--out", default="jeffs_features_prototype.jpg")
    args = parser.parse_args(argv)

    bbox = tuple(float(x) for x in args.bbox.split(","))

    from overlay_osm_jeffs import _build_raster_mosaic
    raster_jpg = REPO_ROOT / "jeffs_features_raster.jpg"
    s, w, n, e = _build_raster_mosaic(KMZ_PATH, bbox, args.zoom, raster_jpg)
    print(f"  mosaic GPS: S{s} W{w} N{n} E{e}", file=sys.stderr)

    bgr = cv2.imread(str(raster_jpg))
    print(f"  size: {bgr.shape[1]}x{bgr.shape[0]}", file=sys.stderr)

    # Pre-pass: remove all OCR text from a working copy so glyphs don't
    # pollute color-based triangle detection.
    bgr_clean = remove_text_from_raster(bgr)
    n_changed = int(np.sum(np.any(bgr_clean != bgr, axis=2)))
    print(f"  text-removal: {n_changed} px whitened "
          f"({100 * n_changed / bgr.shape[0] / bgr.shape[1]:.1f}%)",
          file=sys.stderr)

    # Load GPX campsites if available for GPS-based labelling.
    campsites = []
    gpx_path = Path(args.gpx)
    if gpx_path.exists():
        campsites = load_campsites_gpx(gpx_path)
        print(f"  loaded {len(campsites)} campsites from {gpx_path.name}",
              file=sys.stderr)
    mosaic_bounds = (s, w, n, e)

    # Black campsite triangles.
    black_tris_raw = detect_campsite_triangles(bgr_clean)
    black_tris_clustered = filter_clustered_triangles(black_tris_raw)
    black_tris = filter_dense_region_triangles(bgr_clean, black_tris_clustered)
    print(f"  black triangles: {len(black_tris_raw)} raw → "
          f"{len(black_tris_clustered)} (cluster) → "
          f"{len(black_tris)} (dense-region)", file=sys.stderr)
    if campsites:
        black_sites = label_triangles_via_gpx(
            black_tris, campsites, mosaic_bounds, bgr.shape,
            max_dist_km=args.gpx_max_dist_km)
    else:
        black_sites = ocr_digits_near_triangles(bgr, black_tris,
                                                search_radius_px=35)
    labelled = sum(1 for s in black_sites if s["label"])
    print(f"  black triangles labelled: {labelled}/{len(black_sites)} "
          f"({[s['label'] for s in black_sites if s['label']]})",
          file=sys.stderr)

    # Red triangles (peak markers).
    red_tris_raw = detect_red_campsite_triangles(bgr_clean)
    red_tris_clustered = filter_clustered_triangles(red_tris_raw)
    red_tris = filter_dense_region_triangles(bgr_clean, red_tris_clustered)
    print(f"  red triangles: {len(red_tris_raw)} raw → "
          f"{len(red_tris_clustered)} (cluster) → "
          f"{len(red_tris)} (dense-region)", file=sys.stderr)
    # Red triangles are peaks, not campsites — keep OCR-based labelling
    # for these (matches 'H1', 'H51' style labels).
    red_sites = ocr_digits_near_triangles(bgr, red_tris,
                                          search_radius_px=35)
    red_labelled = sum(1 for s in red_sites if s['label'])
    print(f"  red triangles labelled: {red_labelled}/{len(red_sites)} "
          f"({[s['label'] for s in red_sites if s['label']]})",
          file=sys.stderr)

    # Build OCR text mask (used to subtract text from portage detection
    # without destroying the surrounding raster).
    text_mask = _build_text_mask(bgr)

    # Canoe paths — text-cleaned image (yellow text is rare; cleaning fine).
    paths = detect_canoe_paths(bgr_clean)
    print(f"  yellow path mask (text-cleaned): {int((paths > 0).sum())} px",
          file=sys.stderr)
    # Portages — original image, but subtract text mask so red label
    # glyphs ("Dam", "Liftover", "Backpacking Trail Starting Point") get
    # removed from the brown signal while dashes near them survive.
    portages = detect_portages_trails(bgr, text_mask=text_mask)
    print(f"  portage/trail mask: {int((portages > 0).sum())} px",
          file=sys.stderr)

    # Distinct overlay color per layer (BGR):
    # - black-tri campsites: CYAN (255, 255, 0)
    # - red-tri peaks:       MAGENTA (255, 0, 255)
    # - yellow paths:        BRIGHT YELLOW (0, 255, 255)
    # - portages/trails:     BRIGHT GREEN (0, 255, 0)
    sites_viz = draw_campsite_overlay(bgr, black_sites,
                                      color=(255, 255, 0))   # cyan
    sites_viz = draw_campsite_overlay(sites_viz, red_sites,
                                      color=(255, 0, 255))   # magenta

    paths_viz = bgr.copy()
    paths_viz[paths > 0] = (0, 255, 255)                     # bright yellow

    portages_viz = bgr.copy()
    portages_viz[portages > 0] = (0, 255, 0)                 # bright green

    composite = panel(
        [bgr, sites_viz, paths_viz, portages_viz],
        ["original",
         f"campsites (red ring=black tri, orange ring=red tri)",
         f"canoe paths ({int((paths>0).sum())} px)",
         f"portages/trails ({int((portages>0).sum())} px)"],
    )
    out_path = REPO_ROOT / args.out
    cv2.imwrite(str(out_path), composite, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"Wrote {out_path}", file=sys.stderr)

    html_path = out_path.with_suffix(".html")
    html_path.write_text(
        "<!DOCTYPE html><html><head><title>Jeff's features prototype</title>"
        "<style>body{margin:0;padding:1rem;font-family:sans-serif;"
        "background:#222;color:#eee}img{max-width:100%;display:block;"
        "margin-top:0.6rem}h1{font-size:1.1rem;margin:0}.meta{color:#aaa;"
        "font-size:0.85rem}</style></head>"
        f"<body><h1>Jeff's features prototype — bbox {bbox}</h1>"
        f"<div class='meta'>{bgr.shape[1]}x{bgr.shape[0]} px | "
        f"black tris {len(black_sites)} ({labelled} labelled) | "
        f"red tris {len(red_sites)}</div>"
        f"<img src='{out_path.name}' alt='4-panel'/></body></html>"
    )
    print(f"Wrote {html_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
