"""Route rendering: converts route payloads to HTML sections with maps and tables.

Self-contained implementation extracted from build_trip.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import route_engine as _route_engine
import route_map as _route_map


def _load_manual_routes(trip_dir) -> list:
    """Read trips/<slug>/manual_routes.json if present.

    Schema: { "routes": [{ "label", "geometry": [[lat,lon],...], "distance_km",
                           "show": bool, "color": "#hex" }] }
    Returns the list of route dicts (empty if file absent or malformed).
    """
    if trip_dir is None:
        return []
    path = Path(trip_dir) / "manual_routes.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    routes = data.get("routes") or []
    out = []
    for r in routes:
        geom = r.get("geometry") or []
        if not isinstance(geom, list) or len(geom) < 2:
            continue
        out.append({
            "label": r.get("label") or "manual route",
            "geometry": [[float(p[0]), float(p[1])] for p in geom],
            "distance_km": float(r.get("distance_km") or 0.0),
            "show": r.get("show", True) is not False,
            "color": r.get("color") or "#6b3a8a",
        })
    return out


def _render_auto_route(route: dict, trip_dir=None) -> str:
    """Render the OSM-driven route section: map + per-day estimates table."""
    days = _route_engine.build_day_estimates(route["segments"])

    # Build a route_map-compatible structure to pass to generate_map_section.
    tracks = []
    for seg in route["segments"]:
        if not seg["geometry"]:
            continue
        # Each segment becomes a track; route_map.py will color-cycle them.
        track_name = f"{seg['from']} → {seg['to']} ({seg['kind']})"
        tracks.append({
            "name": track_name,
            "points": [tuple(pt) for pt in seg["geometry"]],
        })
    # Markers (access point + per-night site centroids) become Leaflet pins.
    # `kind` + `site_number` flow through so route_map.py can render numbered
    # badges instead of generic circles for nights and the access point.
    waypoints = [
        {
            "lat": m["lat"], "lon": m["lon"], "name": m["label"], "desc": "",
            "kind": m.get("kind"),
            "site_number": m.get("site_number"),
        }
        for m in route.get("markers", [])
    ]
    # Add portage entry/exit pins for each portage actually used in the route.
    for seg in route["segments"]:
        if seg["kind"] != "portage" or len(seg["geometry"]) < 2:
            continue
        entry = seg["geometry"][0]
        exit_ = seg["geometry"][-1]
        dist = seg["distance_km"]
        waypoints.append({
            "lat": entry[0], "lon": entry[1],
            "name": f"Portage take-out → {seg['to']}", "desc": f"{dist} km",
        })
        waypoints.append({
            "lat": exit_[0], "lon": exit_[1],
            "name": f"Portage put-in ← {seg['from']}", "desc": f"{dist} km",
        })
    manual_routes = _load_manual_routes(trip_dir)
    map_html = _route_map.generate_map_section({
        "waypoints": waypoints, "tracks": tracks, "source": "auto",
        "manual_routes": manual_routes,
    })

    # Per-day estimates table.
    rows = []
    total_paddle = 0.0
    total_portage = 0.0
    total_minutes = 0
    for day in days:
        approx_marker = " ⚠" if day["approx"] else ""
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

    # Manual routes get their own rows below the auto-routed totals so we can
    # compare hand-drawn alternates against the engine's per-day estimates.
    # Treat each manual route as 100% paddle for time estimation.
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
                f"<tr><td>—</td>"
                f"<td>{swatch}{r['label']}</td>"
                f"<td>{dist} km</td><td>—</td>"
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

    overlay_link = (
        '<p class="overlay-link" style="margin:0.4rem 0 0.8rem;'
        'font-size:0.88rem">'
        '<a href="/overlay/" target="_blank" rel="noopener" '
        'style="color:#6b3a8a;text-decoration:none;'
        'border-bottom:1px dashed #6b3a8a">'
        'Open detailed map overlay &rarr;</a>'
        ' <span style="color:#888">draw / edit manual routes against raw '
        'OSM, CanVec, Jeff's, and GPX layers</span></p>'
    )

    return (
        f'<section id="route"><h2>Route</h2>'
        f"{warnings_html}"
        f"{overlay_link}"
        f"{map_html}"
        f"{table_html}"
        f"</section>"
    )


def render(routes_payload: list, trip_slug: str) -> dict[str, Any]:
    """Render routes to an HTML block + summary stats."""
    if not routes_payload:
        return {"html": "", "distance_km": 0, "empty": True}
    parts = []
    total_km = 0.0
    for route in routes_payload:
        block = _render_auto_route(route)
        parts.append(block)
        total_km += float(route.get("distance_km", 0) or 0)
    return {
        "html": "\n".join(parts),
        "distance_km": round(total_km, 1),
        "empty": False,
    }
