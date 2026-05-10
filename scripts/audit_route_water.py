"""
Sample every route segment at fixed GPS spacing, check which samples fall
inside any Jeff polygon (named OR unnamed), and print a comparison table.

Usage:
    python3 scripts/audit_route_water.py [--trip trips/killarney-2026-05/]
                                         [--spacing-m 50]
                                         [--source jeffs|osm|both]

This is a diagnostic / sanity-check tool. It doesn't write HTML or modify
caches. Output goes to stdout: per-segment counts, percent-in-water, and
the first GPS sample point that fails the water test (so you can paste
into the overlay map URL fragment to see exactly where the route leaves
water).
"""
import argparse
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import build_trip
import gpx_library
import osm_data
import route_engine
from route_engine import _haversine_km, _point_in_polygon


def _interpolate(p1, p2, t):
    return [p1[0] + t * (p2[0] - p1[0]),
            p1[1] + t * (p2[1] - p1[1])]


def _sample_polyline(geometry, spacing_km):
    """Walk a polyline and yield sample points spaced ~spacing_km apart in GPS."""
    if len(geometry) < 2:
        return
    for i in range(len(geometry) - 1):
        a, b = geometry[i], geometry[i + 1]
        seg_km = _haversine_km(a, b)
        if seg_km == 0:
            yield list(a)
            continue
        n_samples = max(1, math.ceil(seg_km / spacing_km))
        for s in range(n_samples):
            t = s / n_samples
            yield _interpolate(a, b, t)
    # Always yield the very last point too.
    yield list(geometry[-1])


def _polygons_for_test(source: str, osm_features: dict, jeffs_cache: dict) -> list:
    """Return the list of polygons to test sample points against."""
    out = []
    if source in ("jeffs", "both"):
        for lake in jeffs_cache.get("lakes", []):
            polygon = lake.get("polygon") or []
            if polygon:
                out.append(polygon)
    if source in ("osm", "both"):
        for lake in osm_features.get("lakes", []):
            polygon = lake.get("polygon") or []
            if polygon:
                out.append(polygon)
    return out


def _is_in_any(point, polygons) -> bool:
    for poly in polygons:
        if _point_in_polygon(point, poly):
            return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trip", default=str(REPO_ROOT / "trips" / "killarney-2026-05"),
                        help="Path to trip directory.")
    parser.add_argument("--spacing-m", type=int, default=50,
                        help="Sample spacing in meters (default 50, ~20px at "
                             "zoom 6 mosaic).")
    parser.add_argument("--source", choices=["jeffs", "osm", "both"], default="jeffs",
                        help="Which polygon set to test against (default jeffs).")
    parser.add_argument("--show-bad-points", type=int, default=3,
                        help="Print up to N out-of-water sample coords per "
                             "segment (default 3).")
    args = parser.parse_args(argv)

    trip = build_trip.load_trip(Path(args.trip))
    fm = trip.get("frontmatter") or {}
    if not (fm.get("nights") and fm.get("access_point")):
        print("Trip frontmatter missing 'nights' or 'access_point'", file=sys.stderr)
        return 2
    osm_features = osm_data.load_killarney_features()
    library = gpx_library.load_library_index(REPO_ROOT / "routes" / "killarney" / "library")
    route = route_engine.build_route(
        nights=fm["nights"], access_point=fm["access_point"],
        osm=osm_features, library=library,
    )

    # Load Jeff's cache directly so we get unnamed polygons too. The
    # osm_features merge keeps both, but easier to read directly.
    import json
    jeffs_path = REPO_ROOT / "jeffs_killarney_cache.json"
    jeffs_cache = json.loads(jeffs_path.read_text()) if jeffs_path.exists() else {}

    polygons = _polygons_for_test(args.source, osm_features, jeffs_cache)
    print(f"Testing against {len(polygons)} polygons "
          f"(source={args.source}, spacing={args.spacing_m}m)")
    print()

    spacing_km = args.spacing_m / 1000.0
    headers = ["Day", "Kind", "From → To", "Samples", "InWater", "%", "First-bad GPS"]
    print(f"{headers[0]:<18} {headers[1]:<8} {headers[2]:<55} "
          f"{headers[3]:>7} {headers[4]:>7} {headers[5]:>5}  {headers[6]}")
    print("-" * 130)

    total_samples = 0
    total_in = 0
    bad_segments = 0

    for seg in route["segments"]:
        geom = seg.get("geometry") or []
        if len(geom) < 2:
            continue
        samples = list(_sample_polyline(geom, spacing_km))
        n_total = len(samples)
        in_count = 0
        bad_points = []
        for pt in samples:
            if _is_in_any(pt, polygons):
                in_count += 1
            else:
                if len(bad_points) < args.show_bad_points:
                    bad_points.append(pt)

        pct = (in_count / n_total * 100) if n_total else 0
        label = f"{seg['from']} → {seg['to']}"
        bad_str = ""
        if bad_points:
            bad_str = "; ".join(f"[{p[0]:.5f}, {p[1]:.5f}]" for p in bad_points)
            bad_segments += 1

        print(f"{seg['day']:<18} {seg['kind']:<8} {label[:53]:<55} "
              f"{n_total:>7} {in_count:>7} {pct:>4.0f}%  {bad_str}")
        total_samples += n_total
        total_in += in_count

    print("-" * 130)
    overall_pct = (total_in / total_samples * 100) if total_samples else 0
    print(f"Total: {total_samples} samples, {total_in} in water "
          f"({overall_pct:.1f}%); {bad_segments}/{len(route['segments'])} "
          f"segments have at least one out-of-water sample.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
