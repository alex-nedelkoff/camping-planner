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
<title>Killarney · field overlay</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..700&family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  /* ───── field cartographer's notebook ───── */
  :root {
    --ink:           #1f2a23;
    --ink-soft:      #4a5d4f;
    --ink-faint:     #8a8a78;
    --rule:          #cbbf9f;
    --rule-soft:     #e1d6b8;
    --parchment:     #f5efe1;
    --parchment-deep:#ece2c9;
    --rust:          #a8451f;
    --rust-bright:   #c66633;
    --slate:         #3a5666;
    --moss:          #4f6644;
    --shadow:        0 1px 0 rgba(31, 42, 35, 0.06),
                     0 4px 14px rgba(31, 42, 35, 0.08),
                     0 18px 36px -10px rgba(31, 42, 35, 0.14);
  }

  html, body, #map { height: 100%; margin: 0; }
  #map { background: #ede2c9; }  /* parchment-deep — visible when OSM tiles off */
  body {
    font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--ink);
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }

  /* ───── Unified left side panel ───── */
  .side-panel {
    position: absolute;
    top: 1rem; left: 1rem; z-index: 1000;
    width: 296px;
    max-height: calc(100vh - 2rem);
    display: flex; flex-direction: column;
    background: var(--parchment);
    border: 1px solid var(--rule);
    border-radius: 2px;
    box-shadow: var(--shadow);
    color: var(--ink);
    overflow: hidden;
  }
  .side-panel header {
    padding: 0.95rem 1.05rem 0.85rem;
    border-bottom: 1px solid var(--rule);
    background:
      linear-gradient(180deg,
        rgba(31, 42, 35, 0) 0%,
        rgba(31, 42, 35, 0.025) 100%),
      var(--parchment);
  }
  .panel-title {
    font-family: 'Fraunces', Georgia, serif;
    font-weight: 500;
    font-size: 1.18rem;
    letter-spacing: -0.005em;
    color: var(--ink);
    margin: 0;
    display: flex; align-items: baseline; gap: 0.5rem;
  }
  .panel-title::before {
    content: "▲";
    color: var(--rust);
    font-size: 0.7em;
  }
  .panel-sub {
    font-family: 'Fraunces', Georgia, serif;
    font-style: italic;
    font-size: 0.72rem;
    letter-spacing: 0.04em;
    color: var(--ink-faint);
    margin-top: 0.2rem;
  }
  .panel-body {
    flex: 1 1 auto;
    overflow-y: auto;
  }
  .panel-body::-webkit-scrollbar { width: 6px; }
  .panel-body::-webkit-scrollbar-track { background: transparent; }
  .panel-body::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 2px; }

  .panel-section {
    padding: 0.75rem 1.05rem 0.85rem;
    border-bottom: 1px solid var(--rule-soft);
  }
  .panel-section:last-child { border-bottom: none; }
  .section-heading {
    display: flex; justify-content: space-between; align-items: baseline;
    font-family: 'Fraunces', Georgia, serif;
    font-style: italic;
    font-weight: 500;
    font-size: 0.66rem;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    color: var(--ink-soft);
    margin: 0 0 0.55rem;
  }
  .section-heading .count {
    font-family: 'JetBrains Mono', monospace;
    font-style: normal;
    font-size: 0.65rem;
    letter-spacing: 0.05em;
    color: var(--ink-faint);
  }

  /* Counts list */
  .counts-row {
    display: flex; justify-content: space-between;
    padding: 0.13rem 0;
    font-size: 0.76rem;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1;
  }
  .counts-row .key { color: var(--ink-soft); }
  .counts-row .val { color: var(--ink); font-weight: 600; }

  /* Toggle rows — used for both base radios and overlay checkboxes. */
  .toggle-row {
    display: flex; align-items: center;
    gap: 0.55rem;
    padding: 0.22rem 0;
    cursor: pointer;
    font-size: 0.76rem;
    color: var(--ink);
    transition: color 0.15s ease;
    user-select: none;
  }
  .toggle-row:hover { color: var(--rust); }
  .toggle-row input[type="checkbox"],
  .toggle-row input[type="radio"] {
    accent-color: var(--rust);
    margin: 0;
    flex-shrink: 0;
  }
  .toggle-row .label {
    flex: 1;
    line-height: 1.4;
  }
  .toggle-row .count {
    color: var(--ink-faint);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    letter-spacing: 0.01em;
  }
  /* Dim a row when its checkbox is unchecked. */
  .toggle-row:has(input:not(:checked)) .label,
  .toggle-row:has(input:not(:checked)) .count { color: var(--ink-faint); }
  .toggle-row:has(input:not(:checked)) .swatch { opacity: 0.45; }

  .swatch {
    display: inline-block;
    width: 13px; height: 13px;
    border: 1.5px solid;
    flex-shrink: 0;
  }
  /* Swatch colors match drawn layers — semantic mapping. */
  .swatch.osm         { background: rgba(58,86,102,0.28);  border-color: #3a5666; }
  .swatch.jeffs       { background: rgba(168,69,31,0.22);  border-color: #a8451f; }
  .swatch.unnamed     { background: rgba(198,102,51,0.14); border-color: #c66633;
                        border-style: dashed; }
  .swatch.canvec      { background: rgba(0,96,100,0.28);   border-color: #006064; }
  .swatch.raster      { background: #b4a780; border-color: #6b6147; }
  .swatch.waypoint    { background: #6b1fb1; border-color: #4a0d8a;
                        border-radius: 50%; }
  .swatch.paddle      { background: #1565c0; border-color: #0d47a1; }
  .swatch.portage     { background: #ef6c00; border-color: #b53d00; }
  .swatch.approx      { background: #c62828; border-color: #8a0000;
                        border-style: dashed; }
  .swatch.gpx-portage { background: #7b1fa2; border-color: #4a148c; }
  .swatch.osm-portage { background: #fb8c00; border-color: #e65100;
                        border-style: dashed; }
  .swatch.gpx-campsite { background: #43a047; border-color: #1b5e20;
                         border-radius: 50%; }
  .swatch.hiking      { background: #00897b; border-color: #004d40;
                        border-style: dotted; }
  .swatch.tile        { background:
                          repeating-linear-gradient(45deg,
                            #cfd8d8 0, #cfd8d8 3px,
                            #aab8b8 3px, #aab8b8 6px);
                        border-color: #6e7a7a; }
  .swatch.none        { background: var(--parchment-deep);
                        border-color: var(--rule); }

  /* Inline opacity slider, indented under the row it belongs to. */
  .opacity-inline {
    margin: 0.15rem 0 0.4rem 1.7rem;
    display: flex; align-items: center; gap: 0.5rem;
  }
  .opacity-inline label {
    font-family: 'Fraunces', Georgia, serif;
    font-style: italic;
    font-size: 0.68rem;
    letter-spacing: 0.04em;
    color: var(--ink-faint);
    flex-shrink: 0;
  }
  .opacity-inline input[type=range] {
    flex: 1;
    accent-color: var(--rust);
  }

  /* Manual route drawer */
  .draw-controls {
    display: flex; flex-direction: column; gap: 0.4rem;
    margin-top: 0.4rem;
  }
  .draw-btn {
    padding: 0.45rem 0.7rem;
    font-family: 'Fraunces', Georgia, serif;
    font-style: italic;
    font-size: 0.78rem;
    color: var(--ink);
    background: var(--parchment);
    border: 1px solid var(--rule);
    border-radius: 2px;
    cursor: pointer;
    user-select: none;
    text-align: left;
    transition: background 0.15s ease, color 0.15s ease;
  }
  .draw-btn:hover { background: var(--parchment-deep); color: var(--rust); }
  .draw-btn.active {
    background: #6b3a8a;
    color: #f5efe1;
    border-color: #4a1f6b;
  }
  .draw-btn.active:hover { color: #f5efe1; }
  .draw-stats {
    font-size: 0.72rem;
    color: var(--ink-soft);
    line-height: 1.45;
    padding: 0.15rem 0;
    font-variant-numeric: tabular-nums;
  }
  .draw-stats .km {
    font-family: 'JetBrains Mono', monospace;
    color: var(--ink);
    font-weight: 600;
  }
  .draw-row {
    display: flex; gap: 0.4rem;
  }
  .draw-row .draw-btn { flex: 1; }
  #map.drawing { cursor: crosshair; }
  .draw-snap-row {
    display: flex; align-items: flex-start; gap: 0.45rem;
    font-size: 0.72rem;
    line-height: 1.35;
    color: var(--ink-soft);
    cursor: pointer;
    user-select: none;
    padding: 0.1rem 0;
  }
  .draw-snap-row input { accent-color: var(--rust); margin-top: 2px; flex-shrink: 0; }
  .snap-target { color: var(--rust); font-style: italic; }
  .draw-label-input {
    width: 100%;
    box-sizing: border-box;
    padding: 0.4rem 0.55rem;
    font-family: 'DM Sans', sans-serif;
    font-size: 0.78rem;
    border: 1px solid var(--rule);
    border-radius: 2px;
    background: var(--parchment);
    color: var(--ink);
  }
  .draw-label-input:focus {
    outline: none;
    border-color: var(--rust);
    box-shadow: 0 0 0 2px rgba(168, 69, 31, 0.15);
  }
  .saved-routes {
    margin-top: 0.65rem;
    display: flex; flex-direction: column; gap: 0.35rem;
  }
  .saved-routes:empty::before {
    content: "No saved routes yet.";
    color: var(--ink-faint);
    font-style: italic;
    font-size: 0.72rem;
  }
  .saved-route {
    display: flex; align-items: center; gap: 0.45rem;
    padding: 0.35rem 0.45rem;
    background: var(--parchment-deep);
    border: 1px solid var(--rule-soft);
    border-radius: 2px;
    font-size: 0.74rem;
  }
  .saved-route .sr-swatch {
    width: 12px; height: 12px;
    border: 1.5px solid;
    flex-shrink: 0;
  }
  .saved-route .sr-check { accent-color: var(--rust); margin: 0; flex-shrink: 0; }
  .saved-route .sr-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ink);
  }
  .saved-route .sr-dist {
    color: var(--ink-soft);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
  }
  .saved-route .sr-act {
    background: none;
    border: none;
    color: var(--ink-faint);
    cursor: pointer;
    padding: 0.1rem 0.3rem;
    font-family: 'Fraunces', serif;
    font-style: italic;
    font-size: 0.78rem;
    line-height: 1;
    border-radius: 2px;
  }
  .saved-route .sr-act:hover { color: var(--rust); background: var(--parchment); }

  /* Layer info — trigger button (footer of side panel) + fly-out window. */
  .info-trigger {
    cursor: pointer;
    padding: 0.75rem 1.05rem;
    font-family: 'Fraunces', Georgia, serif;
    font-style: italic;
    font-size: 0.88rem;
    color: var(--ink);
    background: var(--parchment);
    border: none;
    border-top: 1px solid var(--rule);
    display: flex; align-items: center; gap: 0.5rem;
    width: 100%;
    text-align: left;
    user-select: none;
    transition: background 0.15s ease, color 0.15s ease;
  }
  .info-trigger:hover { background: var(--parchment-deep); color: var(--rust); }
  .info-trigger .glyph {
    color: var(--rust);
    font-weight: 600;
    font-style: normal;
  }
  .info-trigger .indicator {
    margin-left: auto;
    font-family: 'Fraunces', serif;
    font-style: normal;
    font-size: 1.05rem;
    line-height: 1;
    color: var(--rust);
    transition: transform 0.25s cubic-bezier(0.2, 0.7, 0.2, 1);
    display: inline-block;
  }
  .info-trigger[aria-expanded="true"] .indicator { transform: rotate(45deg); }

  /* Fly-out info window — slides in to the right of the main side panel. */
  .info-flyout {
    position: absolute;
    top: 1rem;
    /* main panel: 1rem margin + 296px width + 0.6rem gap */
    left: calc(1rem + 296px + 0.6rem);
    width: 340px;
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
    z-index: 999;
    background: var(--parchment);
    border: 1px solid var(--rule);
    border-radius: 2px;
    box-shadow: var(--shadow);
    padding: 1.05rem 1.15rem 1.2rem;
    color: var(--ink);
    transform: translateX(-12px);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.22s cubic-bezier(0.2, 0.7, 0.2, 1),
                transform 0.22s cubic-bezier(0.2, 0.7, 0.2, 1);
  }
  .info-flyout.open {
    opacity: 1;
    transform: translateX(0);
    pointer-events: auto;
  }
  .info-flyout::-webkit-scrollbar { width: 6px; }
  .info-flyout::-webkit-scrollbar-track { background: transparent; }
  .info-flyout::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 2px; }

  .info-flyout h3 {
    font-family: 'Fraunces', Georgia, serif;
    font-weight: 500;
    font-style: italic;
    font-size: 1.05rem;
    letter-spacing: -0.005em;
    color: var(--ink);
    margin: 0 0 0.75rem;
    padding: 0 1.8rem 0.6rem 0;
    border-bottom: 1px solid var(--rule-soft);
  }
  .flyout-close {
    position: absolute;
    top: 0.55rem;
    right: 0.7rem;
    background: none;
    border: none;
    color: var(--ink-faint);
    font-size: 1.35rem;
    line-height: 1;
    cursor: pointer;
    padding: 0.25rem 0.4rem;
    border-radius: 2px;
    transition: color 0.15s ease, background 0.15s ease;
  }
  .flyout-close:hover {
    color: var(--rust);
    background: var(--parchment-deep);
  }
  .info-flyout dl { margin: 0; }
  .info-flyout dt {
    font-weight: 600;
    font-size: 0.76rem;
    color: var(--ink);
    margin-top: 0.85rem;
  }
  .info-flyout dt:first-of-type { margin-top: 0; }
  .info-flyout dd {
    font-size: 0.74rem;
    line-height: 1.55;
    color: var(--ink-soft);
    margin: 0.18rem 0 0;
  }
  .info-flyout code {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.71rem;
    background: var(--parchment-deep);
    padding: 0.05rem 0.32rem;
    border-radius: 2px;
    color: var(--ink);
    letter-spacing: -0.005em;
  }

  /* Leaflet popups + attribution. */
  .leaflet-popup-content-wrapper {
    background: var(--parchment) !important;
    color: var(--ink) !important;
    border-radius: 2px !important;
    box-shadow: var(--shadow) !important;
    border: 1px solid var(--rule);
  }
  .leaflet-popup-content {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.78rem !important;
    line-height: 1.5 !important;
    margin: 0.7rem 0.95rem !important;
    color: var(--ink) !important;
  }
  .leaflet-popup-tip {
    background: var(--parchment) !important;
    border: 1px solid var(--rule);
  }
  .leaflet-control-attribution {
    background: rgba(245, 239, 225, 0.85) !important;
    color: var(--ink-soft) !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 10px !important;
    padding: 2px 6px !important;
  }
  .leaflet-control-attribution a { color: var(--slate) !important; }

  /* Zoom control — lives in the top-right corner (set via JS).
     Sized up + given the parchment treatment. */
  .leaflet-control-zoom {
    border: 1px solid var(--rule) !important;
    box-shadow: var(--shadow) !important;
    border-radius: 2px !important;
    overflow: hidden;
  }
  .leaflet-control-zoom a {
    width: 34px !important;
    height: 34px !important;
    line-height: 34px !important;
    font-size: 1.25rem !important;
    background: var(--parchment) !important;
    color: var(--ink) !important;
    font-family: 'Fraunces', serif !important;
    font-weight: 500 !important;
    border-bottom: 1px solid var(--rule-soft) !important;
    transition: background 0.15s ease, color 0.15s ease;
  }
  .leaflet-control-zoom a:last-child {
    border-bottom: none !important;
  }
  .leaflet-control-zoom a:hover {
    background: var(--parchment-deep) !important;
    color: var(--rust) !important;
  }
</style>
</head>
<body>
<div id="map"></div>
<aside class="side-panel" id="side-panel">
  <header>
    <h1 class="panel-title">Killarney</h1>
    <div class="panel-sub">field overlay · debugging view</div>
  </header>
  <div class="panel-body">
    <section class="panel-section">
      <h2 class="section-heading"><span>Counts</span><span class="count">summary</span></h2>
      <div class="counts-row"><span class="key">OSM named lakes</span><span class="val">__OSM_COUNT__</span></div>
      <div class="counts-row"><span class="key">Jeff's named</span><span class="val">__JEFFS_NAMED_COUNT__</span></div>
      <div class="counts-row"><span class="key">Jeff's unnamed</span><span class="val">__JEFFS_UNNAMED_COUNT__</span></div>
    </section>

    <section class="panel-section">
      <h2 class="section-heading"><span>Base map</span></h2>
      <label class="toggle-row">
        <input type="checkbox" id="base-osm" checked>
        <span class="swatch tile"></span>
        <span class="label">OpenStreetMap tiles</span>
      </label>
      <div class="opacity-inline">
        <label for="osm-opacity">opacity</label>
        <input id="osm-opacity" type="range" min="0" max="1" step="0.05" value="1">
      </div>
    </section>

    <section class="panel-section">
      <h2 class="section-heading"><span>Layers</span><span class="count" id="layers-count"></span></h2>
      <div id="layers-list"></div>
    </section>

    <section class="panel-section">
      <h2 class="section-heading"><span>Manual route</span><span class="count" id="draw-count"></span></h2>
      <div class="draw-controls">
        <input class="draw-label-input" id="draw-label" type="text"
               placeholder="Label (e.g. 'Sat to site 82')" maxlength="64">
        <div class="draw-row">
          <button class="draw-btn" id="draw-toggle" type="button">Draw</button>
          <button class="draw-btn" id="draw-save" type="button" disabled>Save</button>
        </div>
        <label class="draw-snap-row" title="When enabled, clicks within ~14px of a waypoint, campsite, or portage/trail line will snap exactly to that feature.">
          <input type="checkbox" id="draw-snap" checked>
          <span>Snap to waypoints, campsites, portages, trails</span>
        </label>
        <div class="draw-stats" id="draw-stats">type a label, click Draw, click map to add waypoints · Enter / dbl-click to finish</div>
        <div class="draw-row">
          <button class="draw-btn" id="draw-undo" type="button" disabled>Undo</button>
          <button class="draw-btn" id="draw-clear" type="button" disabled>Clear</button>
        </div>
      </div>
      <div class="saved-routes" id="saved-routes"></div>
      <div class="draw-row" style="margin-top: 0.55rem;">
        <button class="draw-btn" id="routes-export" type="button" disabled>Export JSON</button>
        <button class="draw-btn" id="routes-import" type="button">Import…</button>
        <input type="file" id="routes-import-file" accept=".json" style="display:none;">
      </div>
    </section>
  </div>
  <button class="info-trigger" id="info-trigger" aria-expanded="false"
          aria-controls="info-flyout">
    <span class="glyph">ⓘ</span>
    <span>Layer info</span>
    <span class="indicator">+</span>
  </button>
</aside>
<aside class="info-flyout" id="info-flyout" role="region" aria-label="Data sources">
  <button class="flyout-close" id="flyout-close" aria-label="Close panel">×</button>
  <h3>Data sources</h3>
  <dl>
    <dt>OpenStreetMap base tiles</dt>
    <dd>Standard OSM tile renderer (<code>tile.openstreetmap.org</code>).</dd>
    <dt>OSM named lakes (51)</dt>
    <dd>Overpass <code>way[natural=water][name]</code> at park bbox. Crowd-traced; precision varies, often coarse. Cached in <code>data/osm_killarney_cache.json</code>.</dd>
    <dt>CanVec 1:50K lakes</dt>
    <dd>Natural Resources Canada hydrography (CanVec series) via the DFO ArcGIS REST endpoint <code>egisp.dfo-mpo.gc.ca</code>, layer 7 (waterbody @ 1:50K). Government survey-grade — Killarney Lake comes back with ~1500 vertices vs OSM's ~20. Cached in <code>data/canvec_killarney_lakes.json</code>.</dd>
    <dt>Jeff's named lakes (33) / unnamed (102)</dt>
    <dd>KMZ raster → polygon extraction by <code>jeffs_extractor.py</code>. Hand-drawn source; smoothed for legibility. Cached in <code>data/jeffs_killarney_cache.json</code>.</dd>
    <dt>Jeff's raster mosaic</dt>
    <dd>"Maps by Jeff v4.0" KMZ super-overlay PNG tiles, mosaicked.</dd>
    <dt>Portages — GPX</dt>
    <dd><code>data/killarneyPortages.gpx</code> via paddleplanner.com — 110 portages × 2 endpoints. Each line is a straight segment between endpoints; length from GPX description.</dd>
    <dt>Portages — OSM only</dt>
    <dd>OSM Overpass <code>way[portage]</code> with no GPX twin within 200m. Usually 0–2 stragglers.</dd>
    <dt>Campsites — GPX</dt>
    <dd><code>data/killarneyCampsites.gpx</code> via paddleplanner.com — 214 numbered sites with GPS.</dd>
    <dt>Hiking trails — OSM</dt>
    <dd>Overpass <code>way[highway=path|track|footway]</code> excluding canoe portage tags. Cached in <code>data/osm_hiking_trails.json</code>. Visual only — not used for routing.</dd>
    <dt>Trip waypoints / route segments</dt>
    <dd>From <code>route_engine.build_route()</code> consuming the merged dataset above. Same code path the trip page uses.</dd>
  </dl>
</aside>
<script>
const osmFeatures = __OSM_GEOJSON__;
const jeffsNamedFeatures = __JEFFS_NAMED_GEOJSON__;
const jeffsUnnamedFeatures = __JEFFS_UNNAMED_GEOJSON__;
const rasterUrl = __RASTER_URL__;
const rasterBounds = __RASTER_BOUNDS__;
const tripMarkers = __TRIP_MARKERS__;
const tripSlug    = __TRIP_SLUG__;        // null when --trip not passed
const tripSegments = __TRIP_SEGMENTS__;
const gpxPortages = __GPX_PORTAGES__;
const gpxCampsites = __GPX_CAMPSITES__;
const hikingTrails = __HIKING_TRAILS__;
const canvecFeatures = __CANVEC_GEOJSON__;
const center = __MAP_CENTER__;

const map = L.map('map', { center: center, zoom: 11, zoomControl: false });
L.control.zoom({ position: 'topright' }).addTo(map);
const osmTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors',
  maxZoom: 18
});
osmTileLayer.addTo(map);
// Empty "basemap-off" layer — toggling to it removes OSM tiles.
const noBase = L.layerGroup([]);

// --- Base-map checkbox toggle + OSM opacity slider sync ---
// Checkbox toggles OSM tile on/off. Slider→0 implicitly unchecks the box.
// Re-checking while slider is at 0 resets it to 1.0 so the layer is visible.
(function() {
  const checkbox = document.getElementById('base-osm');
  const slider   = document.getElementById('osm-opacity');
  if (!checkbox || !slider) return;
  let osmOnMap = true;

  function enableOsm() {
    if (!map.hasLayer(osmTileLayer)) {
      map.removeLayer(noBase);
      map.addLayer(osmTileLayer);
    }
    osmOnMap = true;
  }
  function disableOsm() {
    if (map.hasLayer(osmTileLayer)) {
      map.removeLayer(osmTileLayer);
      map.addLayer(noBase);
    }
    osmOnMap = false;
  }

  checkbox.addEventListener('change', function(ev) {
    if (ev.target.checked) {
      enableOsm();
      if (parseFloat(slider.value) === 0) {
        slider.value = '1';
        osmTileLayer.setOpacity(1);
      }
    } else {
      disableOsm();
    }
  });

  slider.addEventListener('input', function(ev) {
    const v = parseFloat(ev.target.value);
    osmTileLayer.setOpacity(v);
    if (v === 0 && osmOnMap) {
      disableOsm();
      checkbox.checked = false;
    } else if (v > 0 && !osmOnMap) {
      enableOsm();
      checkbox.checked = true;
    }
  });
})();

function popupName(feature, layer) {
  const props = feature.properties || {};
  const name = props.name || '(unnamed)';
  const src = props.source ? ' [' + props.source + ']' : '';
  layer.bindPopup(name + src);
}

const osmLayer = L.geoJSON(osmFeatures, {
  style: { color: '#3a5666', weight: 1.5, fillColor: '#7a98a8', fillOpacity: 0.25 },
  onEachFeature: popupName,
});

const jeffsNamedLayer = L.geoJSON(jeffsNamedFeatures, {
  style: { color: '#a8451f', weight: 1.5, fillColor: '#c66633', fillOpacity: 0.22 },
  onEachFeature: popupName,
});

const jeffsUnnamedLayer = L.geoJSON(jeffsUnnamedFeatures, {
  style: { color: '#c66633', weight: 1, fillColor: '#e5a878', fillOpacity: 0.16,
           dashArray: '4 4' },
  onEachFeature: popupName,
});

const canvecLayer = L.geoJSON(canvecFeatures, {
  style: { color: '#006064', weight: 1.3, fillColor: '#00838f', fillOpacity: 0.22 },
  onEachFeature: popupName,
});

// Each overlaySpec: { label, layer, swatch, defaultOn, count?, opacityInitial? }
const overlaySpecs = [
  { label: 'OSM named lakes',     layer: osmLayer,         swatch: 'osm',
    defaultOn: true,  count: osmFeatures.length },
  { label: 'CanVec 1:50K lakes',  layer: canvecLayer,      swatch: 'canvec',
    defaultOn: false, count: canvecFeatures.length },
  { label: "Jeff's named lakes",  layer: jeffsNamedLayer,  swatch: 'jeffs',
    defaultOn: true,  count: jeffsNamedFeatures.length },
  { label: "Jeff's unnamed lakes", layer: jeffsUnnamedLayer, swatch: 'unnamed',
    defaultOn: false, count: jeffsUnnamedFeatures.length },
];

let rasterLayer = null;
if (rasterUrl && rasterBounds) {
  rasterLayer = L.imageOverlay(rasterUrl, rasterBounds, { opacity: 0.7 });
  overlaySpecs.push({
    label: "Jeff's raster", layer: rasterLayer, swatch: 'raster',
    defaultOn: true, opacityInitial: 0.7,
  });
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
  }));
  overlaySpecs.push({
    label: 'Trip waypoints', layer: tripWaypointLayer, swatch: 'waypoint',
    defaultOn: true, count: tripMarkers.length,
  });
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
  // Defensive: drop consecutive duplicate vertices. Zero-length chords
  // give centripetal Catmull-Rom a knot interval of 0 → division blows up.
  const deduped = [points[0]];
  for (let k = 1; k < points.length; k++) {
    const prev = deduped[deduped.length - 1];
    if (Math.abs(points[k][0] - prev[0]) > 1e-9 ||
        Math.abs(points[k][1] - prev[1]) > 1e-9) {
      deduped.push(points[k]);
    }
  }
  if (deduped.length < 3) return deduped;
  points = deduped;
  const steps = stepsPerSegment || 12;

  // Synthesize phantom endpoints by mirroring the first/last interior
  // segment. This avoids division-by-zero in centripetal Catmull-Rom when
  // p0 = p1 or p2 = p3, which otherwise sends interpolated points to
  // infinity.
  function mirror(a, b) {
    return [a[0] + (a[0] - b[0]), a[1] + (a[1] - b[1])];
  }
  const phantomStart = mirror(points[0], points[1]);
  const phantomEnd = mirror(points[points.length - 1], points[points.length - 2]);

  const out = [points[0]];
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = (i === 0) ? phantomStart : points[i - 1];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = (i + 2 >= points.length) ? phantomEnd : points[i + 2];
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
    // Draw piecewise-straight. fit_paddle_curve already emits ~37 dense
    // Bezier samples (smooth-looking without splining); yellow-walked
    // paths and approx legs are honest-to-the-data polylines. Catmull-Rom
    // smoothing between sparse waypoints can detour outside the lake.
    const coords = rawCoords;
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
  // Trip route polylines are computed but default OFF — they're the
  // auto-routing output, which we're often working to replace via the
  // manual route drawer. Toggle them back on via the layer panel.
  if (paddleLines.length) {
    tripPaddleLayer = L.layerGroup(paddleLines);
    overlaySpecs.push({ label: 'Trip route — paddle', layer: tripPaddleLayer,
                        swatch: 'paddle', defaultOn: false, count: paddleLines.length });
  }
  if (portageLines.length) {
    tripPortageLayer = L.layerGroup(portageLines);
    overlaySpecs.push({ label: 'Trip route — portage', layer: tripPortageLayer,
                        swatch: 'portage', defaultOn: false, count: portageLines.length });
  }
  if (approxLines.length) {
    tripApproxLayer = L.layerGroup(approxLines);
    overlaySpecs.push({ label: 'Trip route — approx', layer: tripApproxLayer,
                        swatch: 'approx', defaultOn: false, count: approxLines.length });
  }
}

// --- GPX layers (portages + campsites, independent of any trip) ---
if (gpxPortages && gpxPortages.length) {
  const gpxLines = [];
  const osmStraggleLines = [];
  gpxPortages.forEach(function(p) {
    const popup = '#' + p.name + ' — ' + (p.length_km * 1000).toFixed(0) + 'm'
                + ' [' + p.source + ']';
    const opts = (p.source === 'gpx')
      ? { color: '#4a148c', weight: 3.5, opacity: 0.9 }
      : { color: '#e65100', weight: 3, opacity: 0.85, dashArray: '6 4' };
    const line = L.polyline(p.line, opts).bindPopup(popup);
    if (p.source === 'gpx') gpxLines.push(line);
    else osmStraggleLines.push(line);
  });
  if (gpxLines.length) {
    overlaySpecs.push({ label: 'Portages (GPX)', layer: L.layerGroup(gpxLines),
                        swatch: 'gpx-portage', defaultOn: true, count: gpxLines.length });
  }
  if (osmStraggleLines.length) {
    overlaySpecs.push({ label: 'Portages (OSM only)', layer: L.layerGroup(osmStraggleLines),
                        swatch: 'osm-portage', defaultOn: true, count: osmStraggleLines.length });
  }
}

if (gpxCampsites && gpxCampsites.length) {
  const dots = gpxCampsites.map(function(c) {
    return L.circleMarker([c.lat, c.lon], {
      radius: 4,
      color: '#1b5e20',
      weight: 1.5,
      fillColor: '#43a047',
      fillOpacity: 0.85,
    }).bindPopup('Site ' + c.name + (c.desc ? ' — ' + c.desc : ''));
  });
  overlaySpecs.push({ label: 'Campsites (GPX)', layer: L.layerGroup(dots),
                      swatch: 'gpx-campsite', defaultOn: false, count: gpxCampsites.length });
}

if (hikingTrails && hikingTrails.length) {
  const lines = hikingTrails.map(function(t) {
    const popup = (t.name || '(unnamed)') + ' [' + t.highway + ']';
    return L.polyline(t.geometry, {
      color: '#00695c', weight: 2, opacity: 0.7,
      dashArray: '2 4',
    }).bindPopup(popup);
  });
  overlaySpecs.push({ label: 'Hiking trails (OSM)', layer: L.layerGroup(lines),
                      swatch: 'hiking', defaultOn: false, count: hikingTrails.length });
}

// --- Render the overlay layer list in the side panel ---
(function renderOverlays() {
  const list = document.getElementById('layers-list');
  const countEl = document.getElementById('layers-count');
  if (!list) return;
  list.innerHTML = '';

  function refreshCount() {
    if (!countEl) return;
    const on = overlaySpecs.filter(s => map.hasLayer(s.layer)).length;
    countEl.textContent = on + ' / ' + overlaySpecs.length + ' on';
  }

  overlaySpecs.forEach(spec => {
    if (spec.defaultOn && !map.hasLayer(spec.layer)) {
      spec.layer.addTo(map);
    }

    let onMap = !!spec.defaultOn;
    let sliderInput = null;  // populated below if spec has opacity

    const row = document.createElement('label');
    row.className = 'toggle-row';

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = onMap;

    const sw = document.createElement('span');
    sw.className = 'swatch ' + spec.swatch;

    const lbl = document.createElement('span');
    lbl.className = 'label';
    lbl.textContent = spec.label;

    row.appendChild(cb);
    row.appendChild(sw);
    row.appendChild(lbl);

    if (typeof spec.count === 'number') {
      const cnt = document.createElement('span');
      cnt.className = 'count';
      cnt.textContent = String(spec.count);
      row.appendChild(cnt);
    }
    list.appendChild(row);

    function enableLayer() {
      if (!map.hasLayer(spec.layer)) spec.layer.addTo(map);
      onMap = true;
    }
    function disableLayer() {
      if (map.hasLayer(spec.layer)) map.removeLayer(spec.layer);
      onMap = false;
    }

    cb.addEventListener('change', function(ev) {
      if (ev.target.checked) {
        enableLayer();
        // Re-checking while opacity is 0 = reset to its initial visible value.
        if (sliderInput && parseFloat(sliderInput.value) === 0) {
          sliderInput.value = String(spec.opacityInitial);
          if (spec.layer.setOpacity) spec.layer.setOpacity(spec.opacityInitial);
        }
      } else {
        disableLayer();
      }
      refreshCount();
    });

    if (typeof spec.opacityInitial === 'number') {
      const opRow = document.createElement('div');
      opRow.className = 'opacity-inline';
      const sliderId = 'opacity-' + spec.swatch;
      opRow.innerHTML =
        '<label for="' + sliderId + '">opacity</label>' +
        '<input id="' + sliderId + '" type="range" min="0" max="1" step="0.05" value="' +
        spec.opacityInitial + '">';
      list.appendChild(opRow);
      sliderInput = opRow.querySelector('input');
      sliderInput.addEventListener('input', function(ev) {
        const v = parseFloat(ev.target.value);
        if (spec.layer.setOpacity) spec.layer.setOpacity(v);
        // Slider→0 implicitly turns off; slider>0 turns back on.
        if (v === 0 && onMap) {
          disableLayer();
          cb.checked = false;
          refreshCount();
        } else if (v > 0 && !onMap) {
          enableLayer();
          cb.checked = true;
          refreshCount();
        }
      });
    }
  });

  refreshCount();
})();

// --- Manual route drawer ---
// Draw labeled routes, save to localStorage (per-trip), list/toggle/delete,
// and export the collection as `manual_routes.json` for build_trip to consume.
(function() {
  const toggleBtn  = document.getElementById('draw-toggle');
  const saveBtn    = document.getElementById('draw-save');
  const undoBtn    = document.getElementById('draw-undo');
  const clearBtn   = document.getElementById('draw-clear');
  const labelInput = document.getElementById('draw-label');
  const snapCb     = document.getElementById('draw-snap');
  const statsEl    = document.getElementById('draw-stats');
  const countEl    = document.getElementById('draw-count');
  const mapEl      = document.getElementById('map');
  const savedList  = document.getElementById('saved-routes');
  const exportBtn  = document.getElementById('routes-export');
  const importBtn  = document.getElementById('routes-import');
  const importFile = document.getElementById('routes-import-file');
  if (!toggleBtn || !statsEl) return;

  const ROUTE_COLOR = '#6b3a8a';
  const ROUTE_DASH  = null;
  const SNAP_PX     = 14;        // pixel radius for snap detection

  let drawing = false;
  let points  = [];                       // [[lat, lon], ...]
  let lineLayer = null;
  let vertexLayer = L.layerGroup();
  vertexLayer.addTo(map);
  let previewLine = null;
  let snapIndicator = null;               // halo circle drawn at active snap target
  let currentSnap = null;                 // { latlng, label, type } or null

  // Build snap targets from the data we already have in scope.
  // POINTS: trip waypoints, GPX campsites. LINES: GPX portages, hiking trails.
  const snapPoints = [];
  const snapLines  = [];
  if (tripMarkers && tripMarkers.length) {
    for (const m of tripMarkers) {
      snapPoints.push({ lat: m.lat, lon: m.lon,
        label: m.label || (m.kind === 'access' ? 'access' : 'waypoint'),
        type: 'waypoint' });
    }
  }
  if (gpxCampsites && gpxCampsites.length) {
    for (const c of gpxCampsites) {
      snapPoints.push({ lat: c.lat, lon: c.lon,
        label: 'site ' + c.name, type: 'campsite' });
    }
  }
  if (gpxPortages && gpxPortages.length) {
    for (const p of gpxPortages) {
      snapLines.push({ line: p.line, label: 'portage ' + p.name, type: 'portage' });
    }
  }
  if (hikingTrails && hikingTrails.length) {
    for (const t of hikingTrails) {
      snapLines.push({
        line: t.geometry,
        label: 'trail ' + (t.name || '(unnamed)'),
        type: 'trail',
      });
    }
  }

  function _closestOnSegment(p, a, b) {  // L.Point inputs
    const dx = b.x - a.x, dy = b.y - a.y;
    if (dx === 0 && dy === 0) return a;
    let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy);
    t = Math.max(0, Math.min(1, t));
    return L.point(a.x + t * dx, a.y + t * dy);
  }
  function findSnap(latlng) {
    if (!snapCb || !snapCb.checked) return null;
    const clickPx = map.latLngToLayerPoint(latlng);
    let best = null;
    let bestDist = SNAP_PX;
    for (const pt of snapPoints) {
      const px = map.latLngToLayerPoint(L.latLng(pt.lat, pt.lon));
      const d = clickPx.distanceTo(px);
      if (d < bestDist) {
        bestDist = d;
        best = { latlng: [pt.lat, pt.lon], label: pt.label, type: pt.type };
      }
    }
    for (const ln of snapLines) {
      if (!ln.line || ln.line.length < 2) continue;
      for (let i = 0; i < ln.line.length - 1; i++) {
        const a = map.latLngToLayerPoint(L.latLng(ln.line[i][0], ln.line[i][1]));
        const b = map.latLngToLayerPoint(L.latLng(ln.line[i+1][0], ln.line[i+1][1]));
        const cp = _closestOnSegment(clickPx, a, b);
        const d = clickPx.distanceTo(cp);
        if (d < bestDist) {
          bestDist = d;
          const ll = map.layerPointToLatLng(cp);
          best = { latlng: [ll.lat, ll.lng], label: ln.label, type: ln.type };
        }
      }
    }
    return best;
  }
  function showSnapIndicator(snap) {
    if (snapIndicator) { map.removeLayer(snapIndicator); snapIndicator = null; }
    if (!snap) return;
    snapIndicator = L.circleMarker(snap.latlng, {
      radius: 9, color: ROUTE_COLOR, weight: 2.5,
      fillColor: '#f5efe1', fillOpacity: 0.4,
      dashArray: '3 3',
    }).addTo(map);
  }

  function hav(a, b) {
    const R = 6371;
    const p1 = a[0] * Math.PI / 180;
    const p2 = b[0] * Math.PI / 180;
    const dp = (b[0] - a[0]) * Math.PI / 180;
    const dl = (b[1] - a[1]) * Math.PI / 180;
    const h = Math.sin(dp/2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl/2) ** 2;
    return R * 2 * Math.asin(Math.sqrt(h));
  }
  function totalKm() {
    let d = 0;
    for (let i = 1; i < points.length; i++) d += hav(points[i-1], points[i]);
    return d;
  }
  function render() {
    if (lineLayer) { map.removeLayer(lineLayer); lineLayer = null; }
    vertexLayer.clearLayers();
    if (points.length >= 2) {
      lineLayer = L.polyline(points, {
        color: ROUTE_COLOR, weight: 4, opacity: 0.95, smoothFactor: 0,
        ...(ROUTE_DASH ? { dashArray: ROUTE_DASH } : {})
      }).addTo(map);
    }
    points.forEach((p, i) => {
      L.circleMarker(p, {
        radius: 5,
        color: ROUTE_COLOR,
        weight: 2,
        fillColor: i === 0 ? '#f5efe1' : ROUTE_COLOR,
        fillOpacity: 0.95,
      }).bindTooltip(String(i + 1), { permanent: false, direction: 'top', offset: [0, -4] })
        .addTo(vertexLayer);
    });
    updateUI();
  }
  function updateUI() {
    const n = points.length;
    if (countEl) countEl.textContent = n ? `${n} pt` : '';
    const snapNote = currentSnap
      ? ` · <span class="snap-target">snap → ${currentSnap.label}</span>`
      : '';
    if (n === 0) {
      const head = drawing
        ? 'click map to add the first waypoint'
        : 'type a label, click Draw, click map to add waypoints';
      statsEl.innerHTML = head + snapNote;
    } else if (n === 1) {
      statsEl.innerHTML = `<span class="km">1</span> waypoint · 0 km${snapNote}`;
    } else {
      const km = totalKm();
      statsEl.innerHTML = `<span class="km">${km.toFixed(2)} km</span> &middot; ${n} waypoints${snapNote}`;
    }
    const hasPoints = n > 0;
    if (undoBtn)  undoBtn.disabled  = !hasPoints;
    if (clearBtn) clearBtn.disabled = !hasPoints;
    if (saveBtn)  saveBtn.disabled  = !(n >= 2 && labelInput && labelInput.value.trim());
  }
  function setDrawing(on) {
    drawing = !!on;
    toggleBtn.classList.toggle('active', drawing);
    toggleBtn.textContent = drawing ? 'Drawing… (click to finish)' : 'Draw route';
    if (drawing) mapEl.classList.add('drawing');
    else {
      mapEl.classList.remove('drawing');
      if (previewLine) { map.removeLayer(previewLine); previewLine = null; }
      currentSnap = null;
      showSnapIndicator(null);
    }
    updateUI();
  }

  // ── Saved routes (per-trip localStorage + on-map rendering) ──────────────
  const STORAGE_KEY = 'manual_routes:' + (tripSlug || '__no_trip__');
  const PALETTE = ['#6b3a8a','#1565c0','#2e7d32','#c62828','#ef6c00',
                   '#00695c','#5d4037','#8e24aa','#0277bd','#558b2f'];
  let savedRoutes = [];        // {id, label, geometry, distance_km, show, color}
  let renderedLayers = {};     // id → Leaflet polyline

  function loadSaved() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      savedRoutes = raw ? JSON.parse(raw) : [];
    } catch (e) { savedRoutes = []; }
  }
  function persist() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRoutes)); }
    catch (e) { /* localStorage full or disabled */ }
  }
  function pickColor() {
    const used = new Set(savedRoutes.map(r => r.color));
    for (const c of PALETTE) if (!used.has(c)) return c;
    return PALETTE[savedRoutes.length % PALETTE.length];
  }
  function routeHav(geom) {
    let d = 0;
    for (let i = 1; i < geom.length; i++) d += hav(geom[i-1], geom[i]);
    return d;
  }
  function renderSavedOnMap() {
    for (const id of Object.keys(renderedLayers)) {
      map.removeLayer(renderedLayers[id]);
      delete renderedLayers[id];
    }
    for (const r of savedRoutes) {
      if (!r.show || !r.geometry || r.geometry.length < 2) continue;
      const ly = L.polyline(r.geometry, {
        color: r.color, weight: 4, opacity: 0.9, smoothFactor: 0,
      }).bindPopup(`<strong>${escapeHtml(r.label)}</strong><br>${r.distance_km.toFixed(2)} km`);
      ly.addTo(map);
      renderedLayers[r.id] = ly;
    }
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  }
  function renderList() {
    savedList.innerHTML = '';
    for (const r of savedRoutes) {
      const row = document.createElement('div');
      row.className = 'saved-route';
      row.innerHTML = `
        <span class="sr-swatch" style="background: ${r.color}33; border-color: ${r.color};"></span>
        <input class="sr-check" type="checkbox" ${r.show ? 'checked' : ''}>
        <span class="sr-label" title="${escapeHtml(r.label)}">${escapeHtml(r.label)}</span>
        <span class="sr-dist">${r.distance_km.toFixed(2)} km</span>
        <button class="sr-act" data-act="edit" title="Load back into draw mode for editing">✎</button>
        <button class="sr-act" data-act="delete" title="Delete">×</button>
      `;
      const cb = row.querySelector('.sr-check');
      cb.addEventListener('change', () => {
        r.show = cb.checked; persist(); renderSavedOnMap();
      });
      row.querySelector('[data-act="edit"]').addEventListener('click', () => {
        points = r.geometry.map(p => [p[0], p[1]]);
        labelInput.value = r.label;
        // Remove from list while editing — re-save overwrites.
        savedRoutes = savedRoutes.filter(x => x.id !== r.id);
        persist(); renderList(); renderSavedOnMap(); render();
        setDrawing(true);
      });
      row.querySelector('[data-act="delete"]').addEventListener('click', () => {
        savedRoutes = savedRoutes.filter(x => x.id !== r.id);
        persist(); renderList(); renderSavedOnMap();
        exportBtn.disabled = savedRoutes.length === 0;
      });
      savedList.appendChild(row);
    }
    exportBtn.disabled = savedRoutes.length === 0;
  }
  function updateSaveButton() {
    saveBtn.disabled = !(points.length >= 2 && labelInput.value.trim());
  }

  toggleBtn.addEventListener('click', function() { setDrawing(!drawing); });
  undoBtn.addEventListener('click', function() {
    if (points.length) { points.pop(); render(); }
  });
  clearBtn.addEventListener('click', function() {
    points = []; render();
  });
  labelInput.addEventListener('input', updateSaveButton);
  saveBtn.addEventListener('click', function() {
    if (points.length < 2 || !labelInput.value.trim()) return;
    const route = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      label: labelInput.value.trim(),
      geometry: points.map(p => [Number(p[0].toFixed(5)), Number(p[1].toFixed(5))]),
      distance_km: Number(routeHav(points).toFixed(3)),
      show: true,
      color: pickColor(),
    };
    savedRoutes.push(route);
    persist();
    points = []; labelInput.value = '';
    render(); renderList(); renderSavedOnMap();
    setDrawing(false);
    updateSaveButton();
  });

  exportBtn.addEventListener('click', function() {
    const payload = {
      _meta: {
        exported_at: new Date().toISOString(),
        trip_slug: tripSlug,
        source: 'jeffs_osm_overlay.html manual route drawer',
      },
      routes: savedRoutes.map(r => ({
        label: r.label, geometry: r.geometry, distance_km: r.distance_km,
        show: r.show, color: r.color,
      })),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'manual_routes.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
  importBtn.addEventListener('click', () => importFile.click());
  importFile.addEventListener('change', (ev) => {
    const f = ev.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result);
        const incoming = data.routes || [];
        for (const r of incoming) {
          if (!r.label || !Array.isArray(r.geometry) || r.geometry.length < 2) continue;
          savedRoutes.push({
            id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
            label: r.label,
            geometry: r.geometry,
            distance_km: r.distance_km || routeHav(r.geometry),
            show: r.show !== false,
            color: r.color || pickColor(),
          });
        }
        persist(); renderList(); renderSavedOnMap();
      } catch (e) {
        alert('Import failed: ' + e.message);
      }
    };
    reader.readAsText(f);
    importFile.value = '';
  });

  loadSaved();
  renderList();
  renderSavedOnMap();

  map.on('click', function(ev) {
    if (!drawing) return;
    const snap = findSnap(ev.latlng);
    const pt = snap ? snap.latlng : [ev.latlng.lat, ev.latlng.lng];
    points.push(pt);
    render();
  });
  map.on('dblclick', function(ev) {
    if (!drawing) return;
    L.DomEvent.stopPropagation(ev);
    L.DomEvent.preventDefault(ev);
    setDrawing(false);
  });
  // Disable Leaflet's default double-click-zoom while drawing so dblclick
  // finishes the route instead.
  map.doubleClickZoom.disable();
  map.on('mousemove', function(ev) {
    if (!drawing) return;
    const snap = findSnap(ev.latlng);
    currentSnap = snap;
    showSnapIndicator(snap);
    if (points.length > 0) {
      if (previewLine) map.removeLayer(previewLine);
      const end = snap ? snap.latlng : [ev.latlng.lat, ev.latlng.lng];
      previewLine = L.polyline([points[points.length - 1], end], {
        color: ROUTE_COLOR, weight: 2, opacity: 0.5, dashArray: '4 4',
      }).addTo(map);
    }
    updateUI();
  });
  // Recompute snap when the user toggles the checkbox.
  if (snapCb) snapCb.addEventListener('change', function() {
    if (!snapCb.checked) {
      currentSnap = null;
      showSnapIndicator(null);
      updateUI();
    }
  });
  document.addEventListener('keydown', function(ev) {
    if (!drawing) return;
    if (ev.key === 'Escape' || ev.key === 'Enter') setDrawing(false);
    if (ev.key === 'Backspace' && points.length) { points.pop(); render(); }
  });

  updateUI();
})();

