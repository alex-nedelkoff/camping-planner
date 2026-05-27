"""Cookie-based identity for the ≤8-person trusted group.

No password, no accounts. The user picks a name once; the browser holds it
in a `cp_user` cookie. Server reads the cookie to scope per-user state.
An empty/absent cookie means "shared" (matches Phase 2 behaviour).
"""

from __future__ import annotations

import re

from fastapi import Request

COOKIE_NAME = "cp_user"
MAX_LEN = 40
# One year — friends rarely re-pick. They can switch via the UI.
COOKIE_MAX_AGE = 365 * 24 * 60 * 60

_NAME_RE = re.compile(r"^[A-Za-z0-9 _'\-.]{1,40}$")


def normalise(name: str | None) -> str:
    """Strip + length-cap. Returns '' for invalid/missing input (= shared)."""
    if not name:
        return ""
    cleaned = name.strip()
    if not cleaned or not _NAME_RE.match(cleaned):
        return ""
    return cleaned[:MAX_LEN]


def current_user(request: Request) -> str:
    """Read the active user from the request cookie. '' = shared / unidentified."""
    return normalise(request.cookies.get(COOKIE_NAME))
