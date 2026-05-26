# Car-Camping Trip Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class `car_camping` trip mode so `/trip/{slug}` swaps the canoe Route section for a "Getting There & Your Site" section (drive-from-home, booked-site card from the Campsite Search survey, official campground-map link), while leaving canoe trips untouched.

**Architecture:** One `mode` field on the `Trip` model (default `"paddle"`) drives a branch in `trip_pages.py`. Car-camping context is assembled by a new testable service `app/services/getting_there.py` from existing data (`parks.json`, `weather.PARK_COORDS`, the site survey). The booked-site card markup is extracted into a shared partial reused by both the `/sites/{slug}` grid and the trip page.

**Tech Stack:** FastAPI, Jinja2, Pydantic v2, vanilla JS. Tests via `python3 -m pytest` with FastAPI `TestClient`. Camis API always mocked.

---

## File Structure

- `app/models_trip.py` — add `Trip.mode` field.
- `app/services/site_surveys.py` — add `find_site(survey, name)`.
- `app/services/getting_there.py` — **new**: assemble car-camping section context.
- `app/services/parks.py` — unchanged code; `parks.json` gains `campgroundMapUrl`.
- `app/routes/trip_pages.py` — branch on `trip.mode`; pass `getting_there` context.
- `app/templates/partials/site_card.html` — **new**: shared single-site card.
- `app/templates/sites_park.html` — use the shared partial; add per-site anchors.
- `app/templates/partials/section_getting_there.html` — **new**: car-camping section.
- `app/templates/trip.html` — conditional section include + CSS/JS for car mode.
- `app/templates/partials/trip_sidenav.html` — conditional first nav item.
- `app/models.py` — `CreateTripRequest.mode`.
- `app/services/trips.py` — `create_trip_v2(..., mode=...)`.
- `app/routes/trips.py` — pass `mode` through.
- `app/templates/index.html` + `app/static/js/index.js` — mode selector in New Trip form.
- `trips/balsam-lake-2026-05/trip.json` — **new**: the actual trip (final task).

---

## Task 1: Add `mode` to the Trip model

**Files:**
- Modify: `app/models_trip.py`
- Test: `tests/test_trip_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trip_mode.py
from app.models_trip import Trip, TripDates


def _base(**kw):
    data = dict(schema_version=1, name="t", park="balsam-lake",
                dates=TripDates(start="2026-05-30", end="2026-05-31"))
    data.update(kw)
    return Trip(**data)


def test_mode_defaults_to_paddle():
    assert _base().mode == "paddle"


def test_mode_accepts_car_camping():
    assert _base(mode="car_camping").mode == "car_camping"


def test_mode_rejects_unknown():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _base(mode="spaceship")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_trip_mode.py -q`
Expected: FAIL — `Trip` has no field `mode` (extra fields ignored → `mode` attribute missing → AttributeError/assertion fail).

- [ ] **Step 3: Add the field**

In `app/models_trip.py`, inside `class Trip`, add after the `park: str` line:

```python
    mode: Literal["paddle", "car_camping"] = "paddle"
```

