"""Trip edit authorization (Phase 2)."""
from __future__ import annotations

from app.models_trip import Trip
from app.services.identity import User

# /meta fields only the owner may change. participants + access_point stay open.
CORE_META_FIELDS = {"park", "dates", "nights", "mode", "name", "access_point"}


def can_edit_core(trip: Trip, user: User) -> bool:
    """Owner, or a communal (ownerless/migrated) trip -> True."""
    return trip.owner_id is None or trip.owner_id == user.id


def meta_touches_core(body: dict) -> bool:
    return bool(set(body) & CORE_META_FIELDS)
