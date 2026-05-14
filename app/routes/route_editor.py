"""Waypoint editor: JSON read/write + map-overlay endpoints.

The editor UI lives in the SPA (see app/static/js/route_edit.js, mounted
by the /trips/{slug}/route-edit route in app/static/js/index.js). The
backend just provides:

    GET  /api/trips/{slug}/route        — list current waypoints
    POST /api/trips/{slug}/route        — save waypoints to route.gpx
    GET  /api/lakes/{park}              — GeoJSON layers (OSM + Jeff's +
                                          CanVec lakes + GPX campsites
                                          + GPX portages)
    GET  /api/raster/{park}.jpg         — Jeff's Maps raster mosaic
                                          (Web Mercator) for imageOverlay

All endpoints are public to mirror the rest of the per-trip API today;
auth can be layered on later when collab editing lands.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import TRIPS_DIR
from app.services import gpx_overlays, lake_layers, route_gpx


# Jeff's raster mosaic. The full-park mosaic is built by
# scripts/build_jeffs_mosaic.py and writes a sidecar .json alongside the
# JPG with the actual bounds. We try that first, then fall back to the
# older overlay raster (smaller bbox).
PARK_RASTERS: dict[str, dict] = {
    "killarney": {
        "candidates": [
            ("jeffs_killarney_mosaic.jpg", "jeffs_killarney_mosaic.json"),
            ("jeffs_osm_overlay_raster.jpg", None),
        ],
        "fallback_bounds": [[45.994671, -81.622408], [46.102587, -81.31039]],
    },
}


def _raster_info(park: str) -> dict | None:
    spec = PARK_RASTERS.get(park)
    if not spec:
        return None
    for jpg_name, sidecar_name in spec["candidates"]:
        jpg = lake_layers._find(jpg_name)
        if jpg is None:
            continue
        bounds = spec["fallback_bounds"]
        if sidecar_name:
            sidecar = lake_layers._find(sidecar_name)
            if sidecar is not None:
                try:
                    bounds = _json.loads(sidecar.read_text())["bounds"]
                except Exception:
                    pass
        return {"path": jpg, "bounds": bounds, "filename": jpg_name}
    return None


router = APIRouter(prefix="/api")


# ── Schemas ────────────────────────────────────────────────────────────────

class Waypoint(BaseModel):
    lat: float
    lon: float
    name: str = ""


class SaveRouteRequest(BaseModel):
    waypoints: list[Waypoint] = Field(default_factory=list)


def _ensure_trip(slug: str) -> Path:
    trip_dir = TRIPS_DIR / slug
    if not slug or not trip_dir.is_dir():
        raise HTTPException(status_code=404, detail={"ok": False, "error": "trip not found"})
    return trip_dir


# ── Waypoint CRUD ─────────────────────────────────────────────────────────

@router.get("/trips/{slug}/route")
def get_route(slug: str):
    trip_dir = _ensure_trip(slug)
    wpts = route_gpx.load_waypoints(trip_dir)
    return {
        "waypoints": wpts,
        "total_km": round(route_gpx.total_distance_km(wpts), 2),
    }


@router.post("/trips/{slug}/route")
def save_route(slug: str, body: SaveRouteRequest):
    trip_dir = _ensure_trip(slug)
    wpts = [w.model_dump() for w in body.waypoints]
    route_gpx.save_waypoints(trip_dir, wpts)
    return {
        "ok": True,
        "saved": len(wpts),
        "total_km": round(route_gpx.total_distance_km(wpts), 2),
    }


# ── Map overlays ──────────────────────────────────────────────────────────

@router.get("/lakes/{park}")
def get_lakes(park: str):
    """Lake/portage/campsite overlays for a park, keyed by source."""
    lakes = lake_layers.layers_for(park)
    gpx = gpx_overlays.overlays_for(park)
    if not lakes and not gpx:
        raise HTTPException(status_code=404, detail={"error": f"no layers for park {park!r}"})
    return {**lakes, **gpx}


# ── Editor metadata + raster ──────────────────────────────────────────────

@router.get("/raster/{park}.jpg")
def get_raster(park: str):
    info = _raster_info(park)
    if info is None:
        raise HTTPException(status_code=404, detail={"error": f"no raster for park {park!r}"})
    return FileResponse(
        info["path"], media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# Defaults for the editor view (centre + zoom + raster bounds). The SPA
# fetches this on entry so it doesn't need to bake park metadata in JS.
PARK_CENTRES: dict[str, tuple[float, float]] = {
    "killarney": (46.01, -81.40),
    "algonquin-canisbay": (45.5762, -78.5333),
    "algonquin-pog": (45.5660, -78.3733),
    "algonquin-rock-lake": (45.5283, -78.3650),
    "algonquin-mew-lake": (45.5803, -78.5067),
    "algonquin-two-rivers": (45.5825, -78.4825),
    "algonquin-backcountry": (45.6500, -78.3500),
    "killbear": (45.3500, -80.2167),
    "frontenac": (44.5167, -76.5500),
    "bon-echo": (44.8930, -77.2070),
    "french-river": (46.0500, -80.5000),
    "grundy-lake": (45.9333, -80.5333),
    "massasauga": (45.2167, -80.0000),
}


def _park_from_trip(trip_dir: Path) -> str | None:
    md = trip_dir / "trip.md"
    if not md.is_file():
        return None
    text = md.read_text()
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        line = line.strip()
        if line.startswith("park:"):
            return line.split(":", 1)[1].strip() or None
    return None


@router.get("/trips/{slug}/route-meta")
def route_meta(slug: str):
    """Bootstrap payload for the editor: park, centre, raster URL + bounds, seed waypoints."""
    trip_dir = _ensure_trip(slug)
    park = _park_from_trip(trip_dir) or "killarney"
    centre = PARK_CENTRES.get(park) or PARK_CENTRES["killarney"]
    info = _raster_info(park)
    raster_url: str | None = None
    raster_bounds = None
    if info is not None:
        mtime = int(info["path"].stat().st_mtime)
        raster_url = f"/api/raster/{park}.jpg?v={mtime}"
        raster_bounds = info["bounds"]
    return {
        "slug": slug,
        "park": park,
        "centre": list(centre),
        "zoom": 12,
        "raster_url": raster_url,
        "raster_bounds": raster_bounds,
        "waypoints": route_gpx.load_waypoints(trip_dir),
    }
