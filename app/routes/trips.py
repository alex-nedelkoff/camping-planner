"""Trip mutation endpoints (new, rebuild, save-gear)."""

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    NewTripRequest,
    NewTripResponse,
    OkResponse,
    SaveGearRequest,
    TripsListResponse,
    TripListEntry,
)
from app.services import trip_store, trips as trips_svc
from app.services.trips import TripError

router = APIRouter(prefix="/api")


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
