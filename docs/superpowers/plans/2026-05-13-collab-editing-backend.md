# Collaborative Editing — Backend & Sync (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the server side of multi-user collaborative editing — magic-link auth, structured food/gear rows, SSE broadcast, snapshot-to-markdown — all verified by pytest with the Camis API mocked. No UI; no deploy yet. After this plan ships, the backend is provably working and the next plan (frontend + deploy) builds the UI on top.

**Architecture:** FastAPI app extended with new tables in the existing SQLite layer. Magic-link email auth + signed session cookies replace the `cp_user` cookie. Food and gear become structured rows; edits go through REST POST with `expected_updated_at` conflict detection. An in-process asyncio.Queue fan-out powers Server-Sent Events for ~1s sync. A snapshot service renders DB rows back to deterministic markdown and invokes `build_trip.py`.

**Tech Stack:** FastAPI, SQLite (existing), Jinja2 (existing), `httpx` (already in deps), `secrets` stdlib for tokens, Resend HTTP API for email transport (`httpx.AsyncClient`), pytest + TestClient.

**Spec:** `docs/superpowers/specs/2026-05-13-collaborative-editing-design.md`

---

## File Structure

**Create:**
- `app/services/auth.py` — magic-link tokens, sessions, member checks
- `app/services/mailer.py` — Resend HTTP transport with mockable interface
- `app/services/broadcast.py` — in-process asyncio pub/sub for SSE
- `app/services/snapshot.py` — DB → deterministic markdown rendering + build_trip.py invocation
- `app/services/food_repo.py` — food_items CRUD with conflict detection
- `app/services/gear_repo.py` — gear_items CRUD with conflict detection
- `app/services/seed.py` — idempotent markdown → DB seeding (also runnable as a script)
- `app/routes/auth.py` — `/login`, `/login/verify`, `/logout`
- `app/routes/sse.py` — `/trips/<slug>/events`
- `app/routes/food.py` — `/api/trips/<slug>/food` CRUD
- `app/routes/gear.py` — `/api/trips/<slug>/gear` CRUD
- `app/routes/health.py` — `/healthz`
- `scripts/pull-snapshot.sh` — `fly ssh sftp` helper
- `scripts/seed_from_markdown.py` — thin CLI wrapper around `app.services.seed`
- `tests/test_auth.py`
- `tests/test_food_repo.py`
- `tests/test_gear_repo.py`
- `tests/test_food_routes.py`
- `tests/test_gear_routes.py`
- `tests/test_broadcast_sse.py`
- `tests/test_snapshot.py`
- `tests/test_seed.py`

**Modify:**
- `app/services/db.py` — add new tables to schema init
- `app/services/identity.py` — replace cp_user logic with session-cookie lookup
- `app/config.py` — `DATA_DIR` env override for `TRIPS_DIR` and `DATABASE_PATH`
- `app/main.py` — include new routers
- `app/routes/trips.py` — add snapshot endpoint

**Out of scope for this plan:** templates, CSS, JS, Dockerfile, fly.toml. All in Plan 2.

---

## Phase A — Schema & config

### Task 1: Add new tables to the SQLite schema

**Files:**
- Modify: `app/services/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db.py`:

```python
def test_init_schema_creates_collab_tables(tmp_path):
    p = tmp_path / "c.sqlite3"
    db.init_schema(p)
    with db.connect(p) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    expected = {
        "users", "magic_links", "sessions", "trip_members",
        "food_items", "gear_items", "section_state",
    }
    assert expected <= names


def test_init_schema_collab_indexes(tmp_path):
    p = tmp_path / "c.sqlite3"
    db.init_schema(p)
    with db.connect(p) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
    assert "idx_food_trip" in names
    assert "idx_gear_trip" in names
```

- [ ] **Step 2: Run the test, expect FAIL**

```
python3 -m pytest tests/test_db.py::test_init_schema_creates_collab_tables -v
```
Expected: FAIL — tables not present.

- [ ] **Step 3: Add the DDL to `app/services/db.py`**

Add a new constant after `_CHECKLIST_V1_DDL`:

```python
_COLLAB_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    display_name  TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS magic_links (
    token        TEXT PRIMARY KEY,
    email        TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    consumed_at  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trip_members (
    trip_slug  TEXT NOT NULL,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    role       TEXT NOT NULL CHECK (role IN ('owner','editor','viewer')),
    added_at   TEXT NOT NULL,
    PRIMARY KEY (trip_slug, user_id)
);

CREATE TABLE IF NOT EXISTS food_items (
    id           INTEGER PRIMARY KEY,
    trip_slug    TEXT NOT NULL,
    day_index    INTEGER NOT NULL,
    meal         TEXT NOT NULL,
    item         TEXT NOT NULL,
    assigned_to  TEXT,
    notes        TEXT,
    sort_order   REAL NOT NULL,
    updated_at   TEXT NOT NULL,
    updated_by   INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_food_trip
    ON food_items(trip_slug, day_index, meal, sort_order);

CREATE TABLE IF NOT EXISTS gear_items (
    id           INTEGER PRIMARY KEY,
    trip_slug    TEXT NOT NULL,
    category     TEXT NOT NULL,
    item         TEXT NOT NULL,
    quantity     TEXT,
    assigned_to  TEXT,
    notes        TEXT,
    sort_order   REAL NOT NULL,
    updated_at   TEXT NOT NULL,
    updated_by   INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_gear_trip
    ON gear_items(trip_slug, category, sort_order);

CREATE TABLE IF NOT EXISTS section_state (
    trip_slug             TEXT NOT NULL,
    section               TEXT NOT NULL,
    seeded_from_md_at     TEXT,
    last_snapshotted_at   TEXT,
    PRIMARY KEY (trip_slug, section)
);
"""
```

Extend `init_schema`:

```python
def init_schema(path: Path | None = None) -> None:
    """Create / migrate tables. Idempotent — safe to call on every boot."""
    with connect(path) as conn:
        conn.executescript(_BASE_SCHEMA)
        conn.executescript(_COLLAB_SCHEMA)
        _ensure_checklist_state(conn)
```

- [ ] **Step 4: Run the tests, expect PASS**

```
python3 -m pytest tests/test_db.py -v
```
Expected: all green, including the two new tests.

- [ ] **Step 5: Commit**

```bash
git add app/services/db.py tests/test_db.py
git commit -m "feat(db): add auth + structured content + section_state tables"
```

---

### Task 2: `DATA_DIR` env override in config

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Config env overrides."""

import importlib

import pytest


def test_data_dir_env_overrides_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.config as cfg
    importlib.reload(cfg)
    assert cfg.TRIPS_DIR == tmp_path / "trips"
    assert cfg.DATABASE_PATH == tmp_path / "camping.sqlite3"


def test_no_data_dir_falls_back_to_repo(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    import app.config as cfg
    importlib.reload(cfg)
    assert cfg.TRIPS_DIR.name == "trips"
    assert cfg.TRIPS_DIR.parent.name == "camping-planner" or \
           cfg.TRIPS_DIR.parent.name.startswith("collab-editing")  # worktree
```

- [ ] **Step 2: Run the test, expect FAIL**

```
python3 -m pytest tests/test_config.py -v
```
Expected: FAIL — `DATA_DIR` env isn't read.

- [ ] **Step 3: Update `app/config.py`**

```python
"""Centralised paths and settings for the FastAPI app."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_DATA_DIR_ENV = os.environ.get("DATA_DIR")
DATA_DIR = Path(_DATA_DIR_ENV) if _DATA_DIR_ENV else REPO_ROOT

TRIPS_DIR = DATA_DIR / "trips"
TEMPLATE_DIR = REPO_ROOT / "templates" / "trip-template"
PARKS_JSON = REPO_ROOT / "parks.json"
DATABASE_PATH = DATA_DIR / "camping.sqlite3"

APP_DIR = Path(__file__).resolve().parent
JINJA_TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