// Info fly-out toggle.
(function() {
  const trigger = document.getElementById('info-trigger');
  const flyout  = document.getElementById('info-flyout');
  const close   = document.getElementById('flyout-close');
  if (!trigger || !flyout) return;

  function isOpen() { return flyout.classList.contains('open'); }
  function openFlyout() {
    flyout.classList.add('open');
    trigger.setAttribute('aria-expanded', 'true');
  }
  function closeFlyout() {
    flyout.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
  }
  trigger.addEventListener('click', function(ev) {
    ev.stopPropagation();
    if (isOpen()) closeFlyout(); else openFlyout();
  });
  if (close) close.addEventListener('click', closeFlyout);
  document.addEventListener('click', function(ev) {
    if (!isOpen()) return;
    if (flyout.contains(ev.target) || trigger.contains(ev.target)) return;
    closeFlyout();
  });
  document.addEventListener('keydown', function(ev) {
    if (ev.key === 'Escape' && isOpen()) closeFlyout();
  });
})();

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


def _load_gpx_layers(bbox) -> dict:
    """Load merged portages + campsites from osm_data.load_killarney_features
    for the GPX overlay layers. Filters to those intersecting bbox if given.

    Returns:
      {
        "portages": [{"name": str, "line": [[lat,lon],...], "length_km": float,
                      "source": "gpx"|"osm"}],
        "campsites": [{"name": str, "lat": float, "lon": float,
                       "desc": str}],
      }
    """
    import osm_data
    osm = osm_data.load_killarney_features()
    portages = []
    for p in osm.get("portages", []) or []:
        line = p.get("line") or p.get("endpoints") or []
        if not line:
            continue
        # bbox filter via any endpoint inside.
        if bbox is not None:
            s, w, n, e = bbox
            in_bbox = any(s <= pt[0] <= n and w <= pt[1] <= e for pt in line)
            if not in_bbox:
                continue
        portages.append({
            "name": p.get("name", "(unnamed)"),
            "line": line,
            "length_km": p.get("length_km", 0.0),
            "source": p.get("source", "osm"),
        })
    campsites = []
    for c in osm.get("campsites", []) or []:
        lat = c.get("lat")
        lon = c.get("lon")
        if lat is None or lon is None:
            # Legacy Jeff's shape would have "gps" instead.
            gps = c.get("gps")
            if gps and len(gps) == 2:
                lat, lon = gps[0], gps[1]
        if lat is None or lon is None:
            continue
        if bbox is not None:
            s, w, n, e = bbox
            if not (s <= lat <= n and w <= lon <= e):
                continue
        campsites.append({
            "name": c.get("name") or c.get("ref") or "",
            "lat": lat,
            "lon": lon,
            "desc": c.get("desc", ""),
        })
    return {"portages": portages, "campsites": campsites}


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
                        default=str(REPO_ROOT / "data" / "osm_killarney_cache.json"))
    parser.add_argument("--jeffs-cache",
                        default=str(REPO_ROOT / "data" / "jeffs_killarney_cache.json"))
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

    gpx_data = _load_gpx_layers(bbox)
    gpx_portages = gpx_data["portages"]
    gpx_campsites = gpx_data["campsites"]

    # CanVec 1:50K waterbody polygons (NRCan hydrography via DFO ArcGIS).
    # Go through osm_data._load_canvec_lakes so we get the same same-name
    # union (multiple Lake Huron tile pieces merged into one polygon) that
    # the routing pipeline uses — keeps overlay and routing consistent.
    import osm_data as _od
    canvec_features = []
    for lake in _od._load_canvec_lakes():
        polygon = lake.get("polygon") or []
        if not polygon or not _polygon_intersects_bbox(polygon, bbox):
            continue
        canvec_features.append(_to_geojson_feature(lake, {"source": "CanVec"}))

    # Hiking trails from OSM (visual-only — separate from canoe portages).
    hiking_trails = []
    hiking_cache = REPO_ROOT / "data" / "osm_hiking_trails.json"
    if hiking_cache.exists():
        data = json.loads(hiking_cache.read_text())
        for t in data.get("trails", []):
            geom = t.get("geometry") or []
            if not geom:
                continue
            if bbox is not None:
                s, w, n, e = bbox
                if not any(s <= pt[0] <= n and w <= pt[1] <= e for pt in geom):
                    continue
            hiking_trails.append(t)

    trip_markers = []
    trip_segments = []
    trip_slug = None
    if args.trip:
        trip_data = _load_trip_route(Path(args.trip))
        trip_markers = trip_data["markers"]
        trip_segments = trip_data["segments"]
        trip_slug = Path(args.trip).resolve().name

    center = _features_center(osm_named + jeffs_named + jeffs_unnamed)

    html = (
        _HTML_TEMPLATE
        .replace("__OSM_GEOJSON__", json.dumps(osm_named))
        .replace("__JEFFS_NAMED_GEOJSON__", json.dumps(jeffs_named))
        .replace("__JEFFS_UNNAMED_GEOJSON__", json.dumps(jeffs_unnamed))
        .replace("__RASTER_URL__", raster_url_js)
        .replace("__RASTER_BOUNDS__", raster_bounds_js)
        .replace("__TRIP_MARKERS__", json.dumps(trip_markers))
        .replace("__TRIP_SLUG__", json.dumps(trip_slug))
        .replace("__TRIP_SEGMENTS__", json.dumps(trip_segments))
        .replace("__GPX_PORTAGES__", json.dumps(gpx_portages))
        .replace("__GPX_CAMPSITES__", json.dumps(gpx_campsites))
        .replace("__HIKING_TRAILS__", json.dumps(hiking_trails))
        .replace("__CANVEC_GEOJSON__", json.dumps(canvec_features))
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
    print(f"  GPX portages:   {sum(1 for p in gpx_portages if p['source']=='gpx')}")
    print(f"  OSM-only portages: {sum(1 for p in gpx_portages if p['source']=='osm')}")
    print(f"  GPX campsites:  {len(gpx_campsites)}")
    print(f"  Hiking trails:  {len(hiking_trails)}")
    print(f"  CanVec lakes:   {len(canvec_features)}")
    if args.kmz:
        print(f"  Raster mosaic:    {jpg_name} (zoom {args.zoom_raster})")
        print(f"  Open via:         python3 -m http.server  →  "
              f"http://localhost:8000/{out_path.name}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
