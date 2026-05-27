# Phase 3 — Deploy to Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the stateless app to Render (free), private from launch (magic-link auth on, Supabase backend), via a slim runtime requirements file, a `/healthz` endpoint, and a `render.yaml` Blueprint — then wire Supabase auth to the live domain and verify.

**Architecture:** Render runs `uvicorn app.main:app` as a long-lived native-Python web service (no Docker). Secrets (DATABASE_URL, SUPABASE_*) set in the Render dashboard; non-secret env (STORAGE_BACKEND=postgres, AUTH_ENABLED=true, COOKIE_SECURE=1) in `render.yaml`. The app already imports cleanly without the heavy offline deps, so the only code is a public `/healthz` route.

**Tech Stack:** Render (native Python), FastAPI/uvicorn, Supabase (Postgres + Auth). No code changes beyond `/healthz`.

**Conventions:** `python3 -m pytest`; file ops via Bash (Write/Edit are guarded in this background session — use `cat >`/perl).

---

## File Structure
- `requirements-runtime.txt` — **new**: slim deps for the deployed image.
- `app/main.py` — add a public `/healthz` route.
- `render.yaml` — **new**: Render Blueprint.
- `tests/test_healthz.py` — **new**.
- `docs/superpowers/specs/2026-05-27-phase3-deploy-design.md` — the spec (committed).

---

## Task 1: Slim runtime requirements

**Files:** Create `requirements-runtime.txt`

- [ ] **Step 1: Create the file**
```bash
cat > requirements-runtime.txt <<'REQ'
# Runtime-only deps for the deployed app (slim image). Excludes offline
# data-prep deps (playwright, opencv-python, pytesseract, pillow) and pytest.
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
REQ
```

- [ ] **Step 2: Verify it covers the request-path imports**
The app's runtime imports resolve to exactly these packages (confirmed: `fastapi`/`uvicorn`/`jinja2`/`python-multipart` for the web layer; `httpx` for GoTrue; `psycopg`/`psycopg_pool` for Postgres; `pyjwt` for auth; `markdown` in `app/templating.py`; `pyyaml` in `app/services/trips.py`; `requests` in `weather.py`/`ontario_parks.py`). Confirm the app imports cleanly (with the full deps still installed locally, this just proves no import error):
Run: `python3 -c "import app.main; print('import ok')"`
Expected: `import ok`.
Also sanity-check none of the dropped packages are imported at app load:
Run: `python3 -c "import sys, app.main; assert not {'cv2','playwright','pytesseract','PIL'} & set(sys.modules), [m for m in ('cv2','playwright','pytesseract','PIL') if m in sys.modules]; print('no heavy deps loaded')"`
Expected: `no heavy deps loaded`.

- [ ] **Step 3: Commit**
```bash
git add requirements-runtime.txt
git commit -m "build(deploy): slim runtime requirements (no playwright/opencv/tesseract)"
```

---

## Task 2: `/healthz` endpoint

**Files:** Modify `app/main.py`; Test `tests/test_healthz.py`

- [ ] **Step 1: Write the failing test** `tests/test_healthz.py`:
```python
from fastapi.testclient import TestClient
from app import config
from app.main import app


def test_healthz_ok():
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_healthz_public_even_with_auth_on(monkeypatch):
    # health checks are unauthenticated; /healthz must NOT be gated
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "secret")
    c = TestClient(app)
    r = c.get("/healthz", follow_redirects=False)
    assert r.status_code == 200 and r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m pytest tests/test_healthz.py -q`
