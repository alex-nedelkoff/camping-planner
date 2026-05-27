"""Auth dependencies."""
from __future__ import annotations

from fastapi import HTTPException, Request, Response

from app.services import identity


def require_user(request: Request, response: Response) -> identity.User:
    user = identity.current_user_refreshing(request, response)
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    return user
