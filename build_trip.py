"""
Generate a self-contained trip HTML page from a directory of markdown files.

Usage: python3 build_trip.py trips/<trip-name>/
"""
import re
from pathlib import Path

import yaml

SECTION_FILES = ["itinerary", "gear", "food", "packing", "costs"]
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)


def _stringify_dates(obj):
    """Recursively convert date/datetime objects to ISO strings in parsed YAML."""
    import datetime
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(item) for item in obj]
    return obj


def load_trip(trip_dir) -> dict:
    """Parse a trip directory.

    Returns dict with keys:
      frontmatter (dict from trip.md YAML),
      intro (str, markdown body of trip.md after frontmatter),
      itinerary, gear, food, packing, costs (str, markdown content),
      route_file (Path or None — prefers route.gpx over route.kml).
    """
    trip_dir = Path(trip_dir)
    trip_md_path = trip_dir / "trip.md"
    trip_md = trip_md_path.read_text()

    match = FRONTMATTER_RE.match(trip_md)
    if not match:
        raise ValueError(f"{trip_md_path}: missing YAML frontmatter")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    frontmatter = _stringify_dates(frontmatter)
    intro = match.group(2).strip()

    sections = {}
    for name in SECTION_FILES:
        path = trip_dir / f"{name}.md"
        sections[name] = path.read_text() if path.exists() else ""

    route_file = None
    for ext in ("gpx", "kml"):
        candidate = trip_dir / f"route.{ext}"
        if candidate.exists():
            route_file = candidate
            break

    return {
        "frontmatter": frontmatter,
        "intro": intro,
        "route_file": route_file,
        **sections,
    }
