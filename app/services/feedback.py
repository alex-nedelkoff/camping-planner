"""Feedback board storage — ideas and bug reports.

Unlike db.py's caches, this is source-of-truth content, so it gets its own
module. Dual-backend like trips/checklist: Postgres (prod) or SQLite (local /
tests), selected by config.STORAGE_BACKEND. Images are stored inline as bytes
(bytea / BLOB) and served by the app.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from app import config

KINDS = ("idea", "bug")
STATUSES = ("open", "planned", "done")
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB


class FeedbackError(ValueError):
    """Invalid feedback input (bad kind/status, empty body, oversized image)."""


@dataclass
class FeedbackPost:
    id: str
    author: str
    kind: str
    body: str
    status: str
    created_at: float
    has_image: bool


def _is_postgres() -> bool:
    return config.STORAGE_BACKEND == "postgres"


def create(author: str, kind: str, body: str,
           image: bytes | None = None, image_mime: str | None = None) -> str:
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        raise FeedbackError(f"invalid kind: {kind!r}")
    body = (body or "").strip()
    if not body:
        raise FeedbackError("feedback body is empty")
    if image is not None and len(image) > MAX_IMAGE_BYTES:
        raise FeedbackError("image too large")
    fid = uuid.uuid4().hex
    now = time.time()
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            conn.execute(
                "insert into feedback "
                "(id, author, kind, body, status, image, image_mime, created_at) "
                "values (%s, %s, %s, %s, 'open', %s, %s, %s)",
                (fid, author, kind, body, image, image_mime, now))
    else:
        from app.services import db
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO feedback "
                "(id, author, kind, body, status, image, image_mime, created_at) "
                "VALUES (?, ?, ?, ?, 'open', ?, ?, ?)",
                (fid, author, kind, body, image, image_mime, now))
    return fid


def _row_to_post(r) -> FeedbackPost:
    return FeedbackPost(
        id=r[0], author=r[1], kind=r[2], body=r[3], status=r[4],
        created_at=float(r[5]), has_image=bool(r[6]),
    )


_LIST_COLS = "id, author, kind, body, status, created_at, (image is not null)"


def list_all() -> list[FeedbackPost]:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            rows = conn.execute(
                f"select {_LIST_COLS} from feedback order by created_at desc").fetchall()
    else:
        from app.services import db
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT {_LIST_COLS} FROM feedback ORDER BY created_at DESC").fetchall()
    return [_row_to_post(r) for r in rows]


def get(fid: str) -> FeedbackPost | None:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            row = conn.execute(
                f"select {_LIST_COLS} from feedback where id = %s", (fid,)).fetchone()
    else:
        from app.services import db
        with db.connect() as conn:
            row = conn.execute(
                f"SELECT {_LIST_COLS} FROM feedback WHERE id = ?", (fid,)).fetchone()
    return _row_to_post(row) if row else None


def get_image(fid: str) -> tuple[bytes, str] | None:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            row = conn.execute(
                "select image, image_mime from feedback where id = %s", (fid,)).fetchone()
    else:
        from app.services import db
        with db.connect() as conn:
            row = conn.execute(
                "SELECT image, image_mime FROM feedback WHERE id = ?", (fid,)).fetchone()
    if not row or row[0] is None:
        return None
    return bytes(row[0]), (row[1] or "application/octet-stream")


def set_status(fid: str, status: str) -> None:
    status = (status or "").strip().lower()
    if status not in STATUSES:
        raise FeedbackError(f"invalid status: {status!r}")
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            conn.execute("update feedback set status = %s where id = %s", (status, fid))
    else:
        from app.services import db
        with db.connect() as conn:
            conn.execute("UPDATE feedback SET status = ? WHERE id = ?", (status, fid))


def delete(fid: str) -> None:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            conn.execute("delete from feedback where id = %s", (fid,))
    else:
        from app.services import db
        with db.connect() as conn:
            conn.execute("DELETE FROM feedback WHERE id = ?", (fid,))
