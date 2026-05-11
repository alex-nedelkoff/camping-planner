"""
GPX loaders for Killarney campsite + portage data sourced from
paddleplanner.com. Pure parsing — no I/O beyond reading the supplied path.

Exposed functions:
  load_campsites(path) -> list of campsite dicts
  load_portages(path)  -> list of portage dicts (paired endpoints)
"""
import logging
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

_NS = {"g": "http://www.topografix.com/GPX/1/1"}


def _parse_gpx(path: Path):
    """Parse the GPX file and return (tree, root). Raises ValueError on
    malformed XML."""
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as e:
        raise ValueError(f"Malformed GPX at {path}: {e}") from e
    return tree, tree.getroot()


def load_campsites(path: Path) -> list:
    """Parse a campsite GPX file.

    Returns: list of {"name": str, "lat": float, "lon": float, "desc": str}.
    """
    _, root = _parse_gpx(path)
    out = []
    for wpt in root.findall("g:wpt", _NS):
        name_el = wpt.find("g:name", _NS)
        desc_el = wpt.find("g:desc", _NS)
        name = (name_el.text if name_el is not None else "") or ""
        desc = (desc_el.text if desc_el is not None else "") or ""
        out.append({
            "name": name,
            "lat": float(wpt.attrib["lat"]),
            "lon": float(wpt.attrib["lon"]),
            "desc": desc,
        })
    return out


_METERS_RE = re.compile(r"~?\s*(\d+(?:\.\d+)?)\s*meters?", re.IGNORECASE)


def _haversine_km(a: list, b: list) -> float:
    """Distance in km between [lat, lon] points."""
    R = 6371.0
    p1 = math.radians(a[0])
    p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))


def _length_km_from_desc(desc: str, endpoints: list) -> float:
    """Parse '~117 meters' from description. Fall back to haversine of
    endpoints if no match."""
    m = _METERS_RE.search(desc or "")
    if m:
        try:
            return float(m.group(1)) / 1000.0
        except ValueError:
            pass
    return _haversine_km(endpoints[0], endpoints[1])


def load_portages(path: Path) -> list:
    """Parse a portage GPX file.

    Two GPX waypoints sharing a name are paired into one portage record
    matching the OSM portage shape (so the route engine treats both
    sources identically). Orphans (single waypoint with a given name) are
    dropped with a logger warning.

    Returns: list of {
        "name": str,
        "endpoints": [[lat, lon], [lat, lon]],
        "line":      [[lat, lon], [lat, lon]],  # straight-line between endpoints
        "length_km": float,
        "source":    "gpx",
    }
    """
    _, root = _parse_gpx(path)
    # Group waypoints by name.
    by_name: dict = {}
    for wpt in root.findall("g:wpt", _NS):
        name_el = wpt.find("g:name", _NS)
        desc_el = wpt.find("g:desc", _NS)
        name = (name_el.text if name_el is not None else "") or ""
        desc = (desc_el.text if desc_el is not None else "") or ""
        lat = float(wpt.attrib["lat"])
        lon = float(wpt.attrib["lon"])
        by_name.setdefault(name, []).append(([lat, lon], desc))

    out = []
    for name, entries in by_name.items():
        if len(entries) != 2:
            logger.warning(
                "Portage %s has %d waypoint(s), expected 2 — skipping",
                name, len(entries),
            )
            continue
        endpoints = [entries[0][0], entries[1][0]]
        desc = entries[0][1] or entries[1][1] or ""
        length_km = _length_km_from_desc(desc, endpoints)
        out.append({
            "name": name,
            "endpoints": endpoints,
            "line": [list(endpoints[0]), list(endpoints[1])],
            "length_km": round(length_km, 6),
            "source": "gpx",
        })
    return out