AVAILABILITY_CACHE_TTL = 15 * 60
WEATHER_CACHE_TTL = 60 * 60
```

- [ ] **Step 4: Run all tests, expect PASS**

```
python3 -m pytest tests/ -q
```
Expected: 140 + new tests all pass.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): DATA_DIR env override for TRIPS_DIR + DATABASE_PATH"
```

---

## Phase B — Authentication

### Task 3: Magic-link + sessions service

**Files:**
- Create: `app/services/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth.py`:

```python
"""Magic-link issue/verify + session lifecycle."""

import time

import pytest

from app.services import auth, db


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "auth.sqlite3"
    db.init_schema(p)
    return p


def test_issue_magic_link_creates_unconsumed_row(dbpath):
    token = auth.issue_magic_link("alex@example.com", path=dbpath)
    assert len(token) >= 32
    with db.connect(dbpath) as conn:
        row = conn.execute(
            "SELECT email, consumed_at FROM magic_links WHERE token = ?",
            (token,),
        ).fetchone()
    assert row["email"] == "alex@example.com"
    assert row["consumed_at"] is None


def test_consume_magic_link_creates_user_and_session(dbpath):
    token = auth.issue_magic_link("alex@example.com", path=dbpath)
    session_id = auth.consume_magic_link(token, path=dbpath)
    assert session_id
    user = auth.user_for_session(session_id, path=dbpath)
    assert user["email"] == "alex@example.com"


def test_consume_magic_link_marks_consumed(dbpath):
    token = auth.issue_magic_link("alex@example.com", path=dbpath)
    auth.consume_magic_link(token, path=dbpath)
    with pytest.raises(auth.MagicLinkInvalid):
        auth.consume_magic_link(token, path=dbpath)


def test_expired_magic_link_rejected(dbpath, monkeypatch):
    token = auth.issue_magic_link("alex@example.com", path=dbpath)
    # Fast-forward past the 15-min expiry
    real = time.time
    monkeypatch.setattr(auth, "_now", lambda: real() + 16 * 60)
    with pytest.raises(auth.MagicLinkInvalid):
        auth.consume_magic_link(token, path=dbpath)


def test_user_for_unknown_session_returns_none(dbpath):
    assert auth.user_for_session("nope", path=dbpath) is None


def test_is_trip_member_false_for_non_member(dbpath):
    auth.upsert_user("alex@example.com", path=dbpath)
    assert not auth.is_trip_member(
        "killarney-2026-05", "alex@example.com", path=dbpath,
    )


def test_add_trip_member_then_check(dbpath):
    auth.upsert_user("alex@example.com", path=dbpath)
    auth.add_trip_member(
        "killarney-2026-05", "alex@example.com", role="owner", path=dbpath,
    )
    assert auth.is_trip_member(
        "killarney-2026-05", "alex@example.com", path=dbpath,
    )
```

- [ ] **Step 2: Run the tests, expect FAIL**

```
python3 -m pytest tests/test_auth.py -v
```
Expected: collection error — `app.services.auth` doesn't exist.

- [ ] **Step 3: Implement `app/services/auth.py`**

```python
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
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT email, expires_at, consumed_at FROM magic_links "
            "WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None or row["consumed_at"] is not None:
            raise MagicLinkInvalid("unknown or already consumed")
        if _iso(_now()) > row["expires_at"]:
            raise MagicLinkInvalid("expired")
        conn.execute(
            "UPDATE magic_links SET consumed_at = ? WHERE token = ?",
            (_iso(_now()), token),
        )
        user_id = upsert_user(row["email"], conn=conn)
        session_id = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, user_id, _iso(_now()),
             _iso(_now() + SESSION_TTL_SECONDS)),
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
```

- [ ] **Step 4: Run the tests, expect PASS**

```
python3 -m pytest tests/test_auth.py -v
```
Expected: 7 passing.

- [ ] **Step 5: Commit**

```bash
git add app/services/auth.py tests/test_auth.py
git commit -m "feat(auth): magic-link tokens + sessions + trip membership"
```

---

### Task 4: Mailer service with mockable transport

**Files:**
- Create: `app/services/mailer.py`
- Test: `tests/test_mailer.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""Mailer: assemble + send magic-link emails. Transport is mocked."""

import pytest

from app.services import mailer


class FakeTransport:
    def __init__(self):
        self.sent = []

    async def send(self, *, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})


@pytest.mark.asyncio
async def test_send_magic_link_calls_transport_with_link():
    fake = FakeTransport()
    await mailer.send_magic_link(
        "alex@example.com",
        "https://example.test/login/verify?token=abc",
        transport=fake,
    )
    assert len(fake.sent) == 1
    msg = fake.sent[0]
    assert msg["to"] == "alex@example.com"
    assert "abc" in msg["html"]
    assert "Killarney" in msg["subject"] or "trip" in msg["subject"].lower()


@pytest.mark.asyncio
async def test_send_magic_link_html_has_clickable_button():
    fake = FakeTransport()
    url = "https://example.test/login/verify?token=xyz"
    await mailer.send_magic_link("a@b.com", url, transport=fake)
    html = fake.sent[0]["html"]
    assert f'href="{url}"' in html
```

Add `pytest-asyncio` to `requirements.txt` if not present, and ensure `pytest.ini` (or `pyproject.toml`) sets `asyncio_mode = "auto"`. Check first with:

```
grep -r "asyncio_mode" pytest.ini pyproject.toml setup.cfg 2>/dev/null
```

If missing, add to `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 2: Run the test, expect FAIL**

```
python3 -m pytest tests/test_mailer.py -v
```
Expected: import error — module not found.

- [ ] **Step 3: Implement `app/services/mailer.py`**

```python
"""Email transport for magic-link delivery.

Production uses Resend's HTTP API. Tests pass a fake `transport` with
the same `.send(to, subject, html)` interface.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx


class Transport(Protocol):
    async def send(self, *, to: str, subject: str, html: str) -> None: ...


class ResendTransport:
    """Default production transport. Reads API key from env."""

    def __init__(self, api_key: str | None = None, mail_from: str | None = None):
        self.api_key = api_key or os.environ["RESEND_API_KEY"]
        self.mail_from = mail_from or os.environ["MAIL_FROM"]

    async def send(self, *, to: str, subject: str, html: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "from": self.mail_from,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            r.raise_for_status()


_DEFAULT: Transport | None = None


def default_transport() -> Transport:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ResendTransport()
    return _DEFAULT


def _render_magic_link_html(login_url: str) -> str:
    return f"""\
<!doctype html>
<html><body style="font-family:system-ui,sans-serif;color:#222;
                   max-width:480px;margin:2rem auto;padding:1rem;">
  <h1 style="font-family:Fraunces,Georgia,serif;color:#1f3a3a;">
    Killarney trip planner
  </h1>
  <p>Click the button below to sign in. The link expires in 15 minutes.</p>
  <p>
    <a href="{login_url}"
       style="display:inline-block;background:#2d5016;color:white;
              padding:.75rem 1.25rem;border-radius:6px;
              text-decoration:none;">Sign in</a>
  </p>
  <p style="color:#666;font-size:.9rem;">
    If you didn't ask for this, ignore the email.
  </p>
</body></html>
"""


async def send_magic_link(
    to: str,
    login_url: str,
    *,
    transport: Transport | None = None,
) -> None:
    tx = transport or default_transport()
    await tx.send(
        to=to,
        subject="Your Killarney trip planner sign-in link",
        html=_render_magic_link_html(login_url),
    )
```

- [ ] **Step 4: Run the tests, expect PASS**

```
python3 -m pytest tests/test_mailer.py -v
```
Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add app/services/mailer.py tests/test_mailer.py pytest.ini
git commit -m "feat(mailer): Resend transport + mockable magic-link sender"
```

---

### Task 5: Auth routes + identity migration

**Files:**
- Create: `app/routes/auth.py`
- Modify: `app/services/identity.py`, `app/main.py`
- Test: `tests/test_auth_routes.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
"""End-to-end auth flow via TestClient + fake mailer."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import db, mailer


