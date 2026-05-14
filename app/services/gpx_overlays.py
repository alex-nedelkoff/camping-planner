"""Parse the bundled Killarney GPX files into GeoJSON feature collections.

Two sources today:
  - killarneyCampsites.gpx  — Paddle Planner campsite waypoints (~100+)
  - killarneyPortages.gpx   — 220 trail-head waypoints, paired by <name>
                               into 110 portage line segments

Both files are looked up via the same DATA_DIR / parent-repo fallback as
the lake caches (see lake_layers._candidate_dirs).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from app.services.lake_layers import _find

GPX_NS = "{http://www.topografix.com/GPX/1/1}"


def _text(el, tag: str) -> str:
    child = el.find(f"{GPX_NS}{tag}")
    return (child.text or "").strip() if child is not None and child.text else ""


def _parse_waypoints(path: Path) -> list[dict]:
    """Return [{lat, lon, name, desc, sym, type}, ...] from <wpt> elements."""
    if path is None or not path.is_file():
        return []
    root = ET.parse(path).getroot()
    out: list[dict] = []
    for wpt in root.findall(f"{GPX_NS}wpt"):
        try:
            lat = float(wpt.get("lat"))
            lon = float(wpt.get("lon"))
        except (TypeError, ValueError):
            continue
        out.append({
            "lat": lat, "lon": lon,
            "name": _text(wpt, "name"),
            "desc": _text(wpt, "desc"),
            "sym":  _text(wpt, "sym"),
            "type": _text(wpt, "type"),
        })
    return out


# ── Campsites ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=2)
def campsites_geojson() -> dict:
    """Return campsites as a GeoJSON FeatureCollection of Point features."""
    path = _find("killarneyCampsites.gpx")
    if path is None:
        return {"type": "FeatureCollection", "features": []}
    features: list[dict] = []
    for w in _parse_waypoints(path):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [w["lon"], w["lat"]]},
            "properties": {
                "kind": "campsite",
                "name": w["name"],            # e.g. "1", "2", "61"
                "desc": w["desc"],
                "type": w["type"],            # Open-Potential, Verified, etc.
            },
        })
    return {"type": "FeatureCollection", "features": features}


# ── Portages (220 trail-head wpts → 110 line segments) ────────────────────

_LEN_M_RE = re.compile(r"~?\s*([\d,]+)\s*meters", re.IGNORECASE)


def _portage_length_m(desc: str) -> float | None:
    m = _LEN_M_RE.search(desc or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


@lru_cache(maxsize=2)
def portages_geojson() -> dict:
    """Pair the two trail-head waypoints per portage into a LineString."""
    path = _find("killarneyPortages.gpx")
    if path is None:
        return {"type": "FeatureCollection", "features": []}
    pairs: dict[str, list[dict]] = {}
    for w in _parse_waypoints(path):
        pairs.setdefault(w["name"], []).append(w)

    features: list[dict] = []
    for name, ends in pairs.items():
        if len(ends) < 2:
            continue
        # If there are >2 endpoints, take the first two (Killarney data has
        # exactly 2 for every portage today; this is defensive).
        a, b = ends[0], ends[1]
        length_m = _portage_length_m(a["desc"]) or _portage_length_m(b["desc"])
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[a["lon"], a["lat"]], [b["lon"], b["lat"]]],
            },
            "properties": {
                "kind": "portage",
                "name": name,
                "length_m": length_m,
                "length_km": round(length_m / 1000, 3) if length_m else None,
                "desc": a["desc"] or b["desc"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


# ── Dispatch ──────────────────────────────────────────────────────────────

_PARK_GPX = {
    "killarney": {"campsites": campsites_geojson, "portages": portages_geojson},
}


def overlays_for(park: str) -> dict[str, dict]:
    spec = _PARK_GPX.get(park)
    if not spec:
        return {}
    return {name: producer() for name, producer in spec.items()}
