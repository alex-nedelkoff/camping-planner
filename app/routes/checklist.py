"""Cross-device checklist state sync.

Replaces the per-device localStorage that build_trip.py emits. The generated
trip page still writes localStorage as an offline-first fallback; the API is
the source of truth when reachable.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models import ChecklistGetResponse, ChecklistSetRequest, OkResponse
from app.services import db, identity
from app.deps import require_user

router = APIRouter(prefix="/api")


def _ensure_trip(slug: str) -> None:
    from app.services import trip_repo
    if not slug or not trip_repo.get_repo().exists(slug):
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "error": "trip not found"},
        )


@router.get("/checklist", response_model=ChecklistGetResponse)
def get_checklist(trip: str = Query(..., min_length=1),
                  user: identity.User = Depends(require_user)):
    _ensure_trip(trip)
    return ChecklistGetResponse(state=db.checklist_load(trip, user=user.id))


@router.post("/checklist", response_model=OkResponse)
def set_checklist(
    body: ChecklistSetRequest,
    trip: str = Query(..., min_length=1),
    user: identity.User = Depends(require_user),
):
    _ensure_trip(trip)
    db.checklist_set(trip, body.key, body.checked, user=user.id)
    return OkResponse()
