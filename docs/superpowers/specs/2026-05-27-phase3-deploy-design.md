# Phase 3 — Deploy to Render (free) — Design

**Date:** 2026-05-27
**Branch:** local/water-polygon-union
**Status:** Approved (design)

## Context

Phase 3 of the hosting transition (Phase 1 = stateless storage; Phase 2 =
Supabase auth; both done + pushed). The app is now stateless (all writes go to
Supabase Postgres; caches in-memory; read-only assets bundled), so it can run as
a long-lived `uvicorn` container on any host. This phase deploys it to **Render
(free tier)**, **private from launch** (magic-link auth on), and finishes the
Phase-2 live-auth wiring against the deployed domain.

Key facts confirmed during exploration:
- `import app.main` triggers **no** heavy-dependency imports.
- `ontario_parks` imports `playwright` **lazily** inside the availability
  fallback (graceful "not installed" handling) — so a slim image needs **no code
  change**; the requests-based availability path still works, the playwright
  fallback simply degrades.
- `opencv-python`, `pytesseract`, `pillow` are used only by offline data-prep
  scripts (`jeffs_extractor`, `jeffs_paths_extractor`), never the request path.
- No Dockerfile / health-check / deploy config exists yet.

## Decisions (from brainstorming)

- **Host:** Render free tier (native Python build, not Docker). Accept the
  ~30–60s cold start after ~15 min idle.
- **Auth:** private from launch — `AUTH_ENABLED=true`, magic-link, invite-only.
- **Pooler:** session pooler (long-lived container) — same connection string we
  tested locally; no transaction-pooler / prepared-statement changes.
- **Deps:** slim runtime requirements; drop the offline-only heavy deps.

## Design

### 1. Slim runtime dependencies — `requirements-runtime.txt` (new)

```
fastapi>=0.110
uvicorn[standard]>=0.27
jinja2>=3.1
python-multipart>=0.0.9
httpx>=0.27
psycopg[binary]>=3.1
psycopg_pool>=3.2
pyjwt>=2.8
markdown==3.7
pyyaml==6.0.2
requests>=2.31.0
```

Drops `playwright`, `opencv-python`, `pytesseract`, `pillow`, `pytest` (none are
imported by the running app; the playwright availability fallback is already
lazy and returns a graceful "not installed" result on the host). `requirements.txt`
stays the full dev/test set unchanged.

### 2. `/healthz` endpoint (only new code)

A public `GET /healthz` returning `200 {"status": "ok"}`, **exempt from
`require_user`** (Render's health checker is unauthenticated). Added in
`app/main.py` (a plain route, no auth dependency).

### 3. `render.yaml` (Blueprint, native Python)

```yaml
services:
  - type: web
    name: camping-planner
    runtime: python
    plan: free
    buildCommand: pip install -r requirements-runtime.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /healthz
    envVars:
      - { key: STORAGE_BACKEND, value: postgres }
      - { key: AUTH_ENABLED,    value: "true" }
      - { key: COOKIE_SECURE,   value: "1" }
      - { key: PYTHON_VERSION,  value: "3.12.7" }
      - { key: DATABASE_URL,        sync: false }
      - { key: SUPABASE_URL,        sync: false }
      - { key: SUPABASE_ANON_KEY,   sync: false }
      - { key: SUPABASE_JWT_SECRET, sync: false }
```

`sync: false` vars are set as secrets in the Render dashboard (never committed).
`DATABASE_URL` is the Supabase **session-pooler** URL. The app binds `$PORT`
(Render-assigned).

### 4. Supabase Auth — live wiring (dashboard; user-performed, guided)

- Auth → Providers → **Email**: enabled, **magic link on**.
- **Disable public sign-ups** (invite-only); **Invite** the owner's email.
- **Site URL + Redirect URLs**: add the deployed `https://<service>.onrender.com`
  and `…/auth/callback`.
- Secrets into Render env: `SUPABASE_URL`, `SUPABASE_ANON_KEY` (Settings → API),
  `SUPABASE_JWT_SECRET` (Settings → API → JWT secret), `DATABASE_URL`
  (session pooler).

### 5. Deploy flow (ordering resolves the domain chicken-and-egg)

1. Commit `requirements-runtime.txt`, `render.yaml`, the `/healthz` route; push.
2. Render → New → **Blueprint** → connect the GitHub repo → it reads
   `render.yaml` → fill the 4 secret env vars → Deploy.
3. First deploy yields `https://<service>.onrender.com`. Add that
   (+`/auth/callback`) to Supabase Redirect URLs; restart/redeploy if needed so
   magic-link redirects resolve.

### 6. Verification

- `curl https://<app>.onrender.com/healthz` → `200`.
- `GET /` anonymous → `302 /login` (private ✓).
- Magic-link round-trip: owner enters email → clicks the emailed link →
  `/auth/callback` exchanges it → lands authenticated → trips load from Supabase.
  (Owner performs the email click; verify healthz, the login redirect, and
  post-login trip load.)

## Testing

- New `tests/test_healthz.py`: `GET /healthz` → 200 `{"status":"ok"}` and is
  reachable **without** login even when `AUTH_ENABLED=True` (not behind the gate).
- `render.yaml` / `requirements-runtime.txt` are deploy config (not unit-tested),
  but confirm `python3 -c "import app.main"` succeeds and that the runtime
  requirements cover every import in the request path. Full suite stays green
  (filesystem/AUTH-off defaults unchanged).

## Non-goals

- No paid/always-on tier (accept cold start); no custom domain, CDN, or
  autoscaling.
- No Docker (native Render build); a Dockerfile can be added later for portability.
- No CI beyond Render's git-push auto-deploy.
- No change to Phase 1/2 code beyond adding `/healthz`.
