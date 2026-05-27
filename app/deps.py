"""Auth dependencies."""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.services import identity


def require_user(request: Request) -> identity.User:
    user = identity.current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    return user
