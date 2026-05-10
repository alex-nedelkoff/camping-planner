"""Build tiny KMZ archives at test time for jeffs_extractor unit tests.

Mirrors Jeff's Google Earth super-overlay structure:
- doc.kml at root (NetworkLink to first level — we don't actually need
  this for walk_kmz tests since walk_kmz scans the level directory directly)
- per-tile KML files under <level>/<x>/<y>.kml
- per-tile image files alongside their KML
"""
import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw


def _make_solid_image(width: int, height: int, color: tuple) -> bytes:
    """Return PNG bytes of a solid-color image."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _kml_for_tile(image_filename: str, bounds: tuple) -> str:
    """Build a per-tile KML referencing image_filename with given (n, s, e, w) bounds."""
    n, s, e, w = bounds
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <GroundOverlay>
      <Icon><href>{image_filename}</href></Icon>
      <LatLonBox>
        <north>{n}</north>
        <south>{s}</south>
        <east>{e}</east>
        <west>{w}</west>
        <rotation>0</rotation>
      </LatLonBox>
    </GroundOverlay>
  </Document>
</kml>
"""


def write_synthetic_kmz(out_path: Path, tiles: list, level: int = 6) -> Path:
    """Write a KMZ with the given tiles to out_path.

    Each tile in `tiles` is a dict:
      {"filename": "tile_a.png", "bounds": (n, s, e, w),
       "image": optional bytes (defaults to a 100x100 solid white PNG)}

    KMZ layout:
      doc.kml                    — root (minimal, doesn't matter for tests)
      <level>/0/<index>.kml      — per-tile KML referencing the image
      <level>/0/<filename>       — image file
    """
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", _root_kml())
        for i, tile in enumerate(tiles):
            kml_path = f"{level}/0/{i}.kml"
            img_path = f"{level}/0/{tile['filename']}"
            z.writestr(kml_path, _kml_for_tile(tile["filename"], tile["bounds"]))
            img_bytes = tile.get("image") or _make_solid_image(100, 100, (255, 255, 255))
            z.writestr(img_path, img_bytes)
    return out_path


def _root_kml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document><name>synthetic test kmz</name></Document>
</kml>
"""
