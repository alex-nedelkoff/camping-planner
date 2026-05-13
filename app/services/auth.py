"""Magic-link authentication + session management.

No password. Email a single-use token; user clicks; we mint a session cookie.
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from app.services import db

MAGIC_LINK_TTL_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


class MagicLinkInvalid(Exception):
    """Token unknown, expired, or already consumed."""


def _now() -> float:
    return time.time()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def issue_magic_link(email: str, path: Path | None = None) -> str:
    token = secrets.token_hex(32)
    expires = _iso(_now() + MAGIC_LINK_TTL_SECONDS)
    with db.connect(path) as conn:
        conn.execute(
            "INSERT INTO magic_links (token, email, expires_at) "
            "VALUES (?, ?, ?)",
            (token, email.strip().lower(), expires),
        )
    return token


def consume_magic_link(token: str, path: Path | None = None) -> str:
    """Return a new session id. Raises MagicLinkInvalid on any failure."""
    now = _now()
    now_iso = _iso(now)
    with db.connect(path) as conn:
        cur = conn.execute(
            "UPDATE magic_links SET consumed_at = ? "
            "WHERE token = ? AND consumed_at IS NULL AND expires_at > ?",
            (now_iso, token, now_iso),
        )
        if cur.rowcount != 1:
            raise MagicLinkInvalid("unknown, expired, or already consumed")
        row = conn.execute(
            "SELECT email FROM magic_links WHERE token = ?", (token,),
        ).fetchone()
        user_id = upsert_user(row["email"], conn=conn)
        session_id = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, user_id, now_iso,
             _iso(now + SESSION_TTL_SECONDS)),
        )
        return session_id


def upsert_user(email: str, *, conn=None, path: Path | None = None) -> int:
    email = email.strip().lower()
    own_conn = conn is None
    if own_conn:
        conn = db.connect(path)
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,),
        ).fetchone()
        if row:
            return row["id"]
        conn.execute(
            "INSERT INTO users (email, display_name, created_at) "
            "VALUES (?, ?, ?)",
            (email, email.split("@")[0], _iso(_now())),
        )
        return conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,),
        ).fetchone()["id"]
    finally:
        if own_conn:
            conn.close()


def user_for_session(session_id: str, path: Path | None = None) -> dict | None:
    if not session_id:
        return None
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT u.id, u.email, u.display_name, s.expires_at "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        if _iso(_now()) > row["expires_at"]:
            return None
        return {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
        }


def delete_session(session_id: str, path: Path | None = None) -> None:
    with db.connect(path) as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def add_trip_member(
    trip_slug: str,
    email: str,
    role: str = "editor",
    path: Path | None = None,
) -> None:
    if role not in ("owner", "editor", "viewer"):
        raise ValueError(f"bad role: {role}")
    with db.connect(path) as conn:
        user_id = upsert_user(email, conn=conn)
        conn.execute(
            "INSERT OR REPLACE INTO trip_members "
            "(trip_slug, user_id, role, added_at) VALUES (?, ?, ?, ?)",
            (trip_slug, user_id, role, _iso(_now())),
        )


def is_trip_member(
    trip_slug: str,
    email: str,
    path: Path | None = None,
) -> bool:
    with db.connect(path) as conn:
        return conn.execute(
            "SELECT 1 FROM trip_members tm JOIN users u ON u.id = tm.user_id "
            "WHERE tm.trip_slug = ? AND u.email = ?",
            (trip_slug, email.strip().lower()),
        ).fetchone() is not None
