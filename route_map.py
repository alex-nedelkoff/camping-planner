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

    # Convert tracks to GeoJSON
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

    for wpt in route_data.get("waypoints", []):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [wpt["lon"], wpt["lat"]]},
            "properties": {"name": wpt["name"], "desc": wpt.get("desc", "")},
        })

    geojson = json.dumps({"type": "FeatureCollection", "features": features})

    return f"""
<div id="{map_id}" style="height:400px;border-radius:10px;z-index:0"></div>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function() {{
  var map = L.map('{map_id}').setView([{bounds['center_lat']}, {bounds['center_lon']}], 12);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 18
  }}).addTo(map);

  var geojson = {geojson};
  var colors = ['#2d5016', '#1565c0', '#c62828', '#6a1b9a'];
  var colorIdx = 0;

  L.geoJSON(geojson, {{
    style: function(feature) {{
      return {{color: colors[colorIdx++ % colors.length], weight: 4, opacity: 0.8}};
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

  // Fit bounds
  map.fitBounds([[{bounds['min_lat']}, {bounds['min_lon']}], [{bounds['max_lat']}, {bounds['max_lon']}]], {{padding: [30, 30]}});
}})();
</script>"""


# ── Combined HTML section ────────────────────────────────────────────────────

def generate_map_section(route_data: dict) -> str:
    """Generate the full map section HTML with both Leaflet and SVG."""
    if not route_data.get("tracks") and not route_data.get("waypoints"):
        return ""

    leaflet_html = route_to_leaflet(route_data)
    svg_html = route_to_svg(route_data)

    # Summary stats
    stats = []
    for track in route_data.get("tracks", []):
        dist = total_distance(track["points"])
        name = track["name"] or "Route"
        stats.append(f"<li><strong>{name}</strong>: {dist:.1f} km</li>")

    stats_html = f"<ul>{''.join(stats)}</ul>" if stats else ""
    wpt_count = len(route_data.get("waypoints", []))
    wpt_note = f"<p>{wpt_count} waypoint(s) marked</p>" if wpt_count else ""

    return f"""<section id="map">
<h2>Route Map</h2>
{stats_html}
{wpt_note}
<div class="map-online">{leaflet_html}</div>
<noscript>{svg_html}</noscript>
<details class="map-offline">
<summary>Offline map (no internet needed)</summary>
{svg_html}
</details>
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
