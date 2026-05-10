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
