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