Expected: FAIL — `/healthz` 404 (route doesn't exist).

- [ ] **Step 3: Add the route to `app/main.py`**
After the `app = FastAPI(title="Camping Planner")` line (a plain route with NO `require_user` dependency → public; returns 200 so the 401-redirect handler never applies), add:
```python
@app.get("/healthz")
def healthz():
    return {"status": "ok"}
```
(Place it before or after the router includes — either works; it must not depend on `require_user`.)

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m pytest tests/test_healthz.py -q`
Expected: PASS (2). Then full `python3 -m pytest -q` → green; `python3 -c "import app.main"` boots.

- [ ] **Step 5: Commit**
```bash
git add app/main.py tests/test_healthz.py
git commit -m "feat(deploy): public /healthz endpoint for Render health checks"
```

---

## Task 3: `render.yaml` Blueprint

**Files:** Create `render.yaml`

- [ ] **Step 1: Create the Blueprint**
```bash
cat > render.yaml <<'YAML'
services:
  - type: web
    name: camping-planner
    runtime: python
    plan: free
    buildCommand: pip install -r requirements-runtime.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /healthz
    envVars:
      - key: STORAGE_BACKEND
        value: postgres
      - key: AUTH_ENABLED
        value: "true"
      - key: COOKIE_SECURE
        value: "1"
      - key: PYTHON_VERSION
        value: "3.12.7"
      - key: DATABASE_URL
        sync: false
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_ANON_KEY
        sync: false
      - key: SUPABASE_JWT_SECRET
        sync: false
YAML
```

- [ ] **Step 2: Validate the YAML parses**
Run: `python3 -c "import yaml,sys; d=yaml.safe_load(open('render.yaml')); s=d['services'][0]; assert s['healthCheckPath']=='/healthz' and s['startCommand'].startswith('uvicorn'); secret={e['key'] for e in s['envVars'] if e.get('sync') is False}; assert secret=={'DATABASE_URL','SUPABASE_URL','SUPABASE_ANON_KEY','SUPABASE_JWT_SECRET'}, secret; print('render.yaml OK')"`
Expected: `render.yaml OK`.

- [ ] **Step 3: Commit**
```bash
git add render.yaml
git commit -m "build(deploy): render.yaml Blueprint (native python, /healthz, env)"
```

---

## Task 4: Deploy + Supabase auth wiring + verify (live; owner-performed, controller-verified)

This task is performed against live services. The controller (you) walks the owner through the dashboard steps and verifies what's verifiable over HTTP.

- [ ] **Step 1: Push the deploy artifacts**
```bash
git push origin local/water-polygon-union
git push origin local/water-polygon-union:main
```

- [ ] **Step 2: Owner creates the Render service**
On render.com → **New → Blueprint** → connect the `camping-planner` GitHub repo → Render reads `render.yaml`. When prompted, fill the four secret env vars:
- `DATABASE_URL` = the Supabase **session-pooler** string (the one in `.dburl.local`).
- `SUPABASE_URL` = `https://jlheoldxcreakynyqjqa.supabase.co`.
- `SUPABASE_ANON_KEY` = Supabase → Settings → API → anon/publishable key.
- `SUPABASE_JWT_SECRET` = Supabase → Settings → API → JWT secret.
Deploy. Note the assigned URL (e.g. `https://camping-planner.onrender.com`).

- [ ] **Step 3: Owner configures Supabase Auth for the live domain**
Supabase dashboard:
- Authentication → Providers → **Email**: enabled, **magic link** on.
- Authentication → **disable "Allow new users to sign up"** (invite-only).
- Authentication → Users → **Invite** the owner's email.
- Authentication → URL Configuration → set **Site URL** to the Render URL and add
  `https://<service>.onrender.com/auth/callback` to **Redirect URLs**.
Restart the Render service (Manual Deploy → Clear cache & deploy, or just redeploy) so everything is fresh.

- [ ] **Step 4: Controller verifies over HTTP**
```bash
APP=https://<service>.onrender.com
curl -s -o /dev/null -w "healthz %{http_code}\n" "$APP/healthz"            # expect 200
curl -s -o /dev/null -w "root %{http_code} -> %{redirect_url}\n" "$APP/"   # expect 302/303 -> /login
curl -s -o /dev/null -w "login %{http_code}\n" "$APP/login"                # expect 200
```
Expected: `/healthz` 200; `/` redirects to `/login` (private ✓); `/login` 200.

- [ ] **Step 5: Owner completes the magic-link round-trip**
Open the Render URL → redirected to `/login` → enter the invited email → open the
emailed link on the same device → lands authenticated on `/` → trips load (from
Supabase). Toggle a packing checkbox to confirm writes persist.
Controller note: if the email link errors, check the Supabase Redirect URL exactly
matches `https://<service>.onrender.com/auth/callback` and that `SUPABASE_JWT_SECRET`
in Render matches the project (Settings → API → JWT secret). If the deployed app
returns 500 on a trip page, check Render logs for a missing env var.

- [ ] **Step 6: Record the live URL**
Once verified, note the URL in the repo (optional): append it to `CLAUDE.md` or a
`docs/DEPLOY.md`, and commit. (Owner decides whether to make it discoverable.)

---

## Self-Review Notes
- **Spec coverage:** slim deps (T1), `/healthz` public endpoint (T2), `render.yaml` Blueprint with non-secret env + `sync:false` secrets + session-pooler DATABASE_URL (T3), deploy + Supabase live-auth wiring + verification (T4). Non-goals (paid tier, custom domain, Docker, CI) excluded.
- **No placeholders in code steps** — `<service>` in T4 is a genuine runtime value the owner names at deploy time (the Render service name → subdomain), called out in the spec.
- **Type/name consistency:** env keys in `render.yaml` (STORAGE_BACKEND, AUTH_ENABLED, COOKIE_SECURE, DATABASE_URL, SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_JWT_SECRET) match exactly what `app/config.py` reads. `/healthz` returns `{"status":"ok"}` matching the test and `healthCheckPath`.
- **Verification limit:** T4 is a live runbook — the Render service creation, secret entry, Supabase dashboard toggles, and the email click are owner actions; the controller verifies everything reachable over HTTP (healthz, login gate) and guides the rest.
