"""In-process TTL cache for regenerable data (availability/weather/route).

Replaces the SQLite cache tables. Keyed by (namespace,) + tuple key; values are
(stored_at, payload). Per-process — acceptable for short-TTL, regenerable data.
"""
from __future__ import annotations

import time

_store: dict[tuple, tuple[float, dict]] = {}


def _now() -> float:
    """Current time. Seam for tests to control expiry."""
    return time.time()


def _k(table: str, key: tuple) -> tuple:
    return (table,) + tuple(key)


def get(table: str, key: tuple, ttl_seconds: float) -> dict | None:
    k = _k(table, key)
    entry = _store.get(k)
    if entry is None:
        return None
    stored_at, payload = entry
    if (_now() - stored_at) > ttl_seconds:
        del _store[k]  # lazy-evict stale entries
        return None
    return payload


def set(table: str, key: tuple, payload: dict) -> None:
    _store[_k(table, key)] = (_now(), payload)


def drop_prefix(table: str, key_prefix: tuple) -> None:
    prefix = _k(table, key_prefix)
    n = len(prefix)
    for k in [k for k in _store if k[:n] == prefix]:
        del _store[k]


def clear() -> None:
    _store.clear()