(`Literal` is already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_trip_mode.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/models_trip.py tests/test_trip_mode.py
git commit -m "feat(trip): add mode field (paddle|car_camping), default paddle"
```

---

## Task 2: `find_site` survey lookup helper

**Files:**
- Modify: `app/services/site_surveys.py`
- Test: `tests/test_find_site.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_find_site.py
from app.services.site_surveys import find_site

SURVEY = {"sites": [
    {"name": "123", "campground": "A"},
    {"name": "Site 7", "campground": "B"},
]}


def test_exact_number():
    assert find_site(SURVEY, "123")["campground"] == "A"


def test_with_site_prefix_and_case():
    assert find_site(SURVEY, "site 123")["campground"] == "A"
    assert find_site(SURVEY, "  7 ")["campground"] == "B"
    assert find_site(SURVEY, "SITE 7")["campground"] == "B"


def test_blank_or_missing_returns_none():
    assert find_site(SURVEY, "") is None
    assert find_site(SURVEY, "999") is None
    assert find_site(None, "123") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_find_site.py -q`
Expected: FAIL — `ImportError: cannot import name 'find_site'`.

- [ ] **Step 3: Implement the helper**

Append to `app/services/site_surveys.py`:

```python
def _norm_site(name: str) -> str:
    """Normalize a site label for matching: lowercase, drop a leading
    'site' word, collapse whitespace. 'Site 123' / '123' / ' 7 ' → '123'/'7'."""
    s = (name or "").strip().lower()
    if s.startswith("site"):
        s = s[len("site"):].strip()
    return " ".join(s.split())


def find_site(survey: dict | None, name: str) -> dict | None:
    """Return the survey site whose name matches `name` (tolerant of a
    'Site ' prefix, case, and surrounding whitespace), or None."""
    if not survey or not (name or "").strip():
        return None
    target = _norm_site(name)
    for s in survey.get("sites", []):
        if _norm_site(s.get("name", "")) == target:
            return s
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_find_site.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/site_surveys.py tests/test_find_site.py
git commit -m "feat(sites): find_site() tolerant survey lookup by site name"
```

---

## Task 3: Add `campgroundMapUrl` to parks.json (Balsam)

**Files:**
- Modify: `parks.json`

- [ ] **Step 1: Source the official campground-map URL**

Find Balsam Lake's campground map on ontarioparks.com (the park page links a "Park map" / campground map PDF). Use:

Run: `python3 - <<'PY'`
```python
# Just a reminder of the WebFetch step — do this via the WebFetch tool, not python:
# WebFetch("https://www.ontarioparks.com/park/balsamlake", "Find the URL of the campground/park map PDF or image")
print("Use the WebFetch tool to fetch https://www.ontarioparks.com/park/balsamlake and extract the campground map URL")
PY
```

If a specific map URL is found, use it. **Fallback** if none is clearly identifiable: use the park page itself, `https://www.ontarioparks.com/park/balsamlake` (the section block degrades fine — it is just a link/embed).

- [ ] **Step 2: Add the field**

In `parks.json`, add to the `"balsam-lake"` object a `"campgroundMapUrl"` key with the sourced URL, e.g.:

```json
    "balsam-lake": {
      "name": "Balsam Lake",
      "resourceLocationId": -2147483638,
      "mapId": null,
      "driveFromAjax": "1.25 hrs",
      "campgroundMapUrl": "<sourced-url>"
    },
```

- [ ] **Step 3: Verify JSON still parses**

Run: `python3 -c "import json; d=json.load(open('parks.json')); print(d['parks']['balsam-lake']['campgroundMapUrl'])"`
Expected: prints the URL, no JSON error.

- [ ] **Step 4: Commit**

```bash
git add parks.json
git commit -m "data(parks): campgroundMapUrl for Balsam Lake"
```

---

## Task 4: `getting_there` context builder

**Files:**
- Create: `app/services/getting_there.py`
- Test: `tests/test_getting_there.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_getting_there.py
from app.services import getting_there as gt


def test_build_assembles_drive_site_and_map(monkeypatch):
    monkeypatch.setattr(gt.parks_svc, "load_park_info", lambda slug: {
        "name": "Balsam Lake", "driveFromAjax": "1.25 hrs",
        "campgroundMapUrl": "https://example.com/map.pdf",
    })
    monkeypatch.setattr(gt.site_surveys, "load_survey", lambda slug: {
        "park_slug": slug, "sites": [{"name": "123", "campground": "Maple"}],
    })
    monkeypatch.setattr(gt.weather, "PARK_COORDS", {"balsam-lake": (44.58, -78.85)})

    ctx = gt.build("balsam-lake", booked_site="Site 123")
    assert ctx["park_name"] == "Balsam Lake"
    assert ctx["drive_label"] == "1.25 hrs"
    assert ctx["map_url"] == "https://example.com/map.pdf"
    assert "44.58" in ctx["directions_url"] and "-78.85" in ctx["directions_url"]
    assert ctx["booked_site"]["campground"] == "Maple"


def test_build_degrades_when_no_data(monkeypatch):
    monkeypatch.setattr(gt.parks_svc, "load_park_info", lambda slug: {})
    monkeypatch.setattr(gt.site_surveys, "load_survey", lambda slug: None)
    monkeypatch.setattr(gt.weather, "PARK_COORDS", {})

    ctx = gt.build("unknown-park", booked_site="")
    assert ctx["booked_site"] is None
    assert ctx["drive_label"] is None
    assert ctx["map_url"] is None
    assert ctx["directions_url"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_getting_there.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.getting_there`.

- [ ] **Step 3: Implement the builder**

```python
# app/services/getting_there.py
"""Assemble the car-camping 'Getting There & Your Site' section context.

Pure read-only: combines parks.json, weather.PARK_COORDS, and the site survey.
Never raises for missing data — every field degrades to None so the template
can hide blocks individually.
"""
from __future__ import annotations

import weather
from app.services import parks as parks_svc
from app.services import site_surveys


def _directions_url(park_slug: str) -> str | None:
    coords = getattr(weather, "PARK_COORDS", {}).get(park_slug)
    if not coords:
        return None
    lat, lon = coords
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"


def build(park_slug: str, booked_site: str) -> dict:
    """Return template context for the getting-there section.

    Keys: park_name, drive_label, directions_url, map_url, booked_site.
    """
    info = parks_svc.load_park_info(park_slug) or {}
    survey = site_surveys.load_survey(park_slug)
    return {
        "park_name": info.get("name") or park_slug,
        "drive_label": info.get("driveFromAjax") or None,
        "directions_url": _directions_url(park_slug),
        "map_url": info.get("campgroundMapUrl") or None,
        "booked_site": site_surveys.find_site(survey, booked_site),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_getting_there.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/getting_there.py tests/test_getting_there.py
git commit -m "feat(car-camping): getting_there context builder"
```

---

## Task 5: Extract the shared site-card partial + per-site anchors

**Files:**
- Create: `app/templates/partials/site_card.html`
- Modify: `app/templates/sites_park.html`
- Test: `tests/test_sites_routes.py` (add one assertion)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sites_routes.py`:

```python
def test_site_cards_have_anchors(client):
    # client fixture already points SITE_SURVEYS_DIR at a fixture survey
    r = client.get("/sites/balsam-lake")
    assert r.status_code == 200
    # each card carries an id anchor for deep-linking from a trip page
    assert 'id="site-' in r.text
```

(If `tests/test_sites_routes.py` has no shared `client`/survey fixture, mirror
the existing setup already used by the other tests in that file — monkeypatch
`config.SITE_SURVEYS_DIR` and `site_surveys.SITE_SURVEYS_DIR` to a tmp dir
containing a small `balsam-lake.json`, exactly as the existing tests do.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sites_routes.py::test_site_cards_have_anchors -q`
Expected: FAIL — no `id="site-` in output.

- [ ] **Step 3: Create the shared partial**

```html
{# app/templates/partials/site_card.html — renders one survey site.
   Requires in context: `s` (site dict) and `key_attrs` (list[str]). #}
{% set length_num = s.attributes.get("Site Length (m)") %}
<div class="site"
     id="site-{{ (s.name or '') | lower | replace(' ', '-') }}"
     data-camp="{{ s.campground }}"
     data-priv="{{ s.attributes.get('Privacy') or '' }}"
     data-eq="{{ s.equipment_bucket }}"
     data-len="{{ length_num if length_num is not none else '' }}"
     data-photos="{{ s.photos | length }}"
     data-q="{{ (s.name ~ ' ' ~ s.description) | lower }}">
  {% if s.photos %}
  <div class="photos{% if s.photos|length == 1 %} single{% endif %}">
    {% for p in s.photos[:4] %}<img loading="lazy" src="{{ p }}" onclick="siteLightbox(this.src)">{% endfor %}
  </div>
  {% else %}
  <div class="photos empty">no photos</div>
  {% endif %}
  <div class="body">
    <h3>{{ s.name or '?' }}</h3>
    <div class="area">{{ s.campground }} · {{ s.equipment_bucket }}</div>
    <dl>
      {% for k in key_attrs %}
        {% set v = s.attributes.get(k) %}
        {% if v not in (none, '') %}<dt>{{ k }}</dt><dd>{{ v }}</dd>{% endif %}
      {% endfor %}
    </dl>
  </div>
</div>
```

- [ ] **Step 4: Replace the inline card in `sites_park.html`**

Replace the grid loop body (the `{% set length_num %}` line through the closing
`</div>` of `class="site"`, i.e. the old lines 62–87) with:

```html
  {% for s in sites %}
  {% include "partials/site_card.html" %}
  {% endfor %}
```

Leave the surrounding `<div class="grid" ...>`, the `{% else %}`/empty handling
if present, the lightbox div, and `{% endblock %}` intact.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sites_routes.py -q`
Expected: PASS (all existing site-route tests + the new anchor test).

- [ ] **Step 6: Commit**

```bash
git add app/templates/partials/site_card.html app/templates/sites_park.html tests/test_sites_routes.py
git commit -m "refactor(sites): extract shared site_card partial + per-site anchors"
```

---

## Task 6: Car-camping section + conditional rendering on the trip page

**Files:**
- Create: `app/templates/partials/section_getting_there.html`
- Modify: `app/routes/trip_pages.py`, `app/templates/trip.html`, `app/templates/partials/trip_sidenav.html`
- Test: `tests/test_trip_page_modes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trip_page_modes.py
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.services.trips as trips_svc
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _write_trip(tmp_path, monkeypatch, mode, site=""):
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_path)
    slug = "balsam-lake-2026-05"
    d = tmp_path / slug
    d.mkdir()
    trip = {
        "schema_version": 1, "name": slug, "park": "balsam-lake",
        "mode": mode,
        "dates": {"start": "2026-05-30", "end": "2026-05-31"},
        "participants": ["Alex"],
        "nights": [{"date": "2026-05-30", "site": site}],
        "itinerary": [], "gear": [], "food": [], "costs": [],
    }
    (d / "trip.json").write_text(json.dumps(trip))
    return slug