@pytest.fixture
def client(tmp_path, monkeypatch):
    dbp = tmp_path / "ax.sqlite3"
    monkeypatch.setattr("app.services.auth.db.DATABASE_PATH", dbp)
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    sent = []
    async def fake_send(*, to, subject, html):
        sent.append({"to": to, "html": html})
    monkeypatch.setattr(mailer, "default_transport",
                        lambda: type("FT", (), {"send": fake_send})())
    c = TestClient(app)
    c._sent = sent  # type: ignore[attr-defined]
    return c


def test_login_post_issues_link_and_emails(client):
    r = client.post("/login", data={"email": "alex@example.com"})
    assert r.status_code == 200
    assert "check your email" in r.text.lower()
    assert len(client._sent) == 1  # type: ignore[attr-defined]
    assert "token=" in client._sent[0]["html"]  # type: ignore


def test_verify_with_valid_token_sets_session_cookie(client):
    client.post("/login", data={"email": "alex@example.com"})
    html = client._sent[0]["html"]  # type: ignore
    token = html.split("token=")[1].split('"')[0]
    r = client.get(f"/login/verify?token={token}", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "cp_session" in r.cookies


def test_verify_with_bad_token_returns_400(client):
    r = client.get("/login/verify?token=garbage", follow_redirects=False)
    assert r.status_code == 400


def test_logout_clears_session(client):
    client.post("/login", data={"email": "alex@example.com"})
    token = client._sent[0]["html"].split("token=")[1].split('"')[0]  # type: ignore
    client.get(f"/login/verify?token={token}", follow_redirects=False)
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code in (200, 302, 303)
    # Cookie should be cleared (Max-Age=0 or empty value)
    cookie_header = r.headers.get("set-cookie", "")
    assert "cp_session=" in cookie_header
```

- [ ] **Step 2: Run the tests, expect FAIL**

```
python3 -m pytest tests/test_auth_routes.py -v
```
Expected: 404s — routes don't exist.

- [ ] **Step 3: Implement `app/routes/auth.py`**

```python
"""Magic-link login flow."""

from __future__ import annotations

import os

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import JINJA_TEMPLATES_DIR
from app.services import auth, mailer

router = APIRouter()
templates = Jinja2Templates(directory=str(JINJA_TEMPLATES_DIR))

SESSION_COOKIE = "cp_session"


def _base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html",
                                       {"request": request, "sent": False})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...)):
    email = email.strip().lower()
    token = auth.issue_magic_link(email)
    url = f"{_base_url()}/login/verify?token={token}"
    await mailer.send_magic_link(email, url)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "sent": True, "email": email},
    )


@router.get("/login/verify")
async def login_verify(request: Request, token: str, next: str = "/"):
    try:
        session_id = auth.consume_magic_link(token)
    except auth.MagicLinkInvalid as e:
        raise HTTPException(status_code=400, detail=str(e))
    resp = RedirectResponse(url=next, status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return resp


@router.post("/logout")
async def logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE, "")
    if sid:
        auth.delete_session(sid)
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
```

Create a minimal placeholder template `app/templates/login.html` for the test to pass (Plan 2 replaces it with the proper design):

```html
{% if sent %}
  <p>Check your email — link sent to {{ email }}.</p>
{% else %}
  <form method="post" action="/login">
    <label>Email <input name="email" type="email" required></label>
    <button type="submit">send me a link</button>
  </form>
{% endif %}
```

Update `app/services/identity.py`:

```python
"""Identity from session cookie.

The session id resolves to a `users` row; that's the active user. Empty
cookie / unknown session → anonymous.
"""

from __future__ import annotations

from fastapi import Request

from app.services import auth

SESSION_COOKIE = "cp_session"


def current_user(request: Request) -> dict | None:
    sid = request.cookies.get(SESSION_COOKIE, "")
    return auth.user_for_session(sid)


def current_email(request: Request) -> str:
    user = current_user(request)
    return user["email"] if user else ""
```

(Other modules that import `normalise` or `current_user` for the old return type need updating. After this edit, run a project-wide grep and fix call sites: `grep -rn "from app.services.identity" app/`. Existing checklist code that passed a string `user` parameter now passes `current_email(request)` instead.)

Register the auth router in `app/main.py`:

```python
from app.routes import auth, checklist, identity, pages, parks, trips
...
app.include_router(auth.router)
```

- [ ] **Step 4: Run all tests, expect PASS**

```
python3 -m pytest tests/ -q
```
Expected: all green; if existing tests using the old `cp_user` cookie break, fix them to use `cp_session` or pre-create a session in their fixtures.

- [ ] **Step 5: Commit**

```bash
git add app/routes/auth.py app/services/identity.py app/main.py \
       app/templates/login.html tests/test_auth_routes.py
git commit -m "feat(auth): login/verify/logout routes + session-cookie identity"
```

---

## Phase C — Structured content

### Task 6: Food repository

**Files:**
- Create: `app/services/food_repo.py`
- Test: `tests/test_food_repo.py`

- [ ] **Step 1: Write the failing tests**

```python
"""food_items CRUD with conflict detection."""

import pytest

from app.services import auth, db, food_repo


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "f.sqlite3"
    db.init_schema(p)
    auth.upsert_user("alex@example.com", path=p)
    return p


def test_insert_returns_row_with_id_and_timestamp(dbpath):
    row = food_repo.insert(
        trip_slug="killarney-2026-05",
        day_index=1, meal="dinner", item="Pasta",
        assigned_to="Alex", notes="extra", sort_order=1.0,
        user_id=1, path=dbpath,
    )
    assert row["id"]
    assert row["updated_at"]
    assert row["item"] == "Pasta"


def test_list_groups_by_day_meal_sort(dbpath):
    food_repo.insert(trip_slug="t", day_index=2, meal="lunch",
                     item="B", assigned_to="", notes="", sort_order=1.0,
                     user_id=1, path=dbpath)
    food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                     item="A", assigned_to="", notes="", sort_order=1.0,
                     user_id=1, path=dbpath)
    rows = food_repo.list_for_trip("t", path=dbpath)
    assert [r["item"] for r in rows] == ["A", "B"]


def test_update_with_correct_expected_updated_at_succeeds(dbpath):
    row = food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                           item="A", assigned_to="", notes="", sort_order=1.0,
                           user_id=1, path=dbpath)
    updated = food_repo.update(
        row["id"], expected_updated_at=row["updated_at"],
        item="A2", user_id=1, path=dbpath,
    )
    assert updated["item"] == "A2"
    assert updated["updated_at"] > row["updated_at"]


def test_update_with_stale_expected_raises_conflict(dbpath):
    row = food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                           item="A", assigned_to="", notes="", sort_order=1.0,
                           user_id=1, path=dbpath)
    food_repo.update(row["id"], expected_updated_at=row["updated_at"],
                     item="A2", user_id=1, path=dbpath)
    # second update with the original stale timestamp
    with pytest.raises(food_repo.Conflict) as exc:
        food_repo.update(row["id"], expected_updated_at=row["updated_at"],
                         item="A3", user_id=1, path=dbpath)
    assert exc.value.current["item"] == "A2"


def test_delete_removes_row(dbpath):
    row = food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                           item="A", assigned_to="", notes="", sort_order=1.0,
                           user_id=1, path=dbpath)
    food_repo.delete(row["id"], path=dbpath)
    assert food_repo.list_for_trip("t", path=dbpath) == []
