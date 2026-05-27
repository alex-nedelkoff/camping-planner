"""Identity backed by Supabase Auth (Phase 2).

current_user() verifies the access-token JWT from the cp_at cookie. With
AUTH_ENABLED off (local/tests) it returns a synthetic local user so the app
runs without login.
"""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Request, Response

from app import config

ACCESS_COOKIE = "cp_at"
REFRESH_COOKIE = "cp_rt"


@dataclass
class User:
    id: str
    email: str


def _local_user() -> User:
    return User(id="local", email="local")


def _decode(token: str) -> dict | None:
    if not token or not config.SUPABASE_JWT_SECRET:
        return None
    try:
        return jwt.decode(
            token, config.SUPABASE_JWT_SECRET, algorithms=["HS256"],
            audience="authenticated", options={"verify_aud": True},
        )
    except jwt.PyJWTError:
        return None


def current_user(request: Request) -> User | None:
    if not config.AUTH_ENABLED:
        return _local_user()
    claims = _decode(request.cookies.get(ACCESS_COOKIE, ""))
    if not claims or not claims.get("sub"):
        return None
    return User(id=claims["sub"], email=claims.get("email", ""))


def set_session(response: Response, access_token: str, refresh_token: str) -> None:
    common = dict(httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/")
    response.set_cookie(ACCESS_COOKIE, access_token, max_age=3600, **common)
    response.set_cookie(REFRESH_COOKIE, refresh_token, max_age=60 * 60 * 24 * 30, **common)


def clear_session(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
