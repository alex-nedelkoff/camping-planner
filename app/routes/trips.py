"""Trip API endpoints (read + write via new /api/trips/* routes)."""

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from datetime import date as _date_t

from app.models import (
    OkResponse,
    TripsListResponse,
    TripListEntry,
)
from app.models_trip import (
    TripItem, FoodSlot, CostRow, ItineraryDay, Trip,
)
from app.services import trip_store, trips as trips_svc

router = APIRouter(prefix="/api")

# (model_class, field_name, is_list_of_model)
SECTION_FIELD_MAP = {
    "gear":      (TripItem,    "gear",      True),   # unified gear+packing list
    "food":      (FoodSlot,    "food",      True),
    "costs":     (CostRow,     "costs",     True),
    "itinerary": (ItineraryDay, "itinerary", True),
}


@router.get("/trips", response_model=TripsListResponse)
def list_trips():
    entries = trips_svc.list_trips_v2()
    return TripsListResponse(
        trips=[TripListEntry(**e) for e in entries]
    )


@router.get("/trips/{slug}")
def get_trip(slug: str):
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        t = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return t.model_dump(mode="json")


@router.post("/trips/{slug}/refresh-weather", response_model=OkResponse)
def refresh_weather(slug: str):
    trip_dir = trips_svc.TRIPS_DIR / slug
    if not trip_store.exists(trip_dir):
        raise HTTPException(status_code=404, detail="trip not found")
    t = trip_store.load(trip_dir)
    # weather_cache uses column-based key (park, start_date, end_date) — delete directly
    from app.services.db import connect
    with connect() as conn:
        conn.execute(
            "DELETE FROM weather_cache WHERE park = ? AND start_date = ?",
            (t.park or "", str(t.dates.start)),
        )
    return OkResponse(ok=True, message="weather cache cleared")


@router.post("/trips/{slug}/refresh-route", response_model=OkResponse)
def refresh_route(slug: str):
    from app.services import route_cache
    trip_dir = trips_svc.TRIPS_DIR / slug
    if not trip_store.exists(trip_dir):
        raise HTTPException(status_code=404, detail="trip not found")
    route_cache.invalidate(slug)
    return OkResponse(ok=True, message="route cache cleared")


@router.patch("/trips/{slug}/meta")
def patch_meta(slug: str, body: dict = Body(...)):
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        trip = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(404)
    allowed = {"park", "dates", "participants", "access_point", "nights"}
    bad = set(body) - allowed
    if bad:
        raise HTTPException(400, detail={"error": f"unknown fields: {sorted(bad)}"})
    data = trip.model_dump(mode="json")
    data.update(body)
    try:
        new_trip = Trip.model_validate(data)
    except Exception as exc:
        raise HTTPException(422, detail=str(exc))
    trip_store.save(trip_dir, new_trip)
    return new_trip.model_dump(mode="json")


@router.put("/trips/{slug}/section/{name}")
def put_section(slug: str, name: str, body=Body(...)):
    if name not in SECTION_FIELD_MAP:
        raise HTTPException(400, detail={"error": f"unknown section: {name}"})
    model, field, is_list = SECTION_FIELD_MAP[name]
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        trip = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(404)
    try:
        if is_list:
            validated = [model.model_validate(item) for item in body]
            field_value = [v.model_dump(mode="json") for v in validated]
        else:
            validated_obj = model.model_validate(body)
            field_value = validated_obj.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(422, detail=str(exc))
    data = trip.model_dump(mode="json")
    data[field] = field_value
    new_trip = Trip.model_validate(data)
    trip_store.save(trip_dir, new_trip)
    return new_trip.model_dump(mode="json")


import json as _json


@router.put("/trips/{slug}/routes")
def put_routes(slug: str, body=Body(...)):
    trip_dir = trips_svc.TRIPS_DIR / slug
    if not trip_store.exists(trip_dir):
        raise HTTPException(404)
    if not isinstance(body, list):
        raise HTTPException(400, detail={"error": "expected list of routes"})
    (trip_dir / "manual_routes.json").write_text(
        _json.dumps(body, indent=2) + "\n", encoding="utf-8"
    )
    from app.services import route_cache
    route_cache.invalidate(slug)
    return {"ok": True}


@router.get("/trips/{slug}/routes")
def get_routes(slug: str):
    trip_dir = trips_svc.TRIPS_DIR / slug
    p = trip_dir / "manual_routes.json"
    if not p.exists():
        return []
    return _json.loads(p.read_text())


class CreateTripRequest(BaseModel):
    park: str
    start: _date_t
    end: _date_t
    participants: list[str] = []


@router.post("/trips")
def create_trip(body: CreateTripRequest):
    try:
        slug = trips_svc.create_trip_v2(
            park=body.park, start_date=body.start, end_date=body.end,
            participants=body.participants,
        )
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail={"error": f"trip exists: {e}"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    return {"ok": True, "slug": slug}


@router.delete("/trips/{slug}")
def delete_trip(slug: str):
    import shutil
    trip_dir = trips_svc.TRIPS_DIR / slug
    if not trip_dir.exists():
        raise HTTPException(404)
    shutil.rmtree(trip_dir)
    return {"ok": True}
