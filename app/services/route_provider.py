"""Route rendering: renders trip routes (manual + auto-computed) to HTML.

Source of routes:
  - `manual_routes.json` (drawn in /overlay/) is a dict {_meta, routes: [...]}.
    Each route has {label, geometry: [[lat,lon],...], distance_km, color, show}.
  - Auto-routes can also be built from trip metadata (nights + access_point)
    via route_engine.build_route, but that requires loading OSM/Jeff's caches
    and is heavier. Skipped here for the minimal display.

For now this module renders only the manual routes (which is what the user
draws in the overlay). Auto-route rendering can be added later behind a
config flag if needed — `_render_auto_route` below is preserved for that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import route_engine as _route_engine
import route_map as _route_map


def _normalize_routes_payload(payload) -> list:
    """Coerce manual_routes.json content into a list of route dicts.

    Accepts:
      - {"routes": [...]}  (current overlay format)
      - [...]              (legacy / alternate format)
      - {} / None / []     -> []
    """
    if not payload:
        return []
    routes = payload.get("routes") if isinstance(payload, dict) else payload
    if not isinstance(routes, list):
        return []
    out = []
    for r in routes:
        if not isinstance(r, dict):
            continue
        geom = r.get("geometry") or []
        if not isinstance(geom, list) or len(geom) < 2:
            continue
        try:
            pts = [[float(p[0]), float(p[1])] for p in geom]
        except (TypeError, ValueError, IndexError):
            continue
        out.append({
            "label": r.get("label") or "manual route",
            "geometry": pts,
            "distance_km": float(r.get("distance_km") or 0.0),
            "show": r.get("show", True) is not False,
            "color": r.get("color") or "#6b3a8a",
        })
    return out


def render(routes_payload, trip_slug: str) -> dict[str, Any]:
    """Return {html, distance_km, empty} for the trip page's Route section.

    routes_payload is whatever's in manual_routes.json (a dict in the current
    schema). On empty/missing payload, returns the empty marker so the
    template shows the "no routes drawn yet" hint.
    """
    routes = _normalize_routes_payload(routes_payload)
    if not routes:
        return {"html": "", "distance_km": 0, "empty": True}

    total_km = sum(r["distance_km"] for r in routes)

    map_html = _route_map.generate_map_section({
        "waypoints": [],
        "tracks": [],
        "source": "manual",
        "manual_routes": routes,
    })

    return {
        "html": map_html,
        "distance_km": round(total_km, 1),
        "empty": False,
    }


# ---------------------------------------------------------------------------
# Legacy auto-route renderer (kept for future use; not called by render()).
# Preserved verbatim from build_trip.py except the apostrophe-escaping fix on
# the overlay link text.
# ---------------------------------------------------------------------------

def _load_manual_routes(trip_dir) -> list:
    """Read trips/<slug>/manual_routes.json if present."""
    if trip_dir is None:
        return []
    path = Path(trip_dir) / "manual_routes.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return _normalize_routes_payload(data)


def _render_auto_route(route: dict, trip_dir=None) -> str:
    """Render the OSM-driven route section: map + per-day estimates table.

    Expects `route` to be the output of route_engine.build_route(...) — a dict
    with `segments`, `markers`, optionally `warnings`. NOT the contents of
    manual_routes.json. See `render()` above for that path.
    """
    days = _route_engine.build_day_estimates(route["segments"])

    tracks = []
    for seg in route["segments"]:
        if not seg["geometry"]:
            continue
        track_name = f"{seg['from']} -> {seg['to']} ({seg['kind']})"
        tracks.append({
            "name": track_name,
            "points": [tuple(pt) for pt in seg["geometry"]],
        })
    waypoints = [
        {
            "lat": m["lat"], "lon": m["lon"], "name": m["label"], "desc": "",
            "kind": m.get("kind"),
            "site_number": m.get("site_number"),
        }
        for m in route.get("markers", [])
    ]
    for seg in route["segments"]:
        if seg["kind"] != "portage" or len(seg["geometry"]) < 2:
            continue
        entry = seg["geometry"][0]
        exit_ = seg["geometry"][-1]
        dist = seg["distance_km"]
        waypoints.append({
            "lat": entry[0], "lon": entry[1],
            "name": f"Portage take-out -> {seg['to']}", "desc": f"{dist} km",
        })
        waypoints.append({
            "lat": exit_[0], "lon": exit_[1],
            "name": f"Portage put-in <- {seg['from']}", "desc": f"{dist} km",
        })
    manual_routes = _load_manual_routes(trip_dir)
    map_html = _route_map.generate_map_section({
        "waypoints": waypoints, "tracks": tracks, "source": "auto",
        "manual_routes": manual_routes,
    })

    rows = []
    total_paddle = 0.0
    total_portage = 0.0
    total_minutes = 0
    for day in days:
        approx_marker = " &#9888;" if day["approx"] else ""
        portage_cell = (
            "(approx)" if day["approx"] and day["portage_km"] == 0
            else f"{day['portage_km']} km"
        )
        rows.append(
            f"<tr><td>{day['day']}</td>"
            f"<td>{day['label']}{approx_marker}</td>"
            f"<td>{day['paddle_km']} km</td>"
            f"<td>{portage_cell}</td>"
            f"<td>{day['human_time']}</td></tr>"
        )
        total_paddle += day["paddle_km"]
        total_portage += day["portage_km"]
        total_minutes += day["minutes"]

    rows.append(
        f"<tr><td><strong>Total</strong></td><td></td>"
        f"<td><strong>{round(total_paddle, 1)} km</strong></td>"
        f"<td><strong>{round(total_portage, 1)} km</strong></td>"
        f"<td><strong>{_route_engine.format_human_time(total_minutes)}</strong></td></tr>"
    )

    if manual_routes:
        rows.append(
            "<tr><td colspan='5' style='padding-top:0.6rem;"
            "border-top:1px dashed #c8bfa3;font-size:0.85rem;"
            "color:#6b5a3a;letter-spacing:0.04em;text-transform:uppercase;'>"
            "Manual routes</td></tr>"
        )
        for r in manual_routes:
            dist = round(r["distance_km"], 1)
            minutes = _route_engine.estimate_minutes(dist, 0.0)
            swatch = (
                f"<span style='display:inline-block;width:10px;height:10px;"
                f"background:{r['color']};border-radius:2px;"
                f"margin-right:0.4rem;vertical-align:middle'></span>"
            )
            rows.append(
                f"<tr><td>-</td>"
                f"<td>{swatch}{r['label']}</td>"
                f"<td>{dist} km</td><td>-</td>"
                f"<td>{_route_engine.format_human_time(minutes)}</td></tr>"
            )

    warnings_html = ""
    if route.get("warnings"):
        items = "".join(f"<li>{w}</li>" for w in route["warnings"])
        warnings_html = f'<div class="warnings"><ul>{items}</ul></div>'

    table_html = (
        "<table><thead><tr><th>Day</th><th>Leg</th>"
        "<th>Paddle</th><th>Portage</th><th>Est. time</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )

    return (
        f'<section id="route"><h2>Route</h2>'
        f"{warnings_html}"
        f"{map_html}"
        f"{table_html}"
        f"</section>"
    )
