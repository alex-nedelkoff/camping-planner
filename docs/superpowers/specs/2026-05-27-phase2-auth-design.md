# Phase 2 — Supabase Auth + Per-Person Checklists — Design

**Date:** 2026-05-27
**Branch:** local/water-polygon-union
**Status:** Approved (design)

## Context

Phase 2 of the hosting transition (Phase 1 = stateless storage, done; Phase 3 =
deploy). Today identity is a no-password `cp_user` cookie holding a free-text
name (`app/services/identity.py`), used to scope per-person checklists and a nav
"user pill". This replaces that with real **Supabase Auth** accounts so the app
can be shared with friends, and keys per-person checklists to the authenticated
user. The app is server-rendered (Jinja + minimal JS), so FastAPI owns an
HttpOnly session cookie and mediates Supabase Auth — no SPA/JS auth.

## Decisions (from brainstorming)

- **Login:** magic link (passwordless email).
- **Signup:** invite-only (public signup disabled in Supabase; friends invited).
- **Edit model — field-level:** any logged-in friend may edit *planning lists*
  (gear, food, costs, itinerary), *participants*, and *route/waypoints*. The
  trip **owner** (creator) may edit everything; **owner-only** = trip core
  (name, park, dates, nights/site, mode) and trip deletion.
- **View access:** fully private — login required to view anything.
- **Migrated trips:** no owner → communal (any logged-in user edits fully) until
  optionally claimed; new trips get a real owner.
- **Per-person checklists:** keyed by Supabase user id.
- **Session:** FastAPI HttpOnly cookies; tokens from Supabase GoTrue; access JWT
  verified locally.

## Design

### 1. Auth flow (magic link, server-side) — `app/services/auth.py`, `app/routes/auth.py`

- `GET /login` — email entry form.
- `POST /login` — calls GoTrue `POST /auth/v1/otp` (`{email, options:{email_redirect_to: <app>/auth/callback}}`) to email a magic link; renders a "check your email" page.
- `GET /auth/callback` — the link carries `token_hash` + `type`; FastAPI calls
  GoTrue `POST /auth/v1/verify` (`{type, token_hash}`) to exchange it for a
  session (`access_token` JWT, `refresh_token`, user). Sets both tokens as
  **HttpOnly, Secure, SameSite=Lax** cookies; redirects to `/`.
- `POST /logout` — clears the cookies (and best-effort GoTrue logout).

Uses existing **httpx** for GoTrue REST + adds **pyjwt** for local token verify.

### 2. Session & identity — rewrite `app/services/identity.py`

`current_user(request) -> User | None`:
- Reads the access-token cookie; verifies the JWT locally (HS256 using
  `SUPABASE_JWT_SECRET`); on success returns `User(id=<sub>, email=<email>)`.
- On expiry, refreshes via GoTrue `POST /auth/v1/token?grant_type=refresh_token`
  using the refresh-token cookie, re-sets cookies, returns the user; if refresh
  fails, returns `None` (logged out).
- `User` is a small dataclass/Pydantic model (`id: str`, `email: str`).

(If the project signs tokens asymmetrically rather than with the shared JWT
secret, swap local HS256 verify for JWKS fetched from
`/auth/v1/.well-known/jwks.json` — confirmed at build time; interface unchanged.)

`AUTH_ENABLED` (config, default **False** for local/tests): when off,
`current_user` returns a synthetic local user (`id="local"`, `email="local"`)
with full access and the auth routes are inert — preserving today's behavior and
keeping the existing suite green without logging in.

### 3. Access control — `app/services/authz.py` + route guards

- **`require_user` dependency:** yields the `User` or, when anonymous + auth on,
  redirects pages to `/login` (302) and returns **401** for `/api/*`.
- **`owner_id`** added to the `Trip` model + `trips` table (Supabase user UUID,
  nullable). `create_trip_v2` sets it to the creating user. Null = communal.
- **`require_owner(trip, user)`** → 403 unless `user.id == trip.owner_id` or
  `trip.owner_id is None` (communal/migrated).
- Route gating:
  - **Any logged-in user:** `PUT /api/trips/{slug}/section/{name}` for
    gear/food/costs/itinerary; `PUT /api/trips/{slug}/routes`; and the
    *participants* portion of `PATCH /api/trips/{slug}/meta`.
  - **Owner only:** the trip-core fields of `PATCH /meta` (name/park/dates/
    nights/mode/access_point) and `DELETE /api/trips/{slug}`. `/meta` is gated
    field-by-field — a body touching only `participants` is allowed for any
    user; any other field requires owner.
  - **Read (all GET pages/APIs):** require login (fully private).

### 4. Per-person checklists

`checklist_load/checklist_set` continue to take a `user` arg, now passed
`current_user.id` instead of the cookie name. `checklist.py` routes use the
authenticated user id. Existing rows (name-keyed / `''`) remain as harmless
legacy; new toggles key to the uid.

### 5. Identity UI — `nav_band.html`

Replace the free-text user pill: logged-out → **Log in** link; logged-in → the
user's **email** + **Log out**. Remove `/api/whoami` and the set/clear-name
routes + their JS.

### 6. Supabase config (dashboard, no code) — documented in spec

Auth → Providers: enable **Email**, turn **on** "magic link", turn **off**
"Enable sign-ups" (invite-only); add friends via **Invite user** / allowlist;
set the **Site URL** + **Redirect URLs** to include `<app>/auth/callback`.

### 7. Config & secrets — `app/config.py`

Add (env): `AUTH_ENABLED` (bool, default False), `SUPABASE_URL`,
`SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`. Secrets handled like `DATABASE_URL`
(env / gitignored local file; never committed).

## Data flow

```
Browser → GET /login → POST /login → GoTrue /otp (email sent)
   click link → GET /auth/callback?token_hash&type → GoTrue /verify
   → set HttpOnly access+refresh cookies → redirect /
Every request → current_user(): verify access JWT (refresh if expired) → User|None
   page/API guarded by require_user; writes guarded by field-level authz +
   require_owner for trip-core/delete; checklist keyed by User.id
```

## Testing (offline; Supabase never hit)

- `AUTH_ENABLED=False` keeps the existing suite green (synthetic local user, full
  access) — no login needed.
- New tests (auth on, GoTrue + JWT verification mocked / a fake `current_user`
  injected):
  - anonymous → page redirect to `/login`; `/api/*` → 401.
  - logged-in non-owner: can `PUT` gear/food/costs/itinerary, edit participants,
    `PUT` routes; **blocked (403)** on core-meta changes + `DELETE`.
  - owner: allowed on everything incl. delete.
  - communal (owner_id None): any logged-in user edits fully.
  - checklist keyed by `User.id` (two users → independent state).
  - `auth.py`: callback exchanges token_hash→session (GoTrue mocked); logout
    clears cookies; expired access token triggers refresh (mocked).

## Non-goals

- No roles beyond owner/friend; no teams/orgs; no profiles.
- No password or OAuth login (magic link only).
- No changes to Phase 1 storage or read-only assets.
- No deploy/hosting (Phase 3).
