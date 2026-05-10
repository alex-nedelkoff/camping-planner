"""Tests for jeffs_extractor.py."""
from pathlib import Path

import pytest

from tests.fixtures.synthetic_kmz import write_synthetic_kmz
from jeffs_extractor import walk_kmz, tile_pixel_to_gps


def test_walk_kmz_yields_tiles_in_bbox(tmp_path):
    kmz = tmp_path / "synthetic.kmz"
    # Four tiles: two inside target bbox, two outside.
    write_synthetic_kmz(kmz, level=6, tiles=[
        # Inside bbox (45.0..46.0, -82.0..-81.0):
        {"filename": "a.png", "bounds": (45.5, 45.4, -81.5, -81.6)},
        {"filename": "b.png", "bounds": (45.7, 45.6, -81.3, -81.4)},
        # Outside bbox:
        {"filename": "c.png", "bounds": (50.0, 49.9, -81.5, -81.6)},  # north of bbox
        {"filename": "d.png", "bounds": (45.5, 45.4, -70.0, -70.1)},  # east of bbox
    ])

    bbox = (45.0, -82.0, 46.0, -81.0)  # (south, west, north, east)
    tiles = list(walk_kmz(kmz, bbox=bbox, zoom_level=6))
    names = sorted(t.image_path.name for t in tiles)
    assert names == ["a.png", "b.png"]


def test_tile_pixel_to_gps_linear_interpolation():
    # Tile covering 1 deg x 1 deg, image 100x100. Pixel (50, 50) is center.
    class FakeTile:
        north = 46.0
        south = 45.0
        east = -81.0
        west = -82.0

    lat, lon = tile_pixel_to_gps(FakeTile, 50, 50, img_w=100, img_h=100)
    assert abs(lat - 45.5) < 0.001
    assert abs(lon - -81.5) < 0.001

    # Top-left pixel (0, 0) should be (north, west) = (46.0, -82.0).
    lat, lon = tile_pixel_to_gps(FakeTile, 0, 0, img_w=100, img_h=100)
    assert abs(lat - 46.0) < 0.001
    assert abs(lon - -82.0) < 0.001

    # Bottom-right pixel (100, 100) should be (south, east) = (45.0, -81.0).
    lat, lon = tile_pixel_to_gps(FakeTile, 100, 100, img_w=100, img_h=100)
    assert abs(lat - 45.0) < 0.001
    assert abs(lon - -81.0) < 0.001


