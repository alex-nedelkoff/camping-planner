"""Identity from session cookie.

The session id resolves to a `users` row; that's the active user. Empty
cookie / unknown session → anonymous (empty-string email = shared bucket).
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.services import auth

SESSION_COOKIE = "cp_session"


def current_user(request: Request) -> dict | None:
    """Return the active user dict ({id, email, display_name}) or None."""
    sid = request.cookies.get(SESSION_COOKIE, "")
    return auth.user_for_session(sid)


def current_email(request: Request) -> str:
    """Return the active user's email, or '' for anonymous."""
    user = current_user(request)
    return user["email"] if user else ""


def require_trip_member(request: Request, slug: str) -> dict:
    """Return the active user dict, or raise 401 / 403.

    Shared gate for any route that mutates trip-scoped collab data
    (food, gear, future collab tables). Returns the user dict so handlers
    can stamp updated_by with the user id.
    """
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    if not auth.is_trip_member(slug, user["email"]):
        raise HTTPException(status_code=403, detail="not a member of this trip")
    return user
