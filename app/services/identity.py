"""Identity via a shared site password + free-text username.

After someone enters the correct shared password and a username, we set a
single HMAC-signed cookie carrying that username. The signature prevents a
client from forging a different username; it is not per-user authentication
(everyone shares one password), which is acceptable for a trusted friends
group. The username is the identity used for trip ownership and per-person
checklists. With AUTH_ENABLED off (local/tests) we return a synthetic local
user so the app runs without login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Request, Response

from app import config

SESSION_COOKIE = "cp_user"
_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


@dataclass
class User:
    id: str
    email: str


def _local_user() -> User:
    return User(id="local", email="local")


def _secret() -> bytes:
    return (config.SESSION_SECRET or "dev-only-insecure-session-secret").encode()


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(username: str) -> str:
    """Return `<b64(username)>.<b64(hmac)>` for use as the session cookie value."""
    raw = username.encode()
    sig = hmac.new(_secret(), raw, hashlib.sha256).digest()
    return f"{_b64e(raw)}.{_b64e(sig)}"


def unsign(token: str) -> str | None:
    """Recover the username from a signed cookie value, or None if tampered."""
    try:
        name_b64, sig_b64 = token.split(".", 1)
        raw = _b64d(name_b64)
        expected = hmac.new(_secret(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(sig_b64)):
            return None
        return raw.decode()
    except Exception:
        return None


def current_user(request: Request) -> User | None:
    if not config.AUTH_ENABLED:
        return _local_user()
    name = unsign(request.cookies.get(SESSION_COOKIE, ""))
    if not name:
        return None
    return User(id=name, email=name)


def set_session(response: Response, username: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, sign(username), max_age=_MAX_AGE,
        httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_user_refreshing(request: Request, response: Response) -> "User | None":
    """Kept for the require_user dependency. The signed cookie carries no
    short-lived token, so there is nothing to refresh — just resolve the user."""
    return current_user(request)