def test_walk_kmz_rejects_rotated_tiles(tmp_path):
    """Non-zero rotation requires homography; we hard-fail rather than silently skew."""
    kmz = tmp_path / "synthetic.kmz"
    write_synthetic_kmz(kmz, level=6, tiles=[
        {"filename": "a.png", "bounds": (45.5, 45.4, -81.5, -81.6)},
    ])
    # Patch the KML to set rotation=15 instead of 0.
    import zipfile
    with zipfile.ZipFile(kmz, "r") as z:
        contents = {n: z.read(n) for n in z.namelist()}
    for name in list(contents):
        if name.endswith(".kml") and name != "doc.kml":
            contents[name] = contents[name].replace(b"<rotation>0</rotation>",
                                                    b"<rotation>15</rotation>")
    with zipfile.ZipFile(kmz, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in contents.items():
            z.writestr(n, b)

    bbox = (45.0, -82.0, 46.0, -81.0)
    with pytest.raises(ValueError, match="rotation"):
        list(walk_kmz(kmz, bbox=bbox, zoom_level=6))


import io

import cv2
import numpy as np
from PIL import Image, ImageDraw

from jeffs_extractor import build_mosaic, extract_lakes_from_mosaic


def _solid_blue_tile_bytes(w=200, h=200, blue=(100, 200, 220)):
    """200x200 PNG, mostly white, with a blue circle in the middle (HSV blue range)."""
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Note: PIL uses RGB; OpenCV reads BGR. Choose color so HSV-blue triggers.
    draw.ellipse((40, 40, 160, 160), fill=blue)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_build_mosaic_pastes_tiles_at_correct_positions(tmp_path):
    kmz = tmp_path / "synthetic.kmz"
    write_synthetic_kmz(kmz, level=6, tiles=[
        # 2-tile horizontal strip: (45.0..46.0, -82.0..-81.5) and (45.0..46.0, -81.5..-81.0).
        {"filename": "left.png",
         "bounds": (46.0, 45.0, -81.5, -82.0),
         "image": _solid_blue_tile_bytes(100, 100)},
        {"filename": "right.png",
         "bounds": (46.0, 45.0, -81.0, -81.5),
         "image": _solid_blue_tile_bytes(100, 100)},
    ])

    bbox = (45.0, -82.0, 46.0, -81.0)
    tiles = list(walk_kmz(kmz, bbox=bbox, zoom_level=6,
                          extract_dir=tmp_path / "extracted"))
    mosaic, mosaic_bounds = build_mosaic(tiles)
    # Mosaic should be wider than tall (covers 1 deg lat, 1 deg lon at lat 45):
    assert mosaic.shape[0] > 0 and mosaic.shape[1] > 0
    # Bounds should match the union of tile bounds.
    n, s, e, w = mosaic_bounds
    assert abs(n - 46.0) < 1e-6
    assert abs(s - 45.0) < 1e-6
    assert abs(e - -81.0) < 1e-6
    assert abs(w - -82.0) < 1e-6


def test_extract_lakes_finds_synthetic_blue_blob(tmp_path):
    """One blue circle in a tile should produce one lake polygon."""
    kmz = tmp_path / "synthetic.kmz"
    write_synthetic_kmz(kmz, level=6, tiles=[
        {"filename": "a.png",
         "bounds": (46.0, 45.0, -81.0, -82.0),
         "image": _solid_blue_tile_bytes(200, 200)},
    ])
    bbox = (45.0, -82.0, 46.0, -81.0)
    tiles = list(walk_kmz(kmz, bbox=bbox, zoom_level=6,
                          extract_dir=tmp_path / "extracted"))
    mosaic, mosaic_bounds = build_mosaic(tiles)
    palette = {"hue": [90, 130], "saturation": [80, 255], "value": [80, 255],
               "min_area_px": 100}
    lakes = extract_lakes_from_mosaic(mosaic, mosaic_bounds, palette)
    assert len(lakes) == 1
    lake = lakes[0]
    # Centroid should be near the center of the tile (lat 45.5, lon -81.5).
    cx, cy = lake["centroid"]
    assert 45.4 < cx < 45.6
    assert -81.6 < cy < -81.4
    # Polygon has at least 4 vertices.
    assert len(lake["polygon"]) >= 4


from jeffs_extractor import assign_lake_names


def test_assign_lake_names_uses_osm_within_500m():
    jeffs_lakes = [
        {"polygon": [[1, 1]], "centroid": [46.05, -81.40]},  # near OSM
        {"polygon": [[1, 1]], "centroid": [46.06, -81.30]},  # near OSM
        {"polygon": [[1, 1]], "centroid": [50.00, -70.00]},  # nowhere near anything
    ]
    osm_lakes = [
        {"name": "Killarney Lake", "centroid": [46.05, -81.40]},
        {"name": "Freeland Lake",  "centroid": [46.06, -81.30]},
    ]
    overrides = {"lakes": []}
    named = assign_lake_names(jeffs_lakes, osm_lakes, overrides)
    names = sorted(l.get("name", "?") for l in named)
    # First two get OSM names; third is unnamed.
    assert "Killarney Lake" in names
    assert "Freeland Lake" in names
    assert "?" in names  # third polygon unnamed


def test_assign_lake_names_uses_overrides_for_unmatched():
    jeffs_lakes = [
        {"polygon": [[1, 1]], "centroid": [46.022, -81.510]},  # not in OSM
    ]
    osm_lakes = []
    overrides = {"lakes": [
        {"centroid_near": [46.020, -81.510], "name": "Baie Fine"},
    ]}
    named = assign_lake_names(jeffs_lakes, osm_lakes, overrides)
    assert named[0]["name"] == "Baie Fine"


def test_assign_lake_names_osm_wins_over_override_when_both_match():
    """If OSM has a match within 500m, use it. Overrides are for unmatched only."""
    jeffs_lakes = [
        {"polygon": [[1, 1]], "centroid": [46.05, -81.40]},
    ]
    osm_lakes = [{"name": "Killarney Lake", "centroid": [46.05, -81.40]}]
    overrides = {"lakes": [{"centroid_near": [46.05, -81.40], "name": "Wrong Override"}]}
    named = assign_lake_names(jeffs_lakes, osm_lakes, overrides)
    assert named[0]["name"] == "Killarney Lake"


from jeffs_extractor import detect_icons_in_image


def _tile_with_red_dots(tile_w=400, tile_h=400, dot_centers=((100, 100), (300, 300))):
    """Draw red dots (~20px) on a white background — simulates Jeff's campsite icons."""
    img = np.full((tile_h, tile_w, 3), 255, dtype=np.uint8)  # white BGR
    for cx, cy in dot_centers:
        # OpenCV uses BGR. Pure red is (0, 0, 255).
        cv2.circle(img, (cx, cy), 12, (0, 0, 255), thickness=-1)
    return img


def test_detect_icons_finds_each_red_dot():
    img = _tile_with_red_dots(dot_centers=((100, 100), (300, 300)))
    palette = {"hue": [0, 15], "saturation": [120, 255], "value": [120, 255],
               "min_area_px": 50, "max_area_px": 2000,
               "min_aspect": 0.5, "max_aspect": 2.0}
    icons = detect_icons_in_image(img, palette)
    assert len(icons) == 2
    centers = sorted((round(i["pixel_center"][0]), round(i["pixel_center"][1]))
                     for i in icons)
    assert centers == [(100, 100), (300, 300)]


def test_detect_icons_filters_by_area():
    """A tiny dot below min_area should be ignored."""
    img = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.circle(img, (100, 100), 2, (0, 0, 255), thickness=-1)  # ~12px² area
    palette = {"hue": [0, 15], "saturation": [120, 255], "value": [120, 255],
               "min_area_px": 50, "max_area_px": 2000,
               "min_aspect": 0.5, "max_aspect": 2.0}
    icons = detect_icons_in_image(img, palette)
    assert icons == []