def test_car_camping_renders_getting_there_not_route(client, tmp_path, monkeypatch):
    slug = _write_trip(tmp_path, monkeypatch, mode="car_camping", site="123")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert 'data-section="getting-there"' in r.text
    assert 'data-section="route"' not in r.text


def test_paddle_still_renders_route(client, tmp_path, monkeypatch):
    slug = _write_trip(tmp_path, monkeypatch, mode="paddle")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert 'data-section="route"' in r.text
    assert 'data-section="getting-there"' not in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_trip_page_modes.py -q`
Expected: FAIL — both assert on `data-section="getting-there"` which does not exist yet.

- [ ] **Step 3: Branch in `trip_pages.py`**

In `app/routes/trip_pages.py`, replace the route-render block (lines 36–44) so
the paddle render only runs in paddle mode, and build the getting-there context
in car mode:

```python
    # Location section — branch on trip mode, both best-effort.
    route_render = {"html": "", "distance_km": 0, "empty": True}
    route_error = None
    getting_there = None
    if trip.mode == "car_camping":
        from app.services import getting_there as gt
        booked = trip.nights[0].site if trip.nights else ""
        try:
            getting_there = gt.build(trip.park, booked)
        except Exception as exc:  # never 500 the page
            getting_there = {"park_name": trip.park, "drive_label": None,
                             "directions_url": None, "map_url": None,
                             "booked_site": None, "error": str(exc)}
    else:
        from app.services import route_cache
        routes_path = trip_dir / "manual_routes.json"
        try:
            route_render = route_cache.get_route_render(routes_path, slug)
        except Exception as exc:
            route_error = str(exc)
