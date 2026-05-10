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