```

- [ ] **Step 2: Run, expect FAIL**

```
python3 -m pytest tests/test_food_repo.py -v
```

- [ ] **Step 3: Implement `app/services/food_repo.py`**

```python
"""food_items CRUD. Conflicts detected via expected_updated_at."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.services import db


class Conflict(Exception):
    def __init__(self, current: dict):
        super().__init__("food row was modified concurrently")
        self.current = current


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def insert(
    *,
    trip_slug: str,
    day_index: int,
    meal: str,
    item: str,
    assigned_to: str | None,
    notes: str | None,
    sort_order: float,
    user_id: int,
    path: Path | None = None,
) -> dict:
    now = _iso_now()
    with db.connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO food_items "
            "(trip_slug, day_index, meal, item, assigned_to, notes, "
            " sort_order, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trip_slug, day_index, meal, item, assigned_to, notes,
             sort_order, now, user_id),
        )
        rid = cur.lastrowid
        return _row_to_dict(conn.execute(
            "SELECT * FROM food_items WHERE id = ?", (rid,)
        ).fetchone())


def list_for_trip(trip_slug: str, path: Path | None = None) -> list[dict]:
    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM food_items WHERE trip_slug = ? "
            "ORDER BY day_index, meal, sort_order",
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
    allowed = {"day_index", "meal", "item", "assigned_to",
               "notes", "sort_order"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown fields: {bad}")
    now = _iso_now()
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM food_items WHERE id = ?", (row_id,),
        ).fetchone()
        if row is None:
            raise KeyError(row_id)
        if row["updated_at"] != expected_updated_at:
            raise Conflict(current=_row_to_dict(row))
        sets = ", ".join(f"{k} = ?" for k in fields)
        sets += ", updated_at = ?, updated_by = ?"
        values = list(fields.values()) + [now, user_id, row_id]
        conn.execute(
            f"UPDATE food_items SET {sets} WHERE id = ?", values,
        )
        return _row_to_dict(conn.execute(
            "SELECT * FROM food_items WHERE id = ?", (row_id,)
        ).fetchone())


def delete(row_id: int, path: Path | None = None) -> None:
    with db.connect(path) as conn:
        conn.execute("DELETE FROM food_items WHERE id = ?", (row_id,))
```

- [ ] **Step 4: Run, expect PASS**

```
python3 -m pytest tests/test_food_repo.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/services/food_repo.py tests/test_food_repo.py
git commit -m "feat(food): repo with conflict detection on expected_updated_at"
```

---

### Task 7: Gear repository (mirror of food)

**Files:**
- Create: `app/services/gear_repo.py`
- Test: `tests/test_gear_repo.py`

- [ ] **Step 1: Write the failing tests**

Mirror `test_food_repo.py` structure, swapping fields:
- `day_index, meal` → `category`
- `quantity` is a new field

```python
"""gear_items CRUD."""

import pytest

from app.services import auth, db, gear_repo


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "g.sqlite3"
    db.init_schema(p)
    auth.upsert_user("alex@example.com", path=p)
    return p


def test_insert_returns_row(dbpath):
    row = gear_repo.insert(
        trip_slug="t", category="shelter", item="Tent (3p)",
        quantity="1", assigned_to="Alex", notes="", sort_order=1.0,
        user_id=1, path=dbpath,
    )
    assert row["id"]
    assert row["item"] == "Tent (3p)"


def test_list_orders_by_category_then_sort(dbpath):
    gear_repo.insert(trip_slug="t", category="kitchen", item="Stove",
                     quantity="1", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    gear_repo.insert(trip_slug="t", category="shelter", item="Tent",
                     quantity="1", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    rows = gear_repo.list_for_trip("t", path=dbpath)
    assert [r["category"] for r in rows] == ["kitchen", "shelter"]


def test_update_conflict_detection(dbpath):
    row = gear_repo.insert(trip_slug="t", category="kitchen", item="Stove",
                           quantity="1", assigned_to="", notes="",
                           sort_order=1.0, user_id=1, path=dbpath)
    gear_repo.update(row["id"], expected_updated_at=row["updated_at"],
                     item="Big Stove", user_id=1, path=dbpath)
    with pytest.raises(gear_repo.Conflict):
        gear_repo.update(row["id"], expected_updated_at=row["updated_at"],
                         item="Other", user_id=1, path=dbpath)


def test_delete_removes(dbpath):
    row = gear_repo.insert(trip_slug="t", category="kitchen", item="Stove",
                           quantity="1", assigned_to="", notes="",
                           sort_order=1.0, user_id=1, path=dbpath)
    gear_repo.delete(row["id"], path=dbpath)
    assert gear_repo.list_for_trip("t", path=dbpath) == []
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `app/services/gear_repo.py`**

```python
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
    *, trip_slug, category, item, quantity, assigned_to,
    notes, sort_order, user_id, path=None,
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


def list_for_trip(trip_slug, path=None) -> list[dict]:
    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM gear_items WHERE trip_slug = ? "
            "ORDER BY category, sort_order",
            (trip_slug,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update(row_id, *, expected_updated_at, user_id, path=None, **fields) -> dict:
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


def delete(row_id, path=None) -> None:
    with db.connect(path) as conn:
        conn.execute("DELETE FROM gear_items WHERE id = ?", (row_id,))
```

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add app/services/gear_repo.py tests/test_gear_repo.py
git commit -m "feat(gear): repo with conflict detection (mirror of food_repo)"
```

---

### Task 8: Food + gear routes (auth-gated)

**Files:**
- Create: `app/routes/food.py`, `app/routes/gear.py`
- Modify: `app/main.py`
- Test: `tests/test_food_routes.py`, `tests/test_gear_routes.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_food_routes.py`:

```python
"""Food row CRUD over HTTP, auth-gated."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth, db


@pytest.fixture
def setup(tmp_path, monkeypatch):
    dbp = tmp_path / "x.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="editor", path=dbp)
    # Mint a session directly
    import secrets, time
    from datetime import datetime, timezone
    sid = secrets.token_urlsafe(32)
    with db.connect(dbp) as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, 1, ?, ?)",
            (sid,
             datetime.now(timezone.utc).isoformat(),
             datetime.fromtimestamp(time.time() + 3600,
                                    tz=timezone.utc).isoformat()),
        )
    client = TestClient(app, cookies={"cp_session": sid})
    return client


def test_get_food_empty(setup):
    r = setup.get("/api/trips/t/food")
    assert r.status_code == 200
    assert r.json() == {"rows": []}


def test_post_food_creates_row(setup):
    r = setup.post("/api/trips/t/food", json={
        "day_index": 1, "meal": "dinner", "item": "Pasta",
        "assigned_to": "Alex", "notes": "", "sort_order": 1.0,
    })
    assert r.status_code == 200
    assert r.json()["row"]["item"] == "Pasta"


def test_put_food_with_stale_timestamp_409(setup):
    r = setup.post("/api/trips/t/food", json={
        "day_index": 1, "meal": "dinner", "item": "Pasta",
        "assigned_to": "", "notes": "", "sort_order": 1.0,
    })
    row = r.json()["row"]
    # First update
    setup.put(f"/api/trips/t/food/{row['id']}", json={
        "expected_updated_at": row["updated_at"],
        "item": "Risotto",
    })
    # Stale update
    r2 = setup.put(f"/api/trips/t/food/{row['id']}", json={
        "expected_updated_at": row["updated_at"],
        "item": "Pizza",
    })
    assert r2.status_code == 409
    assert r2.json()["current"]["item"] == "Risotto"


def test_non_member_gets_403(tmp_path, monkeypatch):
    dbp = tmp_path / "y.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    auth.upsert_user("ghost@example.com", path=dbp)
    # session for a user who is not a trip member
    import secrets, time
    from datetime import datetime, timezone
    sid = secrets.token_urlsafe(32)
    with db.connect(dbp) as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, 1, ?, ?)",
            (sid,
             datetime.now(timezone.utc).isoformat(),
             datetime.fromtimestamp(time.time() + 3600,
                                    tz=timezone.utc).isoformat()),
        )
    client = TestClient(app, cookies={"cp_session": sid})
    assert client.get("/api/trips/t/food").status_code == 403
