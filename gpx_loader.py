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
