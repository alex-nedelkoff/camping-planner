"""gear_items CRUD. Conflicts detected via expected_updated_at."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.services import db


class Conflict(Exception):
    def __init__(self, current: dict):
        super().__init__("gear row was modified concurrently")
        self.current = current


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def insert(
    *,
    trip_slug: str,
    category: str,
    item: str,
    quantity: str,
    assigned_to: str | None,
    notes: str | None,
    sort_order: float,
    user_id: int,
    path: Path | None = None,
) -> dict:
    now = _iso_now()
    with db.connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO gear_items "
            "(trip_slug, category, item, quantity, assigned_to, "
            " notes, sort_order, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trip_slug, category, item, quantity, assigned_to,
             notes, sort_order, now, user_id),
        )
        rid = cur.lastrowid
        return _row_to_dict(conn.execute(
            "SELECT * FROM gear_items WHERE id = ?", (rid,)
        ).fetchone())


def list_for_trip(trip_slug: str, path: Path | None = None) -> list[dict]:
    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM gear_items WHERE trip_slug = ? "
            "ORDER BY category, sort_order",
            (trip_slug,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update(
    row_id: int,
    *,
    expected_updated_at: str,
    user_id: int,
    path: Path | None = None,
    **fields,
) -> dict:
    allowed = {"category", "item", "quantity", "assigned_to",
               "notes", "sort_order"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown fields: {bad}")
    now = _iso_now()
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM gear_items WHERE id = ?", (row_id,),
        ).fetchone()
        if row is None:
            raise KeyError(row_id)
        if row["updated_at"] != expected_updated_at:
            raise Conflict(current=_row_to_dict(row))
        sets = ", ".join(f"{k} = ?" for k in fields)
        sets += ", updated_at = ?, updated_by = ?"
        values = list(fields.values()) + [now, user_id, row_id]
        conn.execute(
            f"UPDATE gear_items SET {sets} WHERE id = ?", values,
        )
        return _row_to_dict(conn.execute(
            "SELECT * FROM gear_items WHERE id = ?", (row_id,)
        ).fetchone())


def delete(row_id: int, path: Path | None = None) -> None:
    with db.connect(path) as conn:
        conn.execute("DELETE FROM gear_items WHERE id = ?", (row_id,))
