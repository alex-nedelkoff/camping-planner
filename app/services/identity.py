"""Identity from session cookie.

The session id resolves to a `users` row; that's the active user. Empty
cookie / unknown session → anonymous (empty-string email = shared bucket).
"""

from __future__ import annotations

from fastapi import Request

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
