"""In-process pub/sub for SSE.

Single-process only. If scaling to multiple machines is ever needed,
swap in a Redis pub/sub client behind the same interface.
"""

from __future__ import annotations

import asyncio
from typing import Any


class Bus:
    def __init__(self, max_queue: int = 64):
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._max_queue = max_queue

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subs.setdefault(channel, set()).add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(channel)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(channel, None)

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(channel, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # drop for this subscriber; DB is canonical
                pass

    def presence(self, channel: str) -> int:
        return len(self._subs.get(channel, ()))


# Module-level default instance
default_bus = Bus()
