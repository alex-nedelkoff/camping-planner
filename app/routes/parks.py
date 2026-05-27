"""Ontario Parks availability endpoint."""

from datetime import date

from fastapi import Depends, APIRouter, HTTPException, Query
from app.deps import require_user

from app.models import AvailabilityResponse, CampgroundAvailability
from app.services import availability as availability_svc

router = APIRouter(prefix="/api")


@router.get("/availability", response_model=AvailabilityResponse)
def availability(
    park: str = Query(..., min_length=1),
    start: date = Query(...),
    end: date = Query(...),
    _user=Depends(require_user),
):
    try:
        result = availability_svc.check(park, start.isoformat(), end.isoformat())
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(exc)})
    return AvailabilityResponse(
        park_name=result.get("park_name"),
        total_available=result.get("total_available", 0),
        campgrounds={
            name: CampgroundAvailability(**info)
            for name, info in result.get("campgrounds", {}).items()
        },
        cached=bool(result.get("cached", False)),
    )