```

Add a parallel `tests/test_gear_routes.py` with the same structure on `/api/trips/<slug>/gear`.

- [ ] **Step 2: Run, expect FAIL**

```
python3 -m pytest tests/test_food_routes.py tests/test_gear_routes.py -v
```

- [ ] **Step 3: Implement `app/routes/food.py`**

```python
"""Food row CRUD endpoints, member-gated."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services import auth, food_repo
from app.services.identity import current_user

router = APIRouter(prefix="/api/trips/{slug}/food", tags=["food"])


class FoodIn(BaseModel):
    day_index: int
    meal: str
    item: str
    assigned_to: str | None = ""
    notes: str | None = ""
    sort_order: float


class FoodPatch(BaseModel):
    expected_updated_at: str
    day_index: int | None = None
    meal: str | None = None
    item: str | None = None
    assigned_to: str | None = None
    notes: str | None = None
    sort_order: float | None = None


def _require_member(request: Request, slug: str) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "not signed in")
    if not auth.is_trip_member(slug, user["email"]):
        raise HTTPException(403, "not a member of this trip")
    return user


@router.get("")
async def list_food(slug: str, request: Request):
    _require_member(request, slug)
    return {"rows": food_repo.list_for_trip(slug)}


@router.post("")
async def create_food(slug: str, body: FoodIn, request: Request):
    user = _require_member(request, slug)
    row = food_repo.insert(
        trip_slug=slug,
        day_index=body.day_index, meal=body.meal, item=body.item,
        assigned_to=body.assigned_to, notes=body.notes,
        sort_order=body.sort_order, user_id=user["id"],
    )
    # broadcast hooked in Task 11
    return {"row": row}


@router.put("/{row_id}")
async def update_food(slug: str, row_id: int,
                      body: FoodPatch, request: Request):
    user = _require_member(request, slug)
    fields = {k: v for k, v in body.model_dump().items()
              if k != "expected_updated_at" and v is not None}
    try:
        row = food_repo.update(
            row_id,
            expected_updated_at=body.expected_updated_at,
            user_id=user["id"], **fields,
        )
    except food_repo.Conflict as e:
        raise HTTPException(409, detail={"current": e.current})
    return {"row": row}


@router.delete("/{row_id}")
async def delete_food(slug: str, row_id: int, request: Request):
    _require_member(request, slug)
    food_repo.delete(row_id)
    return {"ok": True}
```

`app/routes/gear.py` is a parallel module — same shape, gear fields, `prefix="/api/trips/{slug}/gear"`.

Register both in `app/main.py`:

```python
from app.routes import auth, checklist, food, gear, identity, pages, parks, trips
...
app.include_router(food.router)
app.include_router(gear.router)
```

- [ ] **Step 4: Run, expect PASS**

```
python3 -m pytest tests/test_food_routes.py tests/test_gear_routes.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/routes/food.py app/routes/gear.py app/main.py \
       tests/test_food_routes.py tests/test_gear_routes.py
git commit -m "feat(api): food + gear CRUD routes with member gating + conflict 409"
```

---

## Phase D — SSE & broadcast

### Task 9: Broadcast service

**Files:**
- Create: `app/services/broadcast.py`
- Test: `tests/test_broadcast.py`

- [ ] **Step 1: Write the failing test**

```python
"""In-process pub/sub for SSE fan-out."""

import asyncio

import pytest

from app.services import broadcast


@pytest.mark.asyncio
async def test_subscriber_receives_published_event():
    bus = broadcast.Bus()
    q = bus.subscribe("t1")
    await bus.publish("t1", {"type": "food.upsert", "row": {"id": 1}})
    event = await asyncio.wait_for(q.get(), timeout=0.5)
    assert event["row"]["id"] == 1


@pytest.mark.asyncio
async def test_publish_to_other_trip_not_received():
    bus = broadcast.Bus()
    q = bus.subscribe("t1")
    await bus.publish("t2", {"type": "x"})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_full_queue_drops_for_that_subscriber_only():
    bus = broadcast.Bus(max_queue=2)
    slow = bus.subscribe("t1")
    fast = bus.subscribe("t1")
    for i in range(4):
        await bus.publish("t1", {"i": i})
    # fast consumer should still get the first 2 (the rest dropped for both)
    got = []
    try:
        while True:
            got.append(await asyncio.wait_for(fast.get(), timeout=0.05))
    except asyncio.TimeoutError:
        pass
    assert len(got) == 2  # capped at queue size
    assert slow.qsize() == 2


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue():
    bus = broadcast.Bus()
    q = bus.subscribe("t1")
    bus.unsubscribe("t1", q)
    await bus.publish("t1", {"type": "x"})
    assert q.qsize() == 0
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `app/services/broadcast.py`**

```python
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
```

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add app/services/broadcast.py tests/test_broadcast.py
git commit -m "feat(broadcast): in-process asyncio pub/sub for SSE fan-out"
```

---

### Task 10: SSE route handler + presence

**Files:**
- Create: `app/routes/sse.py`
- Modify: `app/main.py`
- Test: `tests/test_sse.py`

- [ ] **Step 1: Write the failing test**

```python
"""SSE stream + presence broadcast."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth, broadcast, db


@pytest.fixture
def authed_client(tmp_path, monkeypatch):
    dbp = tmp_path / "s.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="editor", path=dbp)
    import secrets, time
    from datetime import datetime, timezone
    sid = secrets.token_urlsafe(32)
    with db.connect(dbp) as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, 1, ?, ?)",
            (sid,
             datetime.now(timezone.utc).isoformat(),
             datetime.fromtimestamp(time.time() + 3600,
                                    tz=timezone.utc).isoformat()),
        )
    return TestClient(app, cookies={"cp_session": sid})


def test_sse_unauthenticated_returns_401(tmp_path, monkeypatch):
    dbp = tmp_path / "u.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    client = TestClient(app)
    r = client.get("/trips/t/events")
    assert r.status_code in (401, 403)


def test_sse_receives_a_published_event(authed_client):
    # Publish before connecting won't reach the stream — publish from a
    # background task after the stream is open.
    with authed_client.stream("GET", "/trips/t/events") as r:
        assert r.status_code == 200
        # Trigger an event by posting a food row in another request
        authed_client.post("/api/trips/t/food", json={
            "day_index": 1, "meal": "dinner", "item": "Pasta",
            "assigned_to": "", "notes": "", "sort_order": 1.0,
        })
        # Read one event line group from the stream (data: {...}\n\n)
        chunks = []
        for line in r.iter_lines():
            chunks.append(line)
            if len(chunks) > 10:
                break
            # Stop once we see a data: line
            if line.startswith("data:"):
                break
        data_line = next(c for c in chunks if c.startswith("data:"))
        payload = json.loads(data_line[len("data:"):].strip())
        assert payload["type"] == "food.upsert"
        assert payload["row"]["item"] == "Pasta"
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `app/routes/sse.py`**

```python
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
    await broadcast.default_bus.publish(slug, {
        "type": "presence",
        "users": sorted(_presence.get(slug, ())),
    })


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
```

Add `sse-starlette` to `requirements.txt`:

```
sse-starlette>=2.1
```

Register in `app/main.py`:

```python
from app.routes import auth, checklist, food, gear, identity, pages, parks, sse, trips
...
app.include_router(sse.router)
```

- [ ] **Step 4: Run, expect PASS**

Note: this test depends on Task 11's broadcast wiring. If running tasks strictly in order, the test for "receives a published event" will still fail until the broadcast call is added in Task 11. Use `-k unauth` to limit to the auth test for now, or skip to Task 11 and validate both together.

- [ ] **Step 5: Commit**

```bash
git add app/routes/sse.py app/main.py requirements.txt tests/test_sse.py
git commit -m "feat(sse): per-trip event stream with presence broadcast"
```

---

### Task 11: Wire broadcasts into food + gear POST/PUT/DELETE

**Files:**
- Modify: `app/routes/food.py`, `app/routes/gear.py`

- [ ] **Step 1: Re-run the previously failing SSE test**

