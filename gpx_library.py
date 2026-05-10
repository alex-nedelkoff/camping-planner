"""
Build a library of real lake-to-lake "connectors" by parsing curated GPX traces.

A connector is the geometry from one lake (lake_a) to an adjacent lake (lake_b)
including: the trailing paddle on lake_a, the portage between them, and the
leading paddle on lake_b. Stitched into one polyline. When route_engine plans
a leg from A to B, it checks the library first and uses the connector's real
geometry. Falls back to OSM portage graph + straight-line paddle when no
library match exists.

Drop GPX files into routes/<park>/library/ and run:

    python3 build_trip.py --refresh-library

to regenerate routes/<park>/library/index.json.
"""
import json
from pathlib import Path
from typing import Optional

import route_map
from route_engine import _haversine_km, _point_in_polygon, LAKE_SUPPLEMENT


def _classify_point(point: list, lakes: list) -> Optional[str]:
    """Return the name of the lake polygon containing this point, or None."""
    for lake in lakes:
        if _point_in_polygon(point, lake["polygon"]):
            return lake["name"]
    return None


def _segment_track(points: list, lakes: list) -> list:
    """Walk a single GPX track, group consecutive points by classification.

    Returns a list of runs, each {state, points}. state is the lake name for
    in-water runs, or None for on-land runs.
    """
    runs: list = []
    if not points:
        return runs
    state = _classify_point(points[0], lakes)
    current = {"state": state, "points": [points[0]]}
    for pt in points[1:]:
        s = _classify_point(pt, lakes)
        if s == state:
            current["points"].append(pt)
        else:
            runs.append(current)
            state = s
            current = {"state": state, "points": [pt]}
    runs.append(current)
    return runs


def _track_distance_km(points: list) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += _haversine_km(points[i - 1], points[i])
    return total


def _extract_connectors(runs: list) -> list:
    """Turn runs into lake-to-lake connectors.

    For each on-land run with paddle runs on both sides AND different lakes,
    emit a connector with approach (lake_a paddle) / portage (overland) /
    departure (lake_b paddle) sub-geometries kept separate. Route_engine
    re-emits these as three tagged segments so the per-day estimate table
    can attribute paddle vs portage distance correctly.

    Land runs at the start or end of a trace are skipped (no lake on one
    side). Same-lake "land" runs (peninsula crossings, GPS noise) are also
    skipped.
    """
    out: list = []
    for i, run in enumerate(runs):
        if run["state"] is not None:
            continue  # paddle run on its own — not a connector
        prev_run = runs[i - 1] if i > 0 else None
        next_run = runs[i + 1] if i + 1 < len(runs) else None
        if prev_run is None or next_run is None:
            continue
        lake_a = prev_run["state"]
        lake_b = next_run["state"]
        if lake_a is None or lake_b is None or lake_a == lake_b:
            continue
        # Use the FULL paddle run on each side. Multi-hop chaining in
        # route_engine drops redundant approaches on non-first hops so the
        # intermediate-lake paddle isn't double-counted.
        approach = [list(p) for p in prev_run["points"]]
        portage = [list(p) for p in run["points"]]
        departure = [list(p) for p in next_run["points"]]
        out.append({
            "lake_a": lake_a,
            "lake_b": lake_b,
            "approach": approach,
            "portage": portage,
            "departure": departure,
            "approach_km": round(_track_distance_km(approach), 3),
            "portage_km": round(_track_distance_km(portage), 3),
            "departure_km": round(_track_distance_km(departure), 3),
        })
    return out


def segment_gpx(gpx_path: Path, lakes: list) -> list:
    """Parse a GPX file and return its lake-to-lake connectors."""
    data = route_map.parse_route_file(str(gpx_path))
    connectors: list = []
    for track in data.get("tracks", []):
        # parse_route_file returns track points as (lat, lon) tuples; normalize.
        points = [[p[0], p[1]] for p in track["points"]]
        runs = _segment_track(points, lakes)
        connectors.extend(_extract_connectors(runs))
    return connectors


