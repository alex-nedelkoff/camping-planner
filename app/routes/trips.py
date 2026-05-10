"""Trip endpoints (new, save-gear, fetch rendered payload)."""

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    NewTripRequest,
    NewTripResponse,
    OkResponse,
    SaveGearRequest,
    TripListItem,
    TripListResponse,
    TripPayloadResponse,
)
from app.services import trips as trips_svc
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


@router.post("/save-gear", response_model=OkResponse)
def save_gear(body: SaveGearRequest, trip: str = Query(..., min_length=1)):
    try:
        trips_svc.save_gear_table(slug=trip, rows=body.rows)
    except TripError as exc:
        _raise(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@router.get("/trips", response_model=TripListResponse)
def list_trips():
    all_trips = trips_svc.scan_trips()
    upcoming, past, broken = trips_svc.split_trips(all_trips)
    items: list[TripListItem] = []
    for trip in upcoming:
        meta = trips_svc.trip_card_meta(trip)
        items.append(TripListItem(bucket="upcoming", **{
            k: meta.get(k) for k in (
                "name", "park_name", "start_date", "end_date",
                "participant_count", "days_label",
            )
        }))
    for trip in past:
        meta = trips_svc.trip_card_meta(trip)
        items.append(TripListItem(bucket="past", **{
            k: meta.get(k) for k in (
                "name", "park_name", "start_date", "end_date",
                "participant_count", "days_label",
            )
        }))
    for trip in broken:
        items.append(TripListItem(
            bucket="broken", name=trip.get("name", ""), error=trip.get("error", ""),
        ))
    return TripListResponse(trips=items)


@router.get("/trip/{slug}", response_model=TripPayloadResponse)
def get_trip(slug: str):
    try:
        payload = trips_svc.load_trip_payload(slug)
    except TripError as exc:
        _raise(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(exc)})
    return TripPayloadResponse(**payload)