```
python3 -m pytest tests/test_sse.py::test_sse_receives_a_published_event -v
```
Expected: still FAIL — no broadcast yet from the food route.

- [ ] **Step 2: Add broadcast calls in `app/routes/food.py`**

At top of file:

```python
from app.services import broadcast
```

In `create_food`, after `row = food_repo.insert(...)`:

```python
    await broadcast.default_bus.publish(slug, {"type": "food.upsert", "row": row})
    return {"row": row}
```

In `update_food`, after `row = food_repo.update(...)`:

```python
    await broadcast.default_bus.publish(slug, {"type": "food.upsert", "row": row})
    return {"row": row}
```

In `delete_food`, after `food_repo.delete(...)`:

```python
    await broadcast.default_bus.publish(slug, {"type": "food.delete", "id": row_id})
    return {"ok": True}
```

Mirror the three additions in `app/routes/gear.py` with event types `gear.upsert` / `gear.delete`.

- [ ] **Step 3: Run the test, expect PASS**

```
python3 -m pytest tests/test_sse.py -v
```

- [ ] **Step 4: Run full suite**

```
python3 -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add app/routes/food.py app/routes/gear.py
git commit -m "feat(sse): broadcast row events from food + gear endpoints"
```

---

## Phase E — Snapshot & seeding

### Task 12: Markdown → DB seed

**Files:**
- Create: `app/services/seed.py`, `scripts/seed_from_markdown.py`
- Test: `tests/test_seed.py`

- [ ] **Step 1: Write the failing test**

```python
"""Idempotent markdown → DB seed."""

import pytest

from app.services import auth, db, food_repo, gear_repo, seed


FOOD_MD = """\
# Food Plan

## Day 1 — Friday

| Meal | Item | Who | Notes |
|---|---|---|---|
| Breakfast | Pancakes + bacon | Alex | extra syrup |
| Breakfast | Coffee | shared | |
| Dinner | Pasta | Alex | |

## Day 2 — Saturday

| Meal | Item | Who | Notes |
|---|---|---|---|
| Lunch | Wraps | Thomas | |
"""

GEAR_MD = """\
# Gear

## shelter

| Item | Qty | Who | Notes |
|---|---|---|---|
| Tent (3p) | 1 | Alex | |
| Tarp | 1 | shared | |

## kitchen

| Item | Qty | Who | Notes |
|---|---|---|---|
| Stove | 1 | Thomas | |
"""


def test_seed_food_parses_two_days(tmp_path):
    dbp = tmp_path / "s.sqlite3"
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="owner", path=dbp)
    trip_dir = tmp_path / "trips" / "t"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(FOOD_MD)
    seed.seed_trip("t", trip_dir, owner_email="alex@example.com", path=dbp)
    rows = food_repo.list_for_trip("t", path=dbp)
    items = [(r["day_index"], r["meal"], r["item"]) for r in rows]
    assert (1, "breakfast", "Pancakes + bacon") in items
    assert (2, "lunch", "Wraps") in items


def test_seed_gear_parses_categories(tmp_path):
    dbp = tmp_path / "s.sqlite3"
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="owner", path=dbp)
    trip_dir = tmp_path / "trips" / "t"
    trip_dir.mkdir(parents=True)
    (trip_dir / "gear.md").write_text(GEAR_MD)
    seed.seed_trip("t", trip_dir, owner_email="alex@example.com", path=dbp)
    rows = gear_repo.list_for_trip("t", path=dbp)
    cats = {r["category"] for r in rows}
    assert {"shelter", "kitchen"} == cats


def test_seed_is_idempotent(tmp_path):
    dbp = tmp_path / "s.sqlite3"
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    trip_dir = tmp_path / "trips" / "t"
    trip_dir.mkdir(parents=True)
    (trip_dir / "food.md").write_text(FOOD_MD)
    seed.seed_trip("t", trip_dir, owner_email="alex@example.com", path=dbp)
    seed.seed_trip("t", trip_dir, owner_email="alex@example.com", path=dbp)
    rows = food_repo.list_for_trip("t", path=dbp)
    # Should not double-insert
    assert len(rows) == 4  # 3 from day 1, 1 from day 2
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `app/services/seed.py`**

```python
"""Parse food.md / gear.md markdown tables into DB rows. Idempotent.

Recognises the markdown structure produced by build_trip.py / the trip
template — `## Day N — <weekday>` for food, `## <category>` for gear.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from app.services import auth, db, food_repo, gear_repo


MEAL_NORM = {
    "breakfast": "breakfast", "lunch": "lunch",
    "dinner": "dinner", "snack": "snack",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_section_seeded(slug: str, section: str, path: Path | None) -> bool:
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT seeded_from_md_at FROM section_state "
            "WHERE trip_slug = ? AND section = ?",
            (slug, section),
        ).fetchone()
    return row is not None and row["seeded_from_md_at"] is not None


def _mark_seeded(slug: str, section: str, path: Path | None) -> None:
    with db.connect(path) as conn:
        conn.execute(
            "INSERT INTO section_state (trip_slug, section, seeded_from_md_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(trip_slug, section) DO UPDATE SET "
            "seeded_from_md_at = excluded.seeded_from_md_at",
            (slug, section, _iso_now()),
        )


_DAY_RE = re.compile(r"^##\s+Day\s+(\d+)\b", re.MULTILINE)
_GEAR_CAT_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*$", re.MULTILINE)


def _parse_table(block: str) -> list[list[str]]:
    """Returns rows of cells (excluding header + separator)."""
    rows = []
    seen_header = False
    skipped_sep = False
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not seen_header:
            seen_header = True
            continue
        if not skipped_sep:
            skipped_sep = True
            continue
        rows.append(cells)
    return rows


def _parse_food_md(text: str) -> list[dict]:
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)[1:]
    out: list[dict] = []
    for sec in sections:
        m = re.match(r"Day\s+(\d+)", sec)
        if not m:
            continue
        day = int(m.group(1))
        order = 1.0
        for cells in _parse_table(sec):
            if len(cells) < 2:
                continue
            meal = cells[0].lower().strip()
            meal = MEAL_NORM.get(meal, meal)
            item = cells[1].strip()
            who = cells[2].strip() if len(cells) > 2 else ""
            notes = cells[3].strip() if len(cells) > 3 else ""
            if not item:
                continue
            out.append({
                "day_index": day, "meal": meal, "item": item,
                "assigned_to": who, "notes": notes, "sort_order": order,
            })
            order += 1.0
    return out


def _parse_gear_md(text: str) -> list[dict]:
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)[1:]
    out: list[dict] = []
    for sec in sections:
        lines = sec.splitlines()
        cat = lines[0].strip().lower() if lines else ""
        if not cat:
            continue
        order = 1.0
        for cells in _parse_table(sec):
            if len(cells) < 1:
                continue
            item = cells[0].strip()
            qty = cells[1].strip() if len(cells) > 1 else ""
            who = cells[2].strip() if len(cells) > 2 else ""
            notes = cells[3].strip() if len(cells) > 3 else ""
            if not item:
                continue
            out.append({
                "category": cat, "item": item, "quantity": qty,
                "assigned_to": who, "notes": notes, "sort_order": order,
            })
            order += 1.0
    return out


def seed_trip(
    slug: str,
    trip_dir: Path,
    *,
    owner_email: str,
    path: Path | None = None,
) -> None:
    """Seed food + gear from markdown if not already seeded. Idempotent."""
    user_id = auth.upsert_user(owner_email, path=path)
    auth.add_trip_member(slug, owner_email, role="owner", path=path)

    food_md = trip_dir / "food.md"
    if food_md.exists() and not _is_section_seeded(slug, "food", path):
        for r in _parse_food_md(food_md.read_text()):
            food_repo.insert(trip_slug=slug, user_id=user_id, path=path, **r)
        _mark_seeded(slug, "food", path)

    gear_md = trip_dir / "gear.md"
    if gear_md.exists() and not _is_section_seeded(slug, "gear", path):
        for r in _parse_gear_md(gear_md.read_text()):
            gear_repo.insert(trip_slug=slug, user_id=user_id, path=path, **r)
        _mark_seeded(slug, "gear", path)
```

Create `scripts/seed_from_markdown.py`:

```python
#!/usr/bin/env python3
"""Walk TRIPS_DIR and seed every trip's food+gear into the DB."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import TRIPS_DIR  # noqa: E402
from app.services import seed  # noqa: E402


