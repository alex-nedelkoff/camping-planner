"""Trip mutation endpoints (new, rebuild, save-gear, snapshot)."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import TRIPS_DIR
from app.models import (
    NewTripRequest,
    NewTripResponse,
    OkResponse,
    SaveGearRequest,
)
from app.services import broadcast, trips as trips_svc
from app.services import snapshot as snapshot_svc
from app.services.identity import require_trip_member
from app.services.trips import TripError

router = APIRouter(prefix="/api")


class SnapshotReq(BaseModel):
    run_build_trip: bool = True


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


@router.post("/trips/{slug}/snapshot")
async def snapshot_to_disk(slug: str, body: SnapshotReq, request: Request):
    user = require_trip_member(request, slug)
    trip_dir = TRIPS_DIR / slug
    paths = snapshot_svc.write_snapshot(
        slug, trip_dir, run_build_trip=body.run_build_trip,
    )
    await broadcast.default_bus.publish(slug, {
        "type": "snapshot.saved",
        "by": user["email"],
        "at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "paths": paths}