def build_library_index(library_dir: Path, osm: dict) -> dict:
    """Walk all *.gpx in library_dir, segment each, combine into an index.

    Returns:
      {
        "connectors": [
          {"lake_a", "lake_b", "geometry", "paddle_km", "portage_km", "source"}
        ]
      }

    Multiple GPX may produce duplicate connectors. We keep all and let
    route_engine pick the shortest-portage match.
    """
    lakes = osm["lakes"] + LAKE_SUPPLEMENT
    connectors: list = []
    if not library_dir.exists():
        return {"connectors": connectors}
    for gpx in sorted(library_dir.glob("*.gpx")):
        for c in segment_gpx(gpx, lakes):
            c["source"] = gpx.name
            connectors.append(c)
    return {"connectors": connectors}


def write_library_index(library_dir: Path, osm: dict) -> Path:
    """Build the index and write it to library_dir/index.json. Returns path."""
    index = build_library_index(library_dir, osm)
    out_path = library_dir / "index.json"
    out_path.write_text(json.dumps(index, indent=2))
    return out_path


def load_library_index(library_dir: Path) -> dict:
    """Read library_dir/index.json. Returns empty index if missing."""
    path = library_dir / "index.json"
    if not path.exists():
        return {"connectors": []}
    return json.loads(path.read_text())


def _build_library_graph(library: dict) -> dict:
    """Adjacency: {lake_name: [(neighbor_name, connector), ...]}."""
    graph: dict = {}
    for c in library.get("connectors", []):
        a, b = c["lake_a"], c["lake_b"]
        graph.setdefault(a, []).append((b, c))
        graph.setdefault(b, []).append((a, c))
    return graph


def find_library_path(lake_a: str, lake_b: str, library: dict,
                      max_hops: int = 5) -> Optional[list]:
    """BFS over library connectors from lake_a to lake_b.

    Returns a list of connectors (oriented lake_a -> lake_b) representing the
    chain, or None if no path exists. Each connector in the result is already
    flipped to read in the requested direction.
    """
    graph = _build_library_graph(library)
    if lake_a not in graph:
        return None
    queue: list = [(lake_a, [])]
    visited = {lake_a}
    while queue:
        current, path = queue.pop(0)
        if current == lake_b:
            return path
        if len(path) >= max_hops:
            continue
        for neighbor, conn in graph.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            # Orient the connector so it reads current -> neighbor.
            if conn["lake_a"] == current and conn["lake_b"] == neighbor:
                oriented = conn
            else:
                oriented = {
                    **conn,
                    "lake_a": current,
                    "lake_b": neighbor,
                    "approach": list(reversed(conn["departure"])),
                    "portage": list(reversed(conn["portage"])),
                    "departure": list(reversed(conn["approach"])),
                    "approach_km": conn["departure_km"],
                    "departure_km": conn["approach_km"],
                }
            queue.append((neighbor, path + [oriented]))
    return None


def find_connector(lake_a: str, lake_b: str, library: dict) -> Optional[dict]:
    """Find a library connector between lake_a and lake_b (any direction).

    Returns the connector with the SHORTEST portage_km when multiple match.
    All sub-geometries (approach, portage, departure) are reversed if needed
    so the result reads from lake_a to lake_b.
    """
    matches = [
        c for c in library.get("connectors", [])
        if {c["lake_a"], c["lake_b"]} == {lake_a, lake_b}
    ]
    if not matches:
        return None
    best = min(matches, key=lambda c: c["portage_km"])
    if best["lake_a"] == lake_a and best["lake_b"] == lake_b:
        return best
    # Reverse direction to match requested orientation. Note: approach and
    # departure swap roles AND each sub-list reverses internally.
    return {
        **best,
        "lake_a": lake_a,
        "lake_b": lake_b,
        "approach": list(reversed(best["departure"])),
        "portage": list(reversed(best["portage"])),
        "departure": list(reversed(best["approach"])),
        "approach_km": best["departure_km"],
        "departure_km": best["approach_km"],
    }
