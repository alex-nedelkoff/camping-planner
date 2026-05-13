"""Cross-device checklist state sync.

Replaces the per-device localStorage that build_trip.py emits. The generated
trip page still writes localStorage as an offline-first fallback; the API is
the source of truth when reachable.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from app.models import ChecklistGetResponse, ChecklistSetRequest, OkResponse
from app.services import db, identity
from app.services.trips import TRIPS_DIR

router = APIRouter(prefix="/api")


def _ensure_trip(slug: str) -> None:
    if not slug or not (TRIPS_DIR / slug).is_dir():
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "error": "trip not found"},
        )


@router.get("/checklist", response_model=ChecklistGetResponse)
def get_checklist(request: Request, trip: str = Query(..., min_length=1)):
    _ensure_trip(trip)
    user = identity.current_email(request)
    return ChecklistGetResponse(state=db.checklist_load(trip, user=user))


@router.post("/checklist", response_model=OkResponse)
def set_checklist(
    body: ChecklistSetRequest,
    request: Request,
    trip: str = Query(..., min_length=1),
):
    _ensure_trip(trip)
    user = identity.current_email(request)
    db.checklist_set(trip, body.key, body.checked, user=user)
    return OkResponse()
