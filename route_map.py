"""
Parse KML/GPX route files and generate embeddable map HTML.

Produces:
- Leaflet.js interactive map (online, with OpenStreetMap tiles)
- Static SVG route diagram (offline fallback)
- Parsed waypoints with names, distances, and coordinates
"""

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple

# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_gpx(filepath: str) -> dict:
    """Parse a GPX file into route data."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Handle namespaces
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    waypoints = []
    tracks = []

    # Parse waypoints
    for wpt in root.findall(f".//{ns}wpt"):
        lat = float(wpt.get("lat", 0))
        lon = float(wpt.get("lon", 0))
        name_el = wpt.find(f"{ns}name")
        desc_el = wpt.find(f"{ns}desc")
        name = name_el.text if name_el is not None and name_el.text else ""
        desc = desc_el.text if desc_el is not None and desc_el.text else ""
        waypoints.append({"lat": lat, "lon": lon, "name": name, "desc": desc})

    # Parse tracks
    for trk in root.findall(f".//{ns}trk"):
        name_el = trk.find(f"{ns}name")
        track_name = name_el.text if name_el is not None and name_el.text else "Track"
        points = []
        for trkpt in trk.findall(f".//{ns}trkpt"):
            lat = float(trkpt.get("lat", 0))
            lon = float(trkpt.get("lon", 0))
            points.append((lat, lon))
        if points:
            tracks.append({"name": track_name, "points": points})

    # Parse routes (rte elements)
    for rte in root.findall(f".//{ns}rte"):
        name_el = rte.find(f"{ns}name")
        route_name = name_el.text if name_el is not None and name_el.text else "Route"
        points = []
        for rtept in rte.findall(f".//{ns}rtept"):
            lat = float(rtept.get("lat", 0))
            lon = float(rtept.get("lon", 0))
            points.append((lat, lon))
        if points:
            tracks.append({"name": route_name, "points": points})

    return {"waypoints": waypoints, "tracks": tracks, "source": "gpx"}


def parse_kml(filepath: str) -> dict:
    """Parse a KML file into route data."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Handle namespaces
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    waypoints = []
    tracks = []

    # Parse placemarks
    for pm in root.findall(f".//{ns}Placemark"):
        name_el = pm.find(f"{ns}name")
        name = name_el.text if name_el is not None and name_el.text else ""
        desc_el = pm.find(f"{ns}description")
        desc = desc_el.text if desc_el is not None and desc_el.text else ""

        # Point (waypoint)
        point = pm.find(f".//{ns}Point/{ns}coordinates")
        if point is not None and point.text:
            coords = point.text.strip().split(",")
            if len(coords) >= 2:
                lon, lat = float(coords[0]), float(coords[1])
                waypoints.append({"lat": lat, "lon": lon, "name": name, "desc": desc})

        # LineString (track)
        linestring = pm.find(f".//{ns}LineString/{ns}coordinates")
        if linestring is not None and linestring.text:
            points = []
            for coord_str in linestring.text.strip().split():
                parts = coord_str.split(",")
                if len(parts) >= 2:
                    lon, lat = float(parts[0]), float(parts[1])
                    points.append((lat, lon))
            if points:
                tracks.append({"name": name, "points": points})

        # MultiGeometry — recurse into LineStrings
        for ls in pm.findall(f".//{ns}MultiGeometry/{ns}LineString/{ns}coordinates"):
            if ls.text:
                points = []
                for coord_str in ls.text.strip().split():
                    parts = coord_str.split(",")
                    if len(parts) >= 2:
                        lon, lat = float(parts[0]), float(parts[1])
                        points.append((lat, lon))
                if points:
                    tracks.append({"name": name, "points": points})

    return {"waypoints": waypoints, "tracks": tracks, "source": "kml"}


def parse_route_file(filepath: str) -> dict:
    """Auto-detect and parse a KML or GPX file."""
    path = Path(filepath)
    ext = path.suffix.lower()
    if ext == ".gpx":
        return parse_gpx(filepath)
    elif ext in (".kml", ".kmz"):
        return parse_kml(filepath)
    else:
        # Try to detect from content
        with open(filepath, encoding="utf-8") as f:
            first_line = f.readline(500).lower()
        if "gpx" in first_line:
            return parse_gpx(filepath)
        return parse_kml(filepath)


# ── Distance calculations ────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def total_distance(points: List[Tuple[float, float]]) -> float:
    """Calculate total distance of a track in km."""
    dist = 0
    for i in range(1, len(points)):
        dist += haversine(points[i-1][0], points[i-1][1], points[i][0], points[i][1])
    return dist


