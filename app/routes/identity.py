"""Session-derived identity endpoint.

Free-text name picking is gone — identity comes from the magic-link session
cookie now. Use `/login` and `/logout` to change identity.
"""

from fastapi import APIRouter, Request

from app.models import WhoamiResponse
from app.services import identity

router = APIRouter(prefix="/api")


@router.get("/whoami", response_model=WhoamiResponse)
def whoami(request: Request):
    return WhoamiResponse(user=identity.current_email(request))
