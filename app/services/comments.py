"""Per-trip comments storage.

Source-of-truth content, dual-backend like feedback/trips: Postgres (prod) or
SQLite (local/tests), selected by config.STORAGE_BACKEND.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from app import config

MAX_COMMENT_LEN = 2000


class CommentError(ValueError):
    """Invalid comment input (empty or too long)."""


@dataclass
class Comment:
    id: str
    trip_slug: str
    author: str
    body: str
    created_at: float


def _is_postgres() -> bool:
    return config.STORAGE_BACKEND == "postgres"


def create(trip_slug: str, author: str, body: str) -> Comment:
    body = (body or "").strip()
    if not body:
        raise CommentError("comment is empty")
    if len(body) > MAX_COMMENT_LEN:
        raise CommentError("comment too long")
    c = Comment(uuid.uuid4().hex, trip_slug, author, body, time.time())
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            conn.execute(
                "insert into trip_comments (id, trip_slug, author, body, created_at) "
                "values (%s, %s, %s, %s, %s)",
                (c.id, c.trip_slug, c.author, c.body, c.created_at))
    else:
        from app.services import db
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO trip_comments (id, trip_slug, author, body, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (c.id, c.trip_slug, c.author, c.body, c.created_at))
    return c


def _row_to_comment(r) -> Comment:
    return Comment(id=r[0], trip_slug=r[1], author=r[2], body=r[3], created_at=float(r[4]))


_COLS = "id, trip_slug, author, body, created_at"


def list_for(trip_slug: str) -> list[Comment]:
    """Comments for a trip, oldest first (chat order)."""
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            rows = conn.execute(
                f"select {_COLS} from trip_comments where trip_slug = %s "
                "order by created_at asc", (trip_slug,)).fetchall()
    else:
        from app.services import db
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM trip_comments WHERE trip_slug = ? "
                "ORDER BY created_at ASC", (trip_slug,)).fetchall()
    return [_row_to_comment(r) for r in rows]


def get(comment_id: str) -> Comment | None:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            row = conn.execute(
                f"select {_COLS} from trip_comments where id = %s", (comment_id,)).fetchone()
    else:
        from app.services import db
        with db.connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM trip_comments WHERE id = ?", (comment_id,)).fetchone()
    return _row_to_comment(row) if row else None


def delete(comment_id: str) -> None:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            conn.execute("delete from trip_comments where id = %s", (comment_id,))
    else:
        from app.services import db
        with db.connect() as conn:
            conn.execute("DELETE FROM trip_comments WHERE id = ?", (comment_id,))
