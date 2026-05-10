"""Tests for jeffs_paths_extractor.py."""
import numpy as np

from jeffs_paths_extractor import _skeletonize


def test_skeletonize_thick_horizontal_line_becomes_thin():
    """A 9-pixel-tall horizontal yellow stripe skeletonizes to ~1 px tall."""
    h, w = 50, 200
    mask = np.zeros((h, w), dtype=np.uint8)
    # Draw a 9-pixel-tall stripe through the middle row.
    mask[20:29, 5:195] = 255
    skel = _skeletonize(mask)
    assert skel.shape == mask.shape
    assert skel.dtype == np.uint8
    # Every column in [5, 194] should have exactly 1-2 white pixels (depends
    # on how the thinning algorithm tied-break a 9-wide stripe).
    for col in range(10, 190):
        col_white = int(np.sum(skel[:, col] > 0))
        assert col_white in (1, 2), \
            f"Column {col} has {col_white} white pixels (expected 1 or 2)"


from jeffs_paths_extractor import _trace_skeleton_polylines


def test_trace_skeleton_polylines_finds_one_horizontal_line():
    """A 1-pixel horizontal stripe should yield exactly one polyline."""
    h, w = 30, 100
    skel = np.zeros((h, w), dtype=np.uint8)
    # Single row of white pixels from col 10 to col 89.
    skel[15, 10:90] = 255
    polylines = _trace_skeleton_polylines(skel, min_length_px=10)
    assert len(polylines) == 1
    line = polylines[0]
    # Polyline should span the full extent of the drawn stripe.
    xs = [p[0] for p in line]
    ys = [p[1] for p in line]
    # Note: returned points are (col, row) tuples — i.e., (x, y).
    assert min(xs) == 10
    assert max(xs) == 89
    assert all(y == 15 for y in ys)


def test_trace_skeleton_drops_too_short_polylines():
    """A 5-pixel stripe is below min_length=10 → dropped."""
    skel = np.zeros((20, 50), dtype=np.uint8)
    skel[10, 5:10] = 255
    polylines = _trace_skeleton_polylines(skel, min_length_px=10)
    assert polylines == []