def get_bounds(route_data: dict) -> dict:
    """Get lat/lon bounds of all points in the route data."""
    all_points = []
    for wpt in route_data.get("waypoints", []):
        all_points.append((wpt["lat"], wpt["lon"]))
    for track in route_data.get("tracks", []):
        all_points.extend(track["points"])

    if not all_points:
        return {"min_lat": 0, "max_lat": 0, "min_lon": 0, "max_lon": 0,
                "center_lat": 0, "center_lon": 0}

    lats = [p[0] for p in all_points]
    lons = [p[1] for p in all_points]
    return {
        "min_lat": min(lats), "max_lat": max(lats),
        "min_lon": min(lons), "max_lon": max(lons),
        "center_lat": sum(lats) / len(lats),
        "center_lon": sum(lons) / len(lons),
    }


# ── SVG generation (offline) ────────────────────────────────────────────────

def route_to_svg(route_data: dict, width: int = 700, height: int = 400) -> str:
    """Generate an SVG visualization of the route."""
    bounds = get_bounds(route_data)
    if bounds["min_lat"] == bounds["max_lat"]:
        return ""

    padding = 40
    draw_w = width - 2 * padding
    draw_h = height - 2 * padding

    lat_range = bounds["max_lat"] - bounds["min_lat"]
    lon_range = bounds["max_lon"] - bounds["min_lon"]

    # Maintain aspect ratio using mercator-like projection
    if lat_range == 0:
        lat_range = 0.01
    if lon_range == 0:
        lon_range = 0.01

    # Scale to fit
    scale_x = draw_w / lon_range
    scale_y = draw_h / lat_range
    scale = min(scale_x, scale_y)

    def project(lat, lon):
        x = padding + (lon - bounds["min_lon"]) * scale + (draw_w - lon_range * scale) / 2
        y = padding + (bounds["max_lat"] - lat) * scale + (draw_h - lat_range * scale) / 2
        return round(x, 1), round(y, 1)

    svg_parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{width}px;height:auto;background:#e8f4f8;border-radius:10px">'
    ]

    # Draw tracks
    colors = ["#2d5016", "#1565c0", "#c62828", "#6a1b9a"]
    for i, track in enumerate(route_data.get("tracks", [])):
        if not track["points"]:
            continue
        color = colors[i % len(colors)]
        points_str = " ".join(f"{project(lat, lon)[0]},{project(lat, lon)[1]}"
                              for lat, lon in track["points"])
        dist = total_distance(track["points"])
        svg_parts.append(
            f'<polyline points="{points_str}" fill="none" stroke="{color}" '
            f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" opacity="0.8"/>'
        )
        # Track label
        mid = track["points"][len(track["points"]) // 2]
        mx, my = project(mid[0], mid[1])
        label = f'{track["name"]} ({dist:.1f} km)' if track["name"] else f'{dist:.1f} km'
        svg_parts.append(
            f'<text x="{mx}" y="{my - 10}" text-anchor="middle" '
            f'font-size="11" fill="{color}" font-weight="600">{label}</text>'
        )

    # Draw waypoints
    for wpt in route_data.get("waypoints", []):
        x, y = project(wpt["lat"], wpt["lon"])
        svg_parts.append(
            f'<circle cx="{x}" cy="{y}" r="5" fill="#c62828" stroke="white" stroke-width="2"/>'
        )
        if wpt["name"]:
            svg_parts.append(
                f'<text x="{x + 8}" y="{y + 4}" font-size="11" fill="#333">{wpt["name"]}</text>'
            )

    # Scale bar
    scale_km = lat_range * 111 * 0.2  # ~20% of map height in km
    scale_px = scale_km / (lat_range * 111) * draw_h
    bar_y = height - 15
    svg_parts.append(
        f'<line x1="{padding}" y1="{bar_y}" x2="{padding + scale_px}" y2="{bar_y}" '
        f'stroke="#666" stroke-width="2"/>'
    )
    svg_parts.append(
        f'<text x="{padding + scale_px / 2}" y="{bar_y - 4}" text-anchor="middle" '
        f'font-size="10" fill="#666">{scale_km:.1f} km</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


# ── Leaflet map generation (online) ─────────────────────────────────────────

def route_to_leaflet(route_data: dict, map_id: str = "route-map") -> str:
    """Generate HTML/JS for an interactive Leaflet map."""
    bounds = get_bounds(route_data)

    # Convert tracks to GeoJSON (auto-routed segments)
    features = []
    for track in route_data.get("tracks", []):
        if not track["points"]:
            continue
        dist = total_distance(track["points"])
        coords = [[lon, lat] for lat, lon in track["points"]]
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"name": track["name"], "distance_km": round(dist, 1)},
        })

    # Waypoints split into:
    #   - "site" markers: rendered as numbered badges (site number from the
    #     trip frontmatter, e.g. "61", "82")
    #   - "access" markers: rendered as a flagged circle
    #   - other: plain circleMarker (existing behavior, e.g. portage pins)
    site_waypoints = []
    other_waypoints = []
    for wpt in route_data.get("waypoints", []):
        if wpt.get("kind") == "site" and wpt.get("site_number"):
            site_waypoints.append(wpt)
        elif wpt.get("kind") == "access":
            site_waypoints.append(wpt)  # access also gets a special pin
        else:
            other_waypoints.append(wpt)

    for wpt in other_waypoints:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [wpt["lon"], wpt["lat"]]},
            "properties": {"name": wpt["name"], "desc": wpt.get("desc", "")},
        })

    geojson = json.dumps({"type": "FeatureCollection", "features": features})
    manual_routes = json.dumps(route_data.get("manual_routes") or [])
    site_markers_json = json.dumps([
        {"lat": w["lat"], "lon": w["lon"],
         "kind": w.get("kind", "site"),
         "label": w.get("site_number") or w.get("name", ""),
         "name": w.get("name", ""),
         "desc": w.get("desc", "")}
        for w in site_waypoints
    ])

    return f"""
<div id="{map_id}-controls" style="margin-bottom:0.5rem"></div>
<div id="{map_id}" style="height:400px;border-radius:10px;z-index:0"></div>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  #{map_id}-controls {{
    display: flex; flex-wrap: wrap; gap: 0.4rem 0.85rem;
    padding: 0.5rem 0.7rem; border: 1px solid #d9d2c0; border-radius: 6px;
    background: #f6f1e3; font-size: 0.85rem; line-height: 1.4;
  }}
  #{map_id}-controls .mr-group-label {{
    font-weight: 600; color: #5d4037; margin-right: 0.3rem;
  }}
  #{map_id}-controls label {{
    display: inline-flex; align-items: center; gap: 0.35rem;
    cursor: pointer; user-select: none; padding: 0.1rem 0.3rem;
    border-radius: 3px;
  }}
  #{map_id}-controls label:hover {{ background: #ebe3cb; }}
  #{map_id}-controls .mr-swatch {{
    display: inline-block; width: 12px; height: 12px; border: 1.5px solid;
  }}
  #{map_id}-controls .mr-dist {{ color: #888; font-size: 0.78rem; }}
  .site-badge {{
    width: 30px; height: 30px; border-radius: 50%;
    background: #c62828; color: #fff;
    border: 2.5px solid #fff;
    box-shadow: 0 1px 4px rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center;
    font: 700 13px/1 'JetBrains Mono', ui-monospace, monospace;
    letter-spacing: -0.02em;
  }}
  .site-badge.access {{ background: #2d5016; border-radius: 4px; }}
</style>
<script>
(function() {{
  var map = L.map('{map_id}').setView([{bounds['center_lat']}, {bounds['center_lon']}], 12);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 18
  }}).addTo(map);

  var geojson = {geojson};
  var siteMarkers = {site_markers_json};
  var colors = ['#2d5016', '#1565c0', '#c62828', '#6a1b9a'];
  var colorIdx = 0;

  var autoLayer = L.geoJSON(geojson, {{
    style: function(feature) {{
      return {{color: colors[colorIdx++ % colors.length], weight: 4, opacity: 0.7}};
    }},
    pointToLayer: function(feature, latlng) {{
      return L.circleMarker(latlng, {{radius: 7, fillColor: '#c62828', color: 'white', weight: 2, fillOpacity: 1}});
    }},
    onEachFeature: function(feature, layer) {{
      var props = feature.properties;
      var popup = props.name || '';
      if (props.distance_km) popup += ' (' + props.distance_km + ' km)';
      if (props.desc) popup += '<br>' + props.desc;
      if (popup) layer.bindPopup(popup);
    }}
  }}).addTo(map);

  // ── Numbered site / access-point badges ─────────────────────────────────
  siteMarkers.forEach(function(m) {{
    var cls = 'site-badge' + (m.kind === 'access' ? ' access' : '');
    var icon = L.divIcon({{
      className: '',
      html: '<div class="' + cls + '">' + m.label + '</div>',
      iconSize: [30, 30],
      iconAnchor: [15, 15]
    }});
    var marker = L.marker([m.lat, m.lon], {{icon: icon}}).addTo(map);
    var popup = '<strong>' + (m.name || ('Site ' + m.label)) + '</strong>';
    if (m.desc) popup += '<br>' + m.desc;
    marker.bindPopup(popup);
  }});

  // ── Manual routes (toggleable, labeled) ────────────────────────────────
  var manualRoutes = {manual_routes};
  var manualLayers = [];
  var manualBoundsAll = [];
  manualRoutes.forEach(function(r) {{
    if (!r.geometry || r.geometry.length < 2) return;
    var ly = L.polyline(r.geometry, {{
      color: r.color || '#6b3a8a', weight: 4, opacity: 0.95, smoothFactor: 0
    }}).bindPopup('<strong>' + r.label + '</strong><br>' + r.distance_km.toFixed(2) + ' km');
    if (r.show !== false) ly.addTo(map);
    manualLayers.push({{ route: r, layer: ly }});
    r.geometry.forEach(function(p) {{ manualBoundsAll.push(p); }});
  }});

  // Toggle UI: auto-route toggle + per-manual-route toggles.
  var controls = document.getElementById('{map_id}-controls');
  if (controls) {{
    var autoLabel = document.createElement('label');
    autoLabel.innerHTML =
      '<input type="checkbox" checked> <span class="mr-group-label">Auto-routed</span>';
    autoLabel.querySelector('input').addEventListener('change', function(ev) {{
      if (ev.target.checked) autoLayer.addTo(map); else map.removeLayer(autoLayer);
    }});
    controls.appendChild(autoLabel);

    if (manualLayers.length) {{
      var sep = document.createElement('span');
      sep.className = 'mr-group-label';
      sep.style.marginLeft = '0.6rem';
      sep.textContent = 'Manual:';
      controls.appendChild(sep);

      manualLayers.forEach(function(entry) {{
        var r = entry.route;
        var lbl = document.createElement('label');
        lbl.innerHTML =
          '<input type="checkbox"' + (r.show !== false ? ' checked' : '') + '>' +
          '<span class="mr-swatch" style="background:' + (r.color || '#6b3a8a') + '33; border-color:' + (r.color || '#6b3a8a') + ';"></span>' +
          '<span>' + r.label + '</span>' +
          '<span class="mr-dist">(' + r.distance_km.toFixed(2) + ' km)</span>';
        lbl.querySelector('input').addEventListener('change', function(ev) {{
          if (ev.target.checked) entry.layer.addTo(map);
          else map.removeLayer(entry.layer);
        }});
        controls.appendChild(lbl);
      }});
    }}
  }}

  // Fit bounds. Include manual routes so they're in view too.
  var fitBounds = [[{bounds['min_lat']}, {bounds['min_lon']}], [{bounds['max_lat']}, {bounds['max_lon']}]];
  if (manualBoundsAll.length) {{
    var lats = manualBoundsAll.map(function(p) {{ return p[0]; }});
    var lons = manualBoundsAll.map(function(p) {{ return p[1]; }});
    fitBounds = [
      [Math.min(fitBounds[0][0], Math.min.apply(null, lats)),
       Math.min(fitBounds[0][1], Math.min.apply(null, lons))],
      [Math.max(fitBounds[1][0], Math.max.apply(null, lats)),
       Math.max(fitBounds[1][1], Math.max.apply(null, lons))]
    ];
  }}
  map.fitBounds(fitBounds, {{padding: [30, 30]}});
}})();
</script>"""


# ── Combined HTML section ────────────────────────────────────────────────────

def generate_map_section(route_data: dict) -> str:
    """Generate the route-map HTML section (Leaflet only)."""
    if (not route_data.get("tracks")
            and not route_data.get("waypoints")
            and not route_data.get("manual_routes")):
        return ""
    return f"""<section id="map">
<h2>Route Map</h2>
<div class="map-online">{route_to_leaflet(route_data)}</div>
</section>"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse and visualize KML/GPX routes")
    parser.add_argument("file", help="KML or GPX file path")
    parser.add_argument("--svg", action="store_true", help="Output SVG only")
    parser.add_argument("--json", action="store_true", help="Output parsed data as JSON")

    args = parser.parse_args()
    data = parse_route_file(args.file)

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    elif args.svg:
        print(route_to_svg(data))
    else:
        print(f"Tracks: {len(data['tracks'])}")
        print(f"Waypoints: {len(data['waypoints'])}")
        for track in data["tracks"]:
            dist = total_distance(track["points"])
            print(f"  {track['name']}: {len(track['points'])} points, {dist:.1f} km")
        for wpt in data["waypoints"]:
            print(f"  📍 {wpt['name']} ({wpt['lat']:.4f}, {wpt['lon']:.4f})")