def main() -> None:
    owner = os.environ.get("BOOTSTRAP_OWNER_EMAIL")
    if not owner:
        raise SystemExit("BOOTSTRAP_OWNER_EMAIL env var is required")
    for trip_dir in sorted(TRIPS_DIR.glob("*/")):
        slug = trip_dir.name
        print(f"seeding {slug}…", flush=True)
        seed.seed_trip(slug, trip_dir, owner_email=owner)


if __name__ == "__main__":
    main()
```

`chmod +x scripts/seed_from_markdown.py`.

- [ ] **Step 4: Run, expect PASS**

```
python3 -m pytest tests/test_seed.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/services/seed.py scripts/seed_from_markdown.py tests/test_seed.py
git commit -m "feat(seed): idempotent food.md / gear.md → DB rows"
```

---

### Task 13: Deterministic markdown renderer

**Files:**
- Create: `app/services/snapshot.py`
- Test: `tests/test_snapshot.py`

- [ ] **Step 1: Write the failing tests**

```python
"""DB rows → markdown is deterministic and byte-stable."""

import pytest

from app.services import auth, db, food_repo, gear_repo, snapshot


@pytest.fixture
def dbpath(tmp_path):
    p = tmp_path / "x.sqlite3"
    db.init_schema(p)
    auth.upsert_user("alex@example.com", path=p)
    return p


