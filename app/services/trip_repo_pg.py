"""Postgres-backed trip repository (STORAGE_BACKEND=postgres)."""
from __future__ import annotations

import json
from typing import Any, Optional

from app.models_trip import Trip
from app.services import pg
from app.services.trip_repo import _validate


class PostgresTripRepo:
    def get(self, slug: str) -> Optional[Trip]:
        with pg.connection() as conn:
            row = conn.execute("select data from trips where slug = %s", (slug,)).fetchone()
        if row is None:
            return None
        data = row[0]
        return _validate(data if isinstance(data, dict) else json.loads(data))

    def save(self, slug: str, trip: Trip) -> None:
        payload = json.dumps(trip.model_dump(mode="json"))
        with pg.connection() as conn:
            conn.execute(
                "insert into trips (slug, data) values (%s, %s::jsonb) "
                "on conflict (slug) do update set data = excluded.data, updated_at = now()",
                (slug, payload),
            )

    def exists(self, slug: str) -> bool:
        with pg.connection() as conn:
            row = conn.execute("select 1 from trips where slug = %s", (slug,)).fetchone()
        return row is not None

    def list_slugs(self) -> list[str]:
        with pg.connection() as conn:
            rows = conn.execute("select slug from trips order by slug").fetchall()
        return [r[0] for r in rows]

    def delete(self, slug: str) -> None:
        with pg.connection() as conn:
            conn.execute("delete from trips where slug = %s", (slug,))

    def get_routes(self, slug: str) -> Any:
        with pg.connection() as conn:
            row = conn.execute("select manual_routes from trips where slug = %s", (slug,)).fetchone()
        if row is None or row[0] is None:
            return None
        return row[0] if not isinstance(row[0], str) else json.loads(row[0])

    def set_routes(self, slug: str, data: Any) -> None:
        with pg.connection() as conn:
            conn.execute("update trips set manual_routes = %s::jsonb, updated_at = now() "
                         "where slug = %s", (json.dumps(data), slug))
