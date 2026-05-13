#!/usr/bin/env python3
"""Local-dev shortcut: mint a session + add user as trip member, no email round-trip.

Usage:
    python3 scripts/dev_grant.py you@example.com                # all trips, owner
    python3 scripts/dev_grant.py you@example.com killarney-2026-05  # one trip
    python3 scripts/dev_grant.py you@example.com all editor    # all trips, editor

Prints a `cp_session=...` cookie value. Paste it into DevTools →
Application → Cookies → http://localhost:8000 (Name `cp_session`,
Value the printed token, Path `/`, HttpOnly checked).
"""

from __future__ import annotations

import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import TRIPS_DIR  # noqa: E402
from app.services import auth, db  # noqa: E402


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        raise SystemExit(2)

    email = argv[0].strip().lower()
    slug_arg = argv[1] if len(argv) > 1 else "all"
    role = argv[2] if len(argv) > 2 else "owner"
    if role not in ("owner", "editor", "viewer"):
        raise SystemExit(f"bad role: {role}")

    db.init_schema()
    user_id = auth.upsert_user(email)

    if slug_arg == "all":
        slugs = sorted(d.name for d in TRIPS_DIR.glob("*/") if d.is_dir())
    else:
        slugs = [slug_arg]

    for slug in slugs:
        auth.add_trip_member(slug, email, role=role)
        print(f"  granted {role} on {slug}")

    sid = secrets.token_urlsafe(32)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (
                sid,
                user_id,
                datetime.now(timezone.utc).isoformat(),
                datetime.fromtimestamp(time.time() + auth.SESSION_TTL_SECONDS,
                                       tz=timezone.utc).isoformat(),
            ),
        )

    print()
    print(f"user_id      : {user_id}")
    print(f"email        : {email}")
    print(f"cp_session   : {sid}")
    print()
    print("Set the cookie in DevTools → Application → Cookies → localhost:8000")
    print("  Name:  cp_session")
    print(f"  Value: {sid}")
    print("  Path:  /")
    print()
    print("Or via curl: cookie header → -b 'cp_session=" + sid + "'")


if __name__ == "__main__":
    main()
