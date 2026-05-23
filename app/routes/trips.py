"""Trip mutation endpoints (new, rebuild, save-gear)."""

from fastapi import APIRouter, Body, HTTPException, Query

from app.models import (
    NewTripRequest,
    NewTripResponse,
    OkResponse,
    SaveGearRequest,
    TripsListResponse,
    TripListEntry,
)
from app.models_trip import (
    GearSection, FoodSlot, CostRow, PackingCategory, ItineraryDay, Trip,
)
from app.services import trip_store, trips as trips_svc
from app.services.trips import TripError

router = APIRouter(prefix="/api")

# (model_class, field_name, is_list_of_model)
SECTION_FIELD_MAP = {
    "gear":      (GearSection, "gear",      False),
    "food":      (FoodSlot,    "food",      True),
    "costs":     (CostRow,     "costs",     True),
    "packing":   (PackingCategory, "packing", True),
    "itinerary": (ItineraryDay, "itinerary", True),
}


def _raise(exc: TripError) -> None:
    raise HTTPException(status_code=exc.status, detail={"ok": False, "error": str(exc)})


@router.post("/new-trip", response_model=NewTripResponse)
def new_trip(body: NewTripRequest):
    try:
        slug = trips_svc.create_trip(
            park=body.park,
            start=body.start,
            end=body.end,
            participants=body.participants,
        )
    except TripError as exc:
        _raise(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(exc)})
    return NewTripResponse(trip_dir=slug)


@router.post("/rebuild", response_model=OkResponse)
def rebuild(trip: str = Query(..., min_length=1)):
    try:
        slug = trips_svc.rebuild_trip(trip)
    except TripError as exc:
        _raise(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(exc)})
    return OkResponse(message=f"rebuilt {slug}")


@router.post("/save-gear", response_model=OkResponse)
def save_gear(body: SaveGearRequest, trip: str = Query(..., min_length=1)):
    try:
        trips_svc.save_gear_table(slug=trip, rows=body.rows)
    except TripError as exc:
        _raise(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(exc)})
    return OkResponse()


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