```

Then add to the `TemplateResponse` context dict (after `"route_error": route_error,`):

```python
            "getting_there": getting_there,
```

- [ ] **Step 4: Create the section partial**

```html
{# app/templates/partials/section_getting_there.html #}
<section id="getting-there" class="trip-section" data-section="getting-there">
  <header class="section-header">
    <h2>Getting There &amp; Your Site</h2>
  </header>
  <div class="section-body getting-there">
    {% set g = getting_there %}
    <div class="gt-drive">
      <h3>Drive from home</h3>
      {% if g.drive_label %}<p class="gt-drive-time">{{ g.drive_label }} from Ajax</p>{% endif %}
      {% if g.directions_url %}<a class="btn btn-ghost" href="{{ g.directions_url }}" target="_blank" rel="noopener">Get directions ↗</a>{% endif %}
      {% if not g.drive_label and not g.directions_url %}<p class="empty">No drive info for this park yet.</p>{% endif %}
    </div>

    <div class="gt-site">
      <h3>Your booked site</h3>
      {% if g.booked_site %}
        {% set s = g.booked_site %}
        {% include "partials/site_card.html" %}
        <a class="btn btn-ghost gt-site-link"
           href="/sites/{{ trip.park }}#site-{{ (s.name or '') | lower | replace(' ', '-') }}">See full details →</a>
      {% else %}
        <p class="empty">No site selected yet — set the site number on your night, or <a href="/sites/{{ trip.park }}">browse Campsite Search</a>.</p>
      {% endif %}
    </div>

    {% if g.map_url %}
    <div class="gt-map">
      <h3>Campground map</h3>
      <a class="btn btn-ghost" href="{{ g.map_url }}" target="_blank" rel="noopener">Open official park map ↗</a>
    </div>
    {% endif %}
  </div>
</section>
```

Note: the partial needs `key_attrs` in context. Add it to the trip-page context
(Step 5) so the embedded card renders its attribute list.

- [ ] **Step 5: Wire `key_attrs` into the trip context**

In `app/routes/trip_pages.py`, import the shared list rather than redefining it.
Add near the top: `from app.routes.sites import KEY_ATTRS`. Then add to the
`TemplateResponse` context dict: `"key_attrs": KEY_ATTRS,`.

- [ ] **Step 6: Conditional includes in `trip.html`**

In `app/templates/trip.html`, replace line 13
(`{% include "partials/section_route.html" %}`) with:

```html
    {% if trip.mode == "car_camping" %}
    {% include "partials/section_getting_there.html" %}
    {% else %}
    {% include "partials/section_route.html" %}
    {% endif %}
```

And in `{% block head_extra %}` (after the trip.css link) add the survey
stylesheet so the embedded card is styled:

```html
<link rel="stylesheet" href="/static/css/sites.css?v={{ static_version }}">
```

And before `{% endblock %}` of `body`, after the `section_route.js` line, add
the lightbox helper so card photos open (only needed in car mode, but harmless
to always include):

```html
  <script src="/static/js/site_search.js?v={{ static_version }}"></script>
```

NOTE: confirm `site_search.js` defines `window.siteLightbox` at top level (it
does) and does not throw when the filter-bar elements are absent. If its
init code assumes `#grid`/filter inputs exist, guard the top of that file with
`if (!document.getElementById('grid')) { /* still expose siteLightbox */ }` —
keep `window.siteLightbox = ...` outside that guard. Verify in Step 8.

- [ ] **Step 7: Conditional sidenav item**

In `app/templates/partials/trip_sidenav.html`, replace the Route `<li>`:

```html
    {% if trip.mode == "car_camping" %}
    <li><a href="#getting-there">Getting There</a></li>
    {% else %}
    <li><a href="#route">Route</a></li>
    {% endif %}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_trip_page_modes.py tests/test_sites_routes.py -q`
Expected: PASS. Then run the full suite: `python3 -m pytest -q` — expected: all green (previous count + new tests).

- [ ] **Step 9: Commit**

```bash
git add app/routes/trip_pages.py app/templates/trip.html \
        app/templates/partials/section_getting_there.html \
        app/templates/partials/trip_sidenav.html tests/test_trip_page_modes.py
git commit -m "feat(car-camping): getting-there section + mode-based trip rendering"
```

---

## Task 7: Mode selector in the New Trip form

**Files:**
- Modify: `app/models.py`, `app/services/trips.py`, `app/routes/trips.py`, `app/templates/index.html`, `app/static/js/index.js`
- Test: `tests/test_create_trip_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_create_trip_mode.py
import json
import pytest
import app.services.trips as trips_svc


def test_create_trip_v2_persists_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_path)
    slug = trips_svc.create_trip_v2(
        park="balsam-lake", start_date="2026-05-30", end_date="2026-05-31",
        participants=["Alex"], mode="car_camping",
    )
    data = json.loads((tmp_path / slug / "trip.json").read_text())
    assert data["mode"] == "car_camping"


def test_create_trip_v2_defaults_paddle(tmp_path, monkeypatch):
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_path)
    slug = trips_svc.create_trip_v2(
        park="killarney", start_date="2026-07-01", end_date="2026-07-03",
        participants=[],
    )
    data = json.loads((tmp_path / slug / "trip.json").read_text())
    assert data["mode"] == "paddle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_create_trip_mode.py -q`
Expected: FAIL — `create_trip_v2() got an unexpected keyword argument 'mode'`.

- [ ] **Step 3: Thread `mode` through `create_trip_v2`**

In `app/services/trips.py`, change the signature and the `Trip(...)` call:

```python
def create_trip_v2(park: str, start_date, end_date, participants: list[str],
                   mode: str = "paddle") -> str:
```

and in the `Trip(...)` constructor add `mode=mode,`:

```python
    trip = Trip(
        schema_version=1, name=slug, park=park, mode=mode,
        dates=TripDates(start=sd, end=ed),
        participants=participants or [], access_point="",
    )
```

- [ ] **Step 4: Add `mode` to the request model + route**

In `app/models.py`, in `class CreateTripRequest`, add after `participants`:

```python
    mode: str = "paddle"
```

In `app/routes/trips.py`, pass it through in the `create_trip` handler:

```python
        slug = trips_svc.create_trip_v2(
            park=body.park, start_date=body.start, end_date=body.end,
            participants=body.participants, mode=body.mode,
        )
```

- [ ] **Step 5: Run the service test to verify it passes**

Run: `python3 -m pytest tests/test_create_trip_mode.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Add the selector to the form + JS**

In `app/templates/index.html`, inside the New Trip `<form>` (after the Park
`<label>…</label>` block, before the Start date label), add:

```html
    <label>Trip type
      <select name="mode">
        <option value="paddle">Paddle / canoe trip</option>
        <option value="car_camping">Car camping</option>
      </select>
    </label>
```

In `app/static/js/index.js`, add `mode` to the `body` object in `createTrip`:

```javascript
    mode: f.mode.value,
```

- [ ] **Step 7: Verify the POST round-trips mode (route test)**

Add to `tests/test_create_trip_mode.py`:

```python
def test_post_trips_accepts_mode(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_path)
    c = TestClient(app)
    r = c.post("/api/trips", json={
        "park": "balsam-lake", "start": "2026-05-30", "end": "2026-05-31",
        "participants": ["Alex"], "mode": "car_camping",
    })
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    data = json.loads((tmp_path / slug / "trip.json").read_text())
    assert data["mode"] == "car_camping"
```

Run: `python3 -m pytest tests/test_create_trip_mode.py -q`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add app/models.py app/services/trips.py app/routes/trips.py \
        app/templates/index.html app/static/js/index.js tests/test_create_trip_mode.py
git commit -m "feat(car-camping): trip-type selector in New Trip form"
```

---

## Task 8: Create the Balsam Lake trip + live smoke check

**Files:**
- Create: `trips/balsam-lake-2026-05/trip.json`

- [ ] **Step 1: Confirm the booked site number**

Ask the user (or use a placeholder they can edit): which site number did you
reserve at Balsam Lake? It must match a `name` in
`app/data/site_surveys/balsam-lake.json`. Verify:

Run: `python3 -c "import json; d=json.load(open('app/data/site_surveys/balsam-lake.json')); print([s['name'] for s in d['sites'] if s['name'] in ('<SITE>',)])"`
Expected: prints `['<SITE>']` (non-empty) — confirms the survey has that site.

- [ ] **Step 2: Create the trip via the running app (preferred)**

Start the app and use the New Trip form with Trip type = Car camping:

Run: `uvicorn app.main:app --reload --port 8000` then open `http://127.0.0.1:8000/`
→ + New Trip → Park: Balsam Lake, Trip type: Car camping, dates, participants → Create.

Then set the booked site: edit `trips/balsam-lake-2026-05/trip.json` so
`nights` contains one night with `"site": "<SITE>"` and the correct date. (Or
add it via the trip page's night/meta editor if available.)

- [ ] **Step 3: Live verification**

Open `http://127.0.0.1:8000/trip/balsam-lake-2026-05`. Confirm:
- The first section is **Getting There & Your Site** (not Route).
- Drive shows "1.25 hrs from Ajax" + a working Get directions link.
- The booked-site card shows photos + attributes for your site; clicking a
  photo opens the lightbox; "See full details →" jumps to the right card on
  `/sites/balsam-lake`.
- "Open official park map" link works.
- Sidenav first item reads "Getting There".

(Use Playwright MCP for an automated check; the Camis API is not called by this
page — survey data is local — so no rate-limit risk.)

- [ ] **Step 4: Full regression**

Run: `python3 -m pytest -q`
Expected: all tests pass. Spot-check an existing Killarney trip page still shows
the Route section.

- [ ] **Step 5: Commit**

```bash
git add trips/balsam-lake-2026-05/
git commit -m "trip(balsam-lake-2026-05): one-night car-camping trip"
```

---

## Self-Review Notes

- **Spec coverage:** mode field (T1), Route→Getting-There with drive/site/map
  (T4, T6), shared site_card reuse + anchors (T5), find_site matching (T2),
  sidenav adapt (T6), new-trip selector (T7), Balsam trip (T8), official map
  link + parks.json field (T3), graceful degradation (T4 test + T6 template).
  Testing requirements all map to T1/T2/T4/T6/T7. No gaps.
- **Deferred (per spec non-goals):** site-pinned map, paddle-path changes,
  trip-planning integration of survey data.
- **Type consistency:** `gt.build(park_slug, booked_site)` → dict keys
  `park_name/drive_label/directions_url/map_url/booked_site` used identically in
  test (T4) and template (T6). `find_site(survey, name)` signature matches T2 +
  T4 usage. `create_trip_v2(..., mode=)` matches T7 service + route + test.
  `KEY_ATTRS` imported from `app.routes.sites` (single source).
