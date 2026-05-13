"""Server-Sent Events: one stream per trip, fed by broadcast.default_bus.

We also track presence here: every subscriber gets added to a set keyed by
(trip_slug, email); add/remove triggers a `presence` event broadcast to all
subscribers of that trip.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.services import auth, broadcast
from app.services.identity import current_user

router = APIRouter()

_presence: dict[str, set[str]] = {}  # trip_slug -> set of emails


def _add_presence(slug: str, email: str) -> None:
    _presence.setdefault(slug, set()).add(email)


def _remove_presence(slug: str, email: str) -> None:
    s = _presence.get(slug)
    if s:
        s.discard(email)
        if not s:
            _presence.pop(slug, None)


async def _broadcast_presence(slug: str) -> None:
    await broadcast.default_bus.publish(
        slug,
        {
            "type": "presence",
            "users": sorted(_presence.get(slug, ())),
        },
    )


@router.get("/trips/{slug}/events")
async def sse(slug: str, request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "not signed in")
    if not auth.is_trip_member(slug, user["email"]):
        raise HTTPException(403, "not a member of this trip")

    queue = broadcast.default_bus.subscribe(slug)
    _add_presence(slug, user["email"])
    await _broadcast_presence(slug)

    async def stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue
                yield {"data": json.dumps(event)}
        finally:
            broadcast.default_bus.unsubscribe(slug, queue)
            _remove_presence(slug, user["email"])
            await _broadcast_presence(slug)

    return EventSourceResponse(stream())
