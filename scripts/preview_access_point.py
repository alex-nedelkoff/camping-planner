"""
One-off preview: render a Leaflet map showing the CURRENT access point GPS
vs a PROPOSED offshore GPS, on top of a focused Jeff's-map raster so you
can visually verify before committing the change.

Usage:
    python3 scripts/preview_access_point.py
    open http://localhost:8000/access_point_preview.html

Builds a fresh small mosaic around the access point (so the raster bounds
are accurate). Reuses overlay_osm_jeffs._build_raster_mosaic for that.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

CURRENT = [46.0136, -81.4049]
PROPOSED = [46.0150, -81.4049]

# Tight bbox around the access point so the mini-raster is focused.
# (south, west, north, east)
PREVIEW_BBOX = (46.005, -81.420, 46.030, -81.395)

KMZ_PATH = (
    REPO_ROOT
    / "Maps by Jeff - Full French River and Killarney Paddling Map v4.0 - Google Earth.kmz"
)
RASTER_JPG = REPO_ROOT / "access_point_preview_raster.jpg"


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Access point — current vs proposed</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body, #map { height: 100%; margin: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
  .legend { position: absolute; bottom: 1rem; left: 1rem; z-index: 1000;
            background: white; padding: 0.6rem 0.8rem; border-radius: 6px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2); font-size: 0.85rem;
            line-height: 1.5; }
  .legend-swatch { display: inline-block; width: 14px; height: 14px;
                   border-radius: 50%; margin-right: 0.4rem;
                   vertical-align: middle; border: 2px solid #000; }
  .swatch-current { background: #ffeb3b; }
  .swatch-proposed { background: #4caf50; border-color: #1b5e20; }
  .opacity-row { margin-top: 0.4rem; display: flex; align-items: center;
                 gap: 0.4rem; font-size: 0.8rem; }
</style>
</head>
<body>
<div id="map"></div>
<div class="legend">
  <div><span class="legend-swatch swatch-current"></span>
    Current ({current_gps})</div>
  <div><span class="legend-swatch swatch-proposed"></span>
    Proposed ({proposed_gps})</div>
  <div style="margin-top: 0.5rem; color: #555;">
    Distance: {distance_m:.0f} m
  </div>
  <div class="opacity-row">
    <label>Raster opacity</label>
    <input id="raster-opacity" type="range" min="0" max="1" step="0.05" value="0.7">
  </div>
</div>
<script>
const current = {current_gps};
const proposed = {proposed_gps};
const rasterBounds = {raster_bounds};
const rasterUrl = {raster_url};

const map = L.map('map', { center: current, zoom: 14 });
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap',
  maxZoom: 18,
}).addTo(map);

let raster = null;
if (rasterUrl) {
  raster = L.imageOverlay(rasterUrl, rasterBounds, { opacity: 0.7 }).addTo(map);
  document.getElementById('raster-opacity').addEventListener('input', e => {
    raster.setOpacity(parseFloat(e.target.value));
  });
}

L.circleMarker(current, {
  radius: 9, color: '#000', weight: 2,
  fillColor: '#ffeb3b', fillOpacity: 0.95,
}).bindPopup('Current: ' + current.join(', ')).addTo(map);

L.circleMarker(proposed, {
  radius: 9, color: '#1b5e20', weight: 2,
  fillColor: '#4caf50', fillOpacity: 0.95,
}).bindPopup('Proposed: ' + proposed.join(', ')).addTo(map);

L.polyline([current, proposed], {
  color: '#666', weight: 2, dashArray: '4 4',
}).addTo(map);

map.fitBounds([current, proposed], { padding: [80, 80] });
</script>
</body>
</html>
"""


def _haversine_m(a, b):
    import math
    R = 6371000
    p1 = math.radians(a[0]); p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0]); dl = math.radians(b[1] - a[1])
    h = math.sin(dp/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl/2)**2
    return R * 2 * math.asin(math.sqrt(h))


def main():
    out_path = REPO_ROOT / "access_point_preview.html"
    # Build a fresh mini-mosaic so the raster bounds are accurate.
    raster_url = None
    s, w, n, e = PREVIEW_BBOX
    if KMZ_PATH.exists():
        from overlay_osm_jeffs import _build_raster_mosaic
        try:
            s, w, n, e = _build_raster_mosaic(KMZ_PATH, PREVIEW_BBOX, 7, RASTER_JPG)
            raster_url = RASTER_JPG.name
        except Exception as exc:
            print(f"Mosaic generation failed ({exc}); rendering without raster.",
                  file=sys.stderr)
    else:
        print(f"KMZ not found at {KMZ_PATH}; rendering without raster.",
              file=sys.stderr)
    html = (HTML
        .replace("{current_gps}", json.dumps(CURRENT))
        .replace("{proposed_gps}", json.dumps(PROPOSED))
        .replace("{distance_m:.0f}", f"{_haversine_m(CURRENT, PROPOSED):.0f}")
        .replace("{raster_bounds}", json.dumps([[s, w], [n, e]]))
        .replace("{raster_url}",
                 json.dumps(raster_url) if raster_url else "null"))
    out_path.write_text(html)
    print(f"Wrote {out_path}")
    print(f"  current:  {CURRENT}")
    print(f"  proposed: {PROPOSED}")
    print(f"  distance: {_haversine_m(CURRENT, PROPOSED):.0f} m")
    if raster_url:
        print(f"  raster:   {raster_url} (using existing overlay raster)")
    print()
    print("Open via: python3 -m http.server  →  "
          f"http://localhost:8000/{out_path.name}")


if __name__ == "__main__":
    main()
