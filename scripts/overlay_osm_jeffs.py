"""
Render an HTML map overlaying OSM polygons, Jeff's Maps polygons, Jeff's
raster mosaic, and a trip's waypoints + route — all GPS-aligned and
toggleable via Leaflet's layer control.

Usage:
    python3 scripts/overlay_osm_jeffs.py
    python3 scripts/overlay_osm_jeffs.py --bbox 46.00,-81.45,46.10,-81.30
    python3 scripts/overlay_osm_jeffs.py --kmz path/to/jeffs.kmz \\
        --bbox 46.00,-81.45,46.10,-81.30
    python3 scripts/overlay_osm_jeffs.py --trip trips/killarney-2026-05/ \\
        --kmz path/to/jeffs.kmz --bbox 46.00,-81.45,46.10,-81.32

Layers (each toggleable in the layer control top-right):
  - OSM named lakes:         blue outline + fill, clickable
  - Jeff's named lakes:      red outline + fill
  - Jeff's unnamed lakes:    orange dashed (off by default — toggle to declutter)
  - Jeff's raster mosaic:    underlay of the source PNG/JPG tiles aligned to
                             their KMZ LatLonBox bounds (only with --kmz)
  - Trip waypoints:          access-point + per-night markers from --trip
  - Trip route (paddle):     paddle segments — blue solid lines
  - Trip route (portage):    portage segments — orange solid lines
  - Trip route (approx):     approx-fallback legs — red dashed lines

The output is a single HTML file plus, when --kmz is provided, a sibling JPG
of the mosaic. Open the HTML via `python3 -m http.server` so the JPG loads.

This is a debugging / inspection tool. It doesn't write any cache or modify
any other file.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Make jeffs_extractor importable when running this script.
sys.path.insert(0, str(REPO_ROOT))


def _bbox_of(polygon):
    if not polygon:
        return None
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    return (min(lats), min(lons), max(lats), max(lons))


def _polygon_intersects_bbox(polygon, bbox):
    """bbox = (s, w, n, e). Polygon is list of [lat, lon]. Crude AABB test."""
    if bbox is None:
        return True
    poly_bbox = _bbox_of(polygon)
    if poly_bbox is None:
        return False
    ps, pw, pn, pe = poly_bbox
    s, w, n, e = bbox
    return not (pn < s or ps > n or pe < w or pw > e)


def _to_geojson_feature(lake, props_extra=None):
    """A lake dict {name?, polygon: [[lat,lon],...], centroid: [lat,lon]} → GeoJSON Feature."""
    coords = [[lon, lat] for lat, lon in lake["polygon"]]  # GeoJSON is lon,lat
    props = {"name": lake.get("name", "(unnamed)")}
    if props_extra:
        props.update(props_extra)
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


def _collect_features(cache_path: Path, source_label: str, bbox):
    """Read a cache JSON and split lakes into named / unnamed feature collections."""
    if not cache_path.exists():
        return [], []
    data = json.loads(cache_path.read_text())
    named = []
    unnamed = []
    for lake in data.get("lakes", []):
        polygon = lake.get("polygon") or []
        if not polygon:
            continue
        if not _polygon_intersects_bbox(polygon, bbox):
            continue
        feat = _to_geojson_feature(lake, {"source": source_label})
        if "name" in lake and lake["name"]:
            named.append(feat)
        else:
            unnamed.append(feat)
    return named, unnamed


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OSM + Jeff's overlay</title>
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
                   margin-right: 0.4rem; vertical-align: middle;
                   border: 1.5px solid; }
  .legend .osm  { background: rgba(33,150,243,0.25); border-color: #1976d2; }
  .legend .jeffs { background: rgba(244,67,54,0.25); border-color: #c62828; }
  .legend .unnamed { background: rgba(255,152,0,0.18); border-color: #f57c00;
                     border-style: dashed; }
  .legend .raster { background: #999; border-color: #555; }
  .legend .waypoint { background: #6b1fb1; border-color: #4a0d8a;
                      border-radius: 50%; }
  .legend .paddle { background: #1565c0; border-color: #0d47a1; }
  .legend .portage { background: #ef6c00; border-color: #b53d00; }
  .legend .approx { background: #c62828; border-color: #8a0000;
                    border-style: dashed; }
  .stats { position: absolute; top: 1rem; right: 1rem; z-index: 1000;
           background: white; padding: 0.6rem 0.8rem; border-radius: 6px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.2); font-size: 0.85rem;
           line-height: 1.5; }
  .opacity-row { margin-top: 0.4rem; display: flex; align-items: center;
                 gap: 0.4rem; }
  .opacity-row label { font-size: 0.8rem; color: #555; }
  .opacity-row input { width: 100px; }
</style>
</head>
<body>
<div id="map"></div>
<div class="legend">
  <div><span class="legend-swatch osm"></span>OSM named lakes</div>
  <div><span class="legend-swatch jeffs"></span>Jeff's named lakes</div>
  <div><span class="legend-swatch unnamed"></span>Jeff's unnamed lakes</div>
  __RASTER_LEGEND__
  __TRIP_LEGEND__
  __RASTER_OPACITY_CONTROL__
</div>
<div class="stats">
  OSM named: __OSM_COUNT__ · Jeff's named: __JEFFS_NAMED_COUNT__ · Jeff's unnamed: __JEFFS_UNNAMED_COUNT__
</div>
<script>
const osmFeatures = __OSM_GEOJSON__;
const jeffsNamedFeatures = __JEFFS_NAMED_GEOJSON__;
const jeffsUnnamedFeatures = __JEFFS_UNNAMED_GEOJSON__;
const rasterUrl = __RASTER_URL__;
const rasterBounds = __RASTER_BOUNDS__;
const tripMarkers = __TRIP_MARKERS__;
const tripSegments = __TRIP_SEGMENTS__;
const center = __MAP_CENTER__;

const map = L.map('map', { center: center, zoom: 11 });
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors',
  maxZoom: 18
}).addTo(map);

function popupName(feature, layer) {
  const props = feature.properties || {};
  const name = props.name || '(unnamed)';
  const src = props.source ? ' [' + props.source + ']' : '';
  layer.bindPopup(name + src);
}

const osmLayer = L.geoJSON(osmFeatures, {
  style: { color: '#1976d2', weight: 1.5, fillColor: '#42a5f5', fillOpacity: 0.25 },
  onEachFeature: popupName,
}).addTo(map);

const jeffsNamedLayer = L.geoJSON(jeffsNamedFeatures, {
  style: { color: '#c62828', weight: 1.5, fillColor: '#ef5350', fillOpacity: 0.25 },
  onEachFeature: popupName,
}).addTo(map);

const jeffsUnnamedLayer = L.geoJSON(jeffsUnnamedFeatures, {
  style: { color: '#f57c00', weight: 1, fillColor: '#ffb74d', fillOpacity: 0.18,
           dashArray: '4 4' },
  onEachFeature: popupName,
});  // off by default — user toggles via layer control

const layerOverlays = {
  'OSM named lakes': osmLayer,
  "Jeff's named lakes": jeffsNamedLayer,
  "Jeff's unnamed lakes": jeffsUnnamedLayer,
};

let rasterLayer = null;
if (rasterUrl && rasterBounds) {
  rasterLayer = L.imageOverlay(rasterUrl, rasterBounds, { opacity: 0.7 });
  rasterLayer.addTo(map);
  layerOverlays["Jeff's raster"] = rasterLayer;
  // Live opacity slider tied to the raster.
  const slider = document.getElementById('raster-opacity');
  if (slider) {
    slider.addEventListener('input', function(ev) {
      rasterLayer.setOpacity(parseFloat(ev.target.value));
    });
  }
}

// --- Trip layers (waypoints + segmented route) ---
let tripWaypointLayer = null;
let tripPaddleLayer = null;
let tripPortageLayer = null;
let tripApproxLayer = null;

if (tripMarkers && tripMarkers.length) {
  tripWaypointLayer = L.layerGroup(tripMarkers.map(function(m) {
    const isAccess = m.kind === 'access';
    return L.circleMarker([m.lat, m.lon], {
      radius: isAccess ? 9 : 7,
      color: isAccess ? '#000' : '#4a0d8a',
      weight: 2,
      fillColor: isAccess ? '#ffeb3b' : '#9c27b0',
      fillOpacity: 0.9,
    }).bindPopup(m.label || '(unnamed)');
  })).addTo(map);
  layerOverlays['Trip waypoints'] = tripWaypointLayer;
}

// Centripetal Catmull-Rom interpolation. Standard Catmull-Rom (uniform
// parameterization) tends to overshoot — the curve can bulge outside the
// straight line between two consecutive vertices, which falsely makes the
// rendered line look like it crosses land. Centripetal (α=0.5) is the
// well-known fix: smooth, passes through all original vertices, and
// guarantees no overshoot or self-intersection.
function _knotInterval(p0, p1, alpha) {
  const dx = p1[0] - p0[0];
  const dy = p1[1] - p0[1];
  return Math.pow(Math.sqrt(dx * dx + dy * dy), alpha);
}

function _centripetalCatmullRom(p0, p1, p2, p3, t /* in [0,1] */) {
  const ALPHA = 0.5;
  const t0 = 0;
  const t1 = t0 + _knotInterval(p0, p1, ALPHA);
  const t2 = t1 + _knotInterval(p1, p2, ALPHA);
  const t3 = t2 + _knotInterval(p2, p3, ALPHA);
  // Map t in [0,1] onto [t1, t2].
  const tEval = t1 + t * (t2 - t1);

  const epsilon = 1e-12;
  const a1 = [
    (t1 - tEval) / Math.max(t1 - t0, epsilon) * p0[0]
      + (tEval - t0) / Math.max(t1 - t0, epsilon) * p1[0],
    (t1 - tEval) / Math.max(t1 - t0, epsilon) * p0[1]
      + (tEval - t0) / Math.max(t1 - t0, epsilon) * p1[1],
  ];
  const a2 = [
    (t2 - tEval) / Math.max(t2 - t1, epsilon) * p1[0]
      + (tEval - t1) / Math.max(t2 - t1, epsilon) * p2[0],
    (t2 - tEval) / Math.max(t2 - t1, epsilon) * p1[1]
      + (tEval - t1) / Math.max(t2 - t1, epsilon) * p2[1],
  ];
  const a3 = [
    (t3 - tEval) / Math.max(t3 - t2, epsilon) * p2[0]
      + (tEval - t2) / Math.max(t3 - t2, epsilon) * p3[0],
    (t3 - tEval) / Math.max(t3 - t2, epsilon) * p2[1]
      + (tEval - t2) / Math.max(t3 - t2, epsilon) * p3[1],
  ];
  const b1 = [
    (t2 - tEval) / Math.max(t2 - t0, epsilon) * a1[0]
      + (tEval - t0) / Math.max(t2 - t0, epsilon) * a2[0],
    (t2 - tEval) / Math.max(t2 - t0, epsilon) * a1[1]
      + (tEval - t0) / Math.max(t2 - t0, epsilon) * a2[1],
  ];
  const b2 = [
    (t3 - tEval) / Math.max(t3 - t1, epsilon) * a2[0]
      + (tEval - t1) / Math.max(t3 - t1, epsilon) * a3[0],
    (t3 - tEval) / Math.max(t3 - t1, epsilon) * a2[1]
      + (tEval - t1) / Math.max(t3 - t1, epsilon) * a3[1],
  ];
  return [
    (t2 - tEval) / Math.max(t2 - t1, epsilon) * b1[0]
      + (tEval - t1) / Math.max(t2 - t1, epsilon) * b2[0],
    (t2 - tEval) / Math.max(t2 - t1, epsilon) * b1[1]
      + (tEval - t1) / Math.max(t2 - t1, epsilon) * b2[1],
  ];
}

function smoothPolyline(points, stepsPerSegment) {
  if (!Array.isArray(points) || points.length < 3) return points;
  const steps = stepsPerSegment || 12;
  const out = [points[0]];
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || points[i + 1];
    for (let s = 1; s <= steps; s++) {
      out.push(_centripetalCatmullRom(p0, p1, p2, p3, s / steps));
    }
  }
  return out;
}

if (tripSegments && tripSegments.length) {
  const paddleLines = [];
  const portageLines = [];
  const approxLines = [];
  tripSegments.forEach(function(s) {
    const rawCoords = (s.geometry || []).filter(function(p) {
      return Array.isArray(p) && p.length === 2;
    });
    if (rawCoords.length < 2) return;
    // Render as smoothed spline. Approx segments stay straight (only
    // 2 points anyway, and they're "we don't know the route" markers).
    const coords = (s.kind === 'approx') ? rawCoords : smoothPolyline(rawCoords);
    const popup = s.from + ' → ' + s.to + ' (' + s.distance_km + ' km)';
    if (s.kind === 'paddle') {
      paddleLines.push(L.polyline(coords, {
        color: '#0d47a1', weight: 4, opacity: 0.85,
        smoothFactor: 0,  // use our own smoothing, not Leaflet's simplifier
      }).bindPopup(popup));
    } else if (s.kind === 'portage') {
      portageLines.push(L.polyline(coords, {
        color: '#b53d00', weight: 4, opacity: 0.95,
        smoothFactor: 0,
      }).bindPopup(popup));
    } else if (s.kind === 'approx') {
      approxLines.push(L.polyline(coords, {
        color: '#c62828', weight: 3, opacity: 0.85,
        dashArray: '8 6',
      }).bindPopup(popup + ' (approx)'));
    }
  });
  if (paddleLines.length) {
    tripPaddleLayer = L.layerGroup(paddleLines).addTo(map);
    layerOverlays['Trip route — paddle'] = tripPaddleLayer;
  }
  if (portageLines.length) {
    tripPortageLayer = L.layerGroup(portageLines).addTo(map);
    layerOverlays['Trip route — portage'] = tripPortageLayer;
  }
  if (approxLines.length) {
    tripApproxLayer = L.layerGroup(approxLines).addTo(map);
    layerOverlays['Trip route — approx'] = tripApproxLayer;
  }
}

L.control.layers(null, layerOverlays, { collapsed: false }).addTo(map);

// Fit bounds to whatever's loaded.
const all = [osmLayer.getBounds(), jeffsNamedLayer.getBounds()];
if (rasterLayer) all.push(L.latLngBounds(rasterBounds));
if (tripWaypointLayer) {
  // layerGroup doesn't have getBounds; expand from markers.
  tripMarkers.forEach(function(m) {
    all.push(L.latLngBounds([[m.lat, m.lon], [m.lat, m.lon]]));
  });
}
const valid = all.filter(b => b.isValid());
if (valid.length) {
  const merged = valid.reduce((a, b) => a.extend(b));
  map.fitBounds(merged, { padding: [30, 30] });
}
</script>
</body>
</html>
"""


