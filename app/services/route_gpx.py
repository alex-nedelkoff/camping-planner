"""Read / write the per-trip route.gpx that the waypoint editor produces.

The file is the source of truth for a hand-edited route. `build_trip.py`
already parses it via `route_map.parse_route_file`, so once we write a fresh
GPX here the existing trip-page Leaflet preview picks it up unchanged.

Format:
  - <wpt> per user waypoint, in order, with a <name>
  - one <trk>/<trkseg> connecting them so the preview renders the polyline
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

GPX_NS = "http://www.topografix.com/GPX/1/1"
CREATOR = "camping-planner waypoint editor"


def _coord(value: float) -> str:
    return f"{value:.6f}"


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_gpx(waypoints: list[dict]) -> str:
    """Serialize a list of {lat, lon, name?} dicts to a deterministic GPX string."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<gpx version="1.1" creator="{CREATOR}" xmlns="{GPX_NS}">',
    ]
    for wpt in waypoints:
        lat = _coord(float(wpt["lat"]))
        lon = _coord(float(wpt["lon"]))
        name = (wpt.get("name") or "").strip()
        lines.append(f'  <wpt lat="{lat}" lon="{lon}">')
        if name:
            lines.append(f"    <name>{_xml_escape(name)}</name>")
        lines.append("  </wpt>")

    if len(waypoints) >= 2:
        lines.append("  <trk>")
        lines.append("    <name>Route</name>")
        lines.append("    <trkseg>")
        for wpt in waypoints:
            lat = _coord(float(wpt["lat"]))
            lon = _coord(float(wpt["lon"]))
            lines.append(f'      <trkpt lat="{lat}" lon="{lon}" />')
        lines.append("    </trkseg>")
        lines.append("  </trk>")

    lines.append("</gpx>")
    return "\n".join(lines) + "\n"


def parse_gpx(text: str) -> list[dict]:
    """Read back the waypoints written by render_gpx.

    Only <wpt> elements are returned — the <trk> exists for the preview but
    is fully determined by the waypoints, so we don't round-trip it.
    """
    root = ET.fromstring(text)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    out: list[dict] = []
    for wpt in root.findall(f"{ns}wpt"):
        lat = wpt.get("lat")
        lon = wpt.get("lon")
        if lat is None or lon is None:
            continue
        name_el = wpt.find(f"{ns}name")
        name = (name_el.text or "").strip() if name_el is not None else ""
        out.append({"lat": float(lat), "lon": float(lon), "name": name})
    return out


def load_waypoints(trip_dir: Path) -> list[dict]:
    path = trip_dir / "route.gpx"
    if not path.is_file():
        return []
    return parse_gpx(path.read_text())


def save_waypoints(trip_dir: Path, waypoints: list[dict]) -> Path:
    path = trip_dir / "route.gpx"
    path.write_text(render_gpx(waypoints))
    return path


# ── Distance helpers (used by editor for live readout & by future estimators) ──

_EARTH_KM = 6371.0088


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(h))


def total_distance_km(waypoints: list[dict]) -> float:
    """Sum of haversine distances between consecutive waypoints."""
    if len(waypoints) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(waypoints)):
        prev = (waypoints[i - 1]["lat"], waypoints[i - 1]["lon"])
        curr = (waypoints[i]["lat"], waypoints[i]["lon"])
        total += haversine_km(prev, curr)
    return total