def test_render_food_md_grouped_by_day_then_meal(dbpath):
    food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                     item="Pasta", assigned_to="Alex", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    food_repo.insert(trip_slug="t", day_index=1, meal="breakfast",
                     item="Coffee", assigned_to="shared", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    food_repo.insert(trip_slug="t", day_index=2, meal="lunch",
                     item="Wraps", assigned_to="Thomas", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    md = snapshot.render_food_markdown("t", path=dbpath)
    assert "## Day 1" in md
    assert "## Day 2" in md
    assert md.index("## Day 1") < md.index("## Day 2")
    assert "Breakfast" in md and "Dinner" in md
    assert md.index("Breakfast") < md.index("Dinner")


def test_render_food_md_is_byte_stable_across_two_runs(dbpath):
    food_repo.insert(trip_slug="t", day_index=1, meal="dinner",
                     item="Pasta", assigned_to="Alex", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    a = snapshot.render_food_markdown("t", path=dbpath)
    b = snapshot.render_food_markdown("t", path=dbpath)
    assert a == b


def test_render_escapes_pipe_in_item_text(dbpath):
    food_repo.insert(trip_slug="t", day_index=1, meal="lunch",
                     item="Chips | salsa", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    md = snapshot.render_food_markdown("t", path=dbpath)
    assert "Chips \\| salsa" in md


def test_render_gear_md_grouped_by_category(dbpath):
    gear_repo.insert(trip_slug="t", category="shelter", item="Tent",
                     quantity="1", assigned_to="Alex", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    gear_repo.insert(trip_slug="t", category="kitchen", item="Stove",
                     quantity="1", assigned_to="Thomas", notes="",
                     sort_order=1.0, user_id=1, path=dbpath)
    md = snapshot.render_gear_markdown("t", path=dbpath)
    assert "## kitchen" in md
    assert "## shelter" in md
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `app/services/snapshot.py`**

```python
"""Render food_items / gear_items rows back to deterministic markdown.

Output is byte-stable: same rows always produce the same string. Pipe
characters in user-entered text are escaped (`\\|`).
"""

from __future__ import annotations

from pathlib import Path

from app.services import food_repo, gear_repo

MEAL_LABEL = {
    "breakfast": "Breakfast", "lunch": "Lunch",
    "dinner": "Dinner", "snack": "Snack",
}
MEAL_ORDER = ["breakfast", "lunch", "dinner", "snack"]


def _esc(text: str | None) -> str:
    return (text or "").replace("|", r"\|")


def render_food_markdown(slug: str, path: Path | None = None) -> str:
    rows = food_repo.list_for_trip(slug, path=path)
    by_day: dict[int, dict[str, list[dict]]] = {}
    for r in rows:
        by_day.setdefault(r["day_index"], {}).setdefault(r["meal"], []).append(r)
    out: list[str] = ["# Food Plan", ""]
    for day in sorted(by_day):
        out.append(f"## Day {day}")
        out.append("")
        out.append("| Meal | Item | Who | Notes |")
        out.append("|---|---|---|---|")
        for meal in MEAL_ORDER:
            for r in by_day[day].get(meal, []):
                out.append(
                    f"| {MEAL_LABEL[meal]} | {_esc(r['item'])} "
                    f"| {_esc(r['assigned_to'])} | {_esc(r['notes'])} |"
                )
        # any meals not in MEAL_ORDER
        for meal, rs in by_day[day].items():
            if meal in MEAL_ORDER:
                continue
            for r in rs:
                out.append(
                    f"| {meal.title()} | {_esc(r['item'])} "
                    f"| {_esc(r['assigned_to'])} | {_esc(r['notes'])} |"
                )
        out.append("")
    return "\n".join(out)


def render_gear_markdown(slug: str, path: Path | None = None) -> str:
    rows = gear_repo.list_for_trip(slug, path=path)
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    out: list[str] = ["# Gear", ""]
    for cat in sorted(by_cat):
        out.append(f"## {cat}")
        out.append("")
        out.append("| Item | Qty | Who | Notes |")
        out.append("|---|---|---|---|")
        for r in by_cat[cat]:
            out.append(
                f"| {_esc(r['item'])} | {_esc(r['quantity'])} "
                f"| {_esc(r['assigned_to'])} | {_esc(r['notes'])} |"
            )
        out.append("")
    return "\n".join(out)
```

- [ ] **Step 4: Run, expect PASS**

```
python3 -m pytest tests/test_snapshot.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/services/snapshot.py tests/test_snapshot.py
git commit -m "feat(snapshot): deterministic food + gear markdown renderers"
```

---

### Task 14: Snapshot endpoint + build_trip.py invocation

**Files:**
- Modify: `app/routes/trips.py`, `app/services/snapshot.py`
- Test: extend `tests/test_snapshot.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_snapshot.py`:

```python
def test_write_snapshot_creates_files_and_updates_state(tmp_path, monkeypatch):
    from app.services import auth, db, food_repo, snapshot
    dbp = tmp_path / "x.sqlite3"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    trip_dir = tmp_path / "trips" / "t"
    trip_dir.mkdir(parents=True)
    food_repo.insert(trip_slug="t", day_index=1, meal="lunch",
                     item="Wraps", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbp)
    paths = snapshot.write_snapshot("t", trip_dir, run_build_trip=False,
                                     path=dbp)
    assert (trip_dir / "food.md").read_text().startswith("# Food Plan")
    assert (trip_dir / "gear.md").exists()
    # last_snapshotted_at recorded
    with db.connect(dbp) as conn:
        row = conn.execute(
            "SELECT last_snapshotted_at FROM section_state "
            "WHERE trip_slug = ? AND section = 'food'", ("t",),
        ).fetchone()
    assert row and row["last_snapshotted_at"]
```

And a TestClient test for the endpoint:

```python
def test_snapshot_endpoint_writes_files(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import auth, db, food_repo

    dbp = tmp_path / "x.sqlite3"
    trips = tmp_path / "trips"
    monkeypatch.setattr("app.services.db.DATABASE_PATH", dbp)
    monkeypatch.setattr("app.config.TRIPS_DIR", trips)
    monkeypatch.setattr("app.routes.trips.TRIPS_DIR", trips)
    db.init_schema(dbp)
    auth.upsert_user("alex@example.com", path=dbp)
    auth.add_trip_member("t", "alex@example.com", role="owner", path=dbp)
    (trips / "t").mkdir(parents=True)
    food_repo.insert(trip_slug="t", day_index=1, meal="lunch",
                     item="Wraps", assigned_to="", notes="",
                     sort_order=1.0, user_id=1, path=dbp)
    # mint session
    import secrets, time
    from datetime import datetime, timezone
    sid = secrets.token_urlsafe(32)
    with db.connect(dbp) as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) "
            "VALUES (?, 1, ?, ?)",
            (sid, datetime.now(timezone.utc).isoformat(),
             datetime.fromtimestamp(time.time() + 3600,
                                    tz=timezone.utc).isoformat()),
        )
    client = TestClient(app, cookies={"cp_session": sid})
    r = client.post("/api/trips/t/snapshot",
                     json={"run_build_trip": False})
    assert r.status_code == 200
    assert (trips / "t" / "food.md").exists()
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement**

Add to `app/services/snapshot.py`:

```python
import subprocess
import sys
from datetime import datetime, timezone

from app.services import db


def _record_snapshotted(
    slug: str, section: str, path: Path | None = None,
) -> None:
    iso = datetime.now(timezone.utc).isoformat()
    with db.connect(path) as conn:
        conn.execute(
            "INSERT INTO section_state "
            "(trip_slug, section, last_snapshotted_at) VALUES (?, ?, ?) "
            "ON CONFLICT(trip_slug, section) DO UPDATE SET "
            "last_snapshotted_at = excluded.last_snapshotted_at",
            (slug, section, iso),
        )


def write_snapshot(
    slug: str,
    trip_dir: Path,
    *,
    run_build_trip: bool = True,
    path: Path | None = None,
) -> dict:
    trip_dir.mkdir(parents=True, exist_ok=True)
    food_path = trip_dir / "food.md"
    gear_path = trip_dir / "gear.md"
    food_path.write_text(render_food_markdown(slug, path=path))
    gear_path.write_text(render_gear_markdown(slug, path=path))
    _record_snapshotted(slug, "food", path=path)
    _record_snapshotted(slug, "gear", path=path)
    if run_build_trip:
        from app.config import REPO_ROOT
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "build_trip.py"), str(trip_dir)],
            check=True,
        )
    return {"food": str(food_path), "gear": str(gear_path)}
```

Extend `app/routes/trips.py` (use the existing router). Add at the top:

```python
from pydantic import BaseModel
from app.config import TRIPS_DIR
from app.services import auth, broadcast, snapshot as snapshot_svc
from app.services.identity import current_user


class SnapshotReq(BaseModel):
    run_build_trip: bool = True
```

Add the endpoint:

```python
@router.post("/api/trips/{slug}/snapshot")
async def snapshot_to_disk(slug: str, body: SnapshotReq, request):
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "not signed in")
    if not auth.is_trip_member(slug, user["email"]):
        raise HTTPException(403, "not a member of this trip")
    trip_dir = TRIPS_DIR / slug
    paths = snapshot_svc.write_snapshot(
        slug, trip_dir, run_build_trip=body.run_build_trip,
    )
    await broadcast.default_bus.publish(slug, {
        "type": "snapshot.saved",
        "by": user["email"],
        "at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
    })
    return {"ok": True, "paths": paths}
```

(Adjust import style to match the existing file's conventions — the snippet above uses absolute imports for clarity; if `app/routes/trips.py` already imports `Request` and `HTTPException`, reuse those.)

- [ ] **Step 4: Run, expect PASS**

```
python3 -m pytest tests/test_snapshot.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/services/snapshot.py app/routes/trips.py tests/test_snapshot.py
git commit -m "feat(snapshot): /api/trips/<slug>/snapshot endpoint + build_trip invoke"
```

---

### Task 15: `pull-snapshot.sh` helper + `/healthz`

**Files:**
- Create: `scripts/pull-snapshot.sh`, `app/routes/health.py`
- Modify: `app/main.py`
- Test: `tests/test_health.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""Healthz endpoint."""

from fastapi.testclient import TestClient
from app.main import app


def test_healthz_returns_ok():
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement `app/routes/health.py`**

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"ok": True}
```

Register in `app/main.py`:

```python
from app.routes import auth, checklist, food, gear, health, identity, pages, parks, sse, trips
...
app.include_router(health.router)
```

Create `scripts/pull-snapshot.sh`:

```bash
#!/usr/bin/env bash
# Pull a trip's snapshot files from the Fly machine back to the local repo.
# Usage: scripts/pull-snapshot.sh <slug>
set -euo pipefail

slug="${1:?usage: pull-snapshot.sh <slug>}"
app="${FLY_APP:-camping-planner}"

echo "Pulling /data/trips/${slug}/ from app=${app}…"
fly ssh sftp get -a "${app}" "/data/trips/${slug}/food.md" "trips/${slug}/food.md"
fly ssh sftp get -a "${app}" "/data/trips/${slug}/gear.md" "trips/${slug}/gear.md"
fly ssh sftp get -a "${app}" "/data/trips/${slug}/trip.html" "trips/${slug}/trip.html"
echo "Done. Review with: git diff trips/${slug}/"
```

`chmod +x scripts/pull-snapshot.sh`.

- [ ] **Step 4: Run all tests, expect PASS**

```
python3 -m pytest tests/ -q
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull-snapshot.sh app/routes/health.py app/main.py tests/test_health.py
git commit -m "feat: /healthz + pull-snapshot.sh helper for fly→local"
```

---

## Wrap-up

After Task 15 lands, Phase 1 is complete:

- `python3 -m pytest tests/ -q` is green (existing 140 + ~30 new tests).
- The backend supports magic-link login, structured food + gear editing with conflict detection, SSE broadcast of edits + presence, and one-shot snapshot back to markdown.
- The app still runs locally via `uvicorn app.main:app --port 8000`. You can drive it end-to-end with `curl` to verify before building the UI.

**Smoke-test sequence (manual):**

1. `python3 -m uvicorn app.main:app --port 8000`
2. `curl -X POST localhost:8000/login -d email=alex@example.com` — link printed in server logs since no real mail transport is wired locally (you can monkey-patch `mailer.default_transport` to print).
3. Click the link → cookie set.
4. `curl --cookie-jar j -b j -X POST localhost:8000/api/trips/killarney-2026-05/food -H 'content-type: application/json' -d '{"day_index":1,"meal":"dinner","item":"Pasta","sort_order":1.0}'`
5. In another terminal: `curl --cookie j localhost:8000/trips/killarney-2026-05/events` — you should see the event stream and the upsert event.
6. `curl --cookie j -X POST localhost:8000/api/trips/killarney-2026-05/snapshot -d '{"run_build_trip":false}' -H content-type:application/json` — check `trips/killarney-2026-05/food.md` updated.

Once verified, ready for **Plan 2: Frontend + deploy**.

---

## Self-review checklist

- **Spec coverage:** ✓ auth, structured tables, conflict detection, SSE broadcast, presence, snapshot service, build_trip invocation, pull-back script, healthz. Out-of-scope-this-plan items (UI, Dockerfile, fly.toml, seed-script-as-Fly-task, font, CSS) are deferred to Plan 2 with that explicitly stated.
- **Placeholders:** none — every code block is concrete.
- **Type/name consistency:** `food_repo.Conflict.current`, `expected_updated_at`, `cp_session` cookie, `broadcast.default_bus` referenced consistently across tasks.
- **Granularity:** 15 tasks, each one TDD cycle of test→fail→impl→pass→commit, ~5 steps per task.
- **Backward-compat:** existing 140 tests must stay green; Tasks 1–2 explicitly verify.
