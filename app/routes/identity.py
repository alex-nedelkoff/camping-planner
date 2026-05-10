"""Cookie-based identity endpoints (no password)."""

from fastapi import APIRouter, HTTPException, Request, Response

from app.models import OkResponse, WhoamiResponse, WhoamiSetRequest
from app.services import identity

router = APIRouter(prefix="/api")


@router.get("/whoami", response_model=WhoamiResponse)
def whoami(request: Request):
    return WhoamiResponse(user=identity.current_user(request))


@router.post("/whoami", response_model=WhoamiResponse)
def set_whoami(body: WhoamiSetRequest, response: Response):
    name = identity.normalise(body.user)
    if not name:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "error": "invalid name"},
        )
    response.set_cookie(
        key=identity.COOKIE_NAME,
        value=name,
        max_age=identity.COOKIE_MAX_AGE,
        httponly=False,  # the JS reads it for the trip-page header
        samesite="lax",
    )
    return WhoamiResponse(user=name)


@router.delete("/whoami", response_model=OkResponse)
def clear_whoami(response: Response):
    response.delete_cookie(identity.COOKIE_NAME)
    return OkResponse()