def _load_trip_route(trip_dir: Path) -> dict:
    """Load a trip and return {'markers': [...], 'segments': [...]}.

    Reuses build_trip.load_trip + osm_data.load_killarney_features +
    route_engine.build_route so the overlay matches what the trip page
    renders.
    """
    import build_trip
    import osm_data
    import route_engine
    import gpx_library

    trip = build_trip.load_trip(trip_dir)
    fm = trip.get("frontmatter") or {}
    nights = fm.get("nights") or []
    access_point = fm.get("access_point")
    if not (nights and access_point):
        return {"markers": [], "segments": []}
    osm = osm_data.load_killarney_features()
    library = gpx_library.load_library_index(
        Path(__file__).resolve().parent.parent / "routes" / "killarney" / "library"
    )
    route = route_engine.build_route(
        nights=nights, access_point=access_point, osm=osm, library=library,
    )
    return {
        "markers": route.get("markers") or [],
        "segments": route.get("segments") or [],
    }


def _build_raster_mosaic(kmz_path: Path, bbox, zoom: int, out_jpg: Path) -> tuple:
    """Walk the KMZ, build a mosaic at the given zoom, save as JPG.

    Returns (south, west, north, east) — the GPS bounds of the saved mosaic.
    Reuses jeffs_extractor.walk_kmz / build_mosaic to avoid duplicating logic.

    walk_kmz auto-cleans its temp dir when its generator is exhausted, which
    breaks build_mosaic (still needs the image files). Pass our own
    extract_dir so cleanup is local and deferred until after build_mosaic.
    """
    import shutil
    import tempfile
    import cv2
    from jeffs_extractor import walk_kmz, build_mosaic

    extract_dir = Path(tempfile.mkdtemp(prefix="jeffs_overlay_"))
    try:
        tiles = list(walk_kmz(kmz_path, bbox=bbox, zoom_level=zoom,
                              extract_dir=extract_dir))
        if not tiles:
            raise RuntimeError(
                f"No tiles found at zoom {zoom} intersecting bbox {bbox}. "
                "Try a different zoom level or a different bbox."
            )
        print(f"  walking KMZ at zoom {zoom}: {len(tiles)} tiles",
              file=sys.stderr)
        mosaic, mosaic_bounds = build_mosaic(tiles)  # (n, s, e, w)
        n, s, e, w = mosaic_bounds
        # Save as JPG with moderate quality (small file, decent fidelity).
        cv2.imwrite(str(out_jpg), mosaic, [cv2.IMWRITE_JPEG_QUALITY, 78])
        print(f"  mosaic saved: {out_jpg.name} "
              f"({mosaic.shape[1]}x{mosaic.shape[0]} px, "
              f"{out_jpg.stat().st_size // 1024} KB)", file=sys.stderr)
        return (s, w, n, e)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def _features_center(features):
    """Rough center of a list of GeoJSON polygon features (lat, lon)."""
    lats = []
    lons = []
    for f in features:
        for ring in f["geometry"]["coordinates"]:
            for lon, lat in ring:
                lats.append(lat)
                lons.append(lon)
    if not lats:
        return [46.05, -81.40]  # fallback: roughly Killarney center
    return [sum(lats) / len(lats), sum(lons) / len(lons)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm-cache",
                        default=str(REPO_ROOT / "osm_killarney_cache.json"))
    parser.add_argument("--jeffs-cache",
                        default=str(REPO_ROOT / "jeffs_killarney_cache.json"))
    parser.add_argument("--bbox",
                        help="Optional 'south,west,north,east' filter — show "
                             "only polygons that intersect this bbox. Useful "
                             "for taking a smaller bite of the map.")
    parser.add_argument("--kmz",
                        help="Optional KMZ path. When provided, builds a "
                             "mosaic JPG of the raster tiles intersecting "
                             "--bbox at --zoom-raster and adds it as a "
                             "toggleable Leaflet imageOverlay.")
    parser.add_argument("--zoom-raster", type=int, default=6,
                        help="Pyramid level for the raster mosaic (default 6).")
    parser.add_argument("--trip",
                        help="Optional trip directory. When provided, the "
                             "trip's waypoints and route segments are added "
                             "as toggleable layers.")
    parser.add_argument("--out", default=str(REPO_ROOT / "jeffs_osm_overlay.html"))
    args = parser.parse_args(argv)

    bbox = None
    if args.bbox:
        parts = [float(x) for x in args.bbox.split(",")]
        if len(parts) != 4:
            print("--bbox must have 4 comma-separated values "
                  "(south,west,north,east)")
            return 2
        bbox = tuple(parts)

    # OSM cache has ALL lakes named (the Overpass query filters by name); we
    # treat them all as "named" for layering. Read them directly here rather
    # than reusing _collect_features, since OSM polygons may not have a
    # "name" key with the same defaulting behavior as Jeff's.
    osm_named = []
    osm_path = Path(args.osm_cache)
    if osm_path.exists():
        osm = json.loads(osm_path.read_text())
        for lake in osm.get("lakes", []):
            polygon = lake.get("polygon") or []
            if not polygon:
                continue
            if not _polygon_intersects_bbox(polygon, bbox):
                continue
            osm_named.append(_to_geojson_feature(lake, {"source": "OSM"}))

    jeffs_named, jeffs_unnamed = _collect_features(
        Path(args.jeffs_cache), "Jeff's", bbox,
    )

    out_path = Path(args.out)
    raster_url_js = "null"
    raster_bounds_js = "null"
    raster_legend = ""
    raster_opacity_html = ""
    if args.kmz:
        # Mosaic JPG goes next to the HTML so a relative URL works.
        jpg_name = out_path.stem + "_raster.jpg"
        jpg_path = out_path.parent / jpg_name
        mosaic_bbox = bbox if bbox else None
        if mosaic_bbox is None:
            print("Note: --kmz without --bbox will mosaic the full map area "
                  "(slow, ~80MP+). Pass a --bbox to take a smaller bite.",
                  file=sys.stderr)
            mosaic_bbox = (45.92, -81.60, 46.12, -81.25)  # default to Killarney
        s, w, n, e = _build_raster_mosaic(
            Path(args.kmz), mosaic_bbox, args.zoom_raster, jpg_path,
        )
        raster_url_js = json.dumps(jpg_name)
        # Leaflet imageOverlay bounds: [[south, west], [north, east]].
        raster_bounds_js = json.dumps([[s, w], [n, e]])
        raster_legend = (
            '<div><span class="legend-swatch raster"></span>'
            "Jeff's raster mosaic</div>"
        )
        raster_opacity_html = (
            '<div class="opacity-row">'
            '<label for="raster-opacity">Raster opacity</label>'
            '<input id="raster-opacity" type="range" min="0" max="1" '
            'step="0.05" value="0.7"></div>'
        )

    trip_markers = []
    trip_segments = []
    trip_legend = ""
    if args.trip:
        trip_data = _load_trip_route(Path(args.trip))
        trip_markers = trip_data["markers"]
        trip_segments = trip_data["segments"]
        if trip_markers or trip_segments:
            trip_legend = (
                '<div><span class="legend-swatch waypoint"></span>'
                'Trip waypoints</div>'
                '<div><span class="legend-swatch paddle"></span>'
                'Trip route — paddle</div>'
                '<div><span class="legend-swatch portage"></span>'
                'Trip route — portage</div>'
                '<div><span class="legend-swatch approx"></span>'
                'Trip route — approx</div>'
            )

    center = _features_center(osm_named + jeffs_named + jeffs_unnamed)

    html = (
        _HTML_TEMPLATE
        .replace("__OSM_GEOJSON__", json.dumps(osm_named))
        .replace("__JEFFS_NAMED_GEOJSON__", json.dumps(jeffs_named))
        .replace("__JEFFS_UNNAMED_GEOJSON__", json.dumps(jeffs_unnamed))
        .replace("__RASTER_URL__", raster_url_js)
        .replace("__RASTER_BOUNDS__", raster_bounds_js)
        .replace("__RASTER_LEGEND__", raster_legend)
        .replace("__TRIP_LEGEND__", trip_legend)
        .replace("__RASTER_OPACITY_CONTROL__", raster_opacity_html)
        .replace("__TRIP_MARKERS__", json.dumps(trip_markers))
        .replace("__TRIP_SEGMENTS__", json.dumps(trip_segments))
        .replace("__MAP_CENTER__", json.dumps(center))
        .replace("__OSM_COUNT__", str(len(osm_named)))
        .replace("__JEFFS_NAMED_COUNT__", str(len(jeffs_named)))
        .replace("__JEFFS_UNNAMED_COUNT__", str(len(jeffs_unnamed)))
    )
    out_path.write_text(html)
    print(f"Wrote {out_path}")
    print(f"  OSM named lakes: {len(osm_named)}")
    print(f"  Jeff's named lakes: {len(jeffs_named)}")
    print(f"  Jeff's unnamed lakes: {len(jeffs_unnamed)}")
    if args.trip:
        print(f"  Trip waypoints: {len(trip_markers)}")
        print(f"  Trip segments:  {len(trip_segments)}")
    if args.kmz:
        print(f"  Raster mosaic:    {jpg_name} (zoom {args.zoom_raster})")
        print(f"  Open via:         python3 -m http.server  →  "
              f"http://localhost:8000/{out_path.name}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
