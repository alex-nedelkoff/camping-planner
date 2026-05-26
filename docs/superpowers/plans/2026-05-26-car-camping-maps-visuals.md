# Car-Camping Maps & Visuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the car-camping trip page with a per-park background photo, a real OSM driving route from Ajax, two zoomable park-map images, and removal of the "FIELD JOURNAL · EXPEDITION LOG" stamp — all driven by a per-park asset convention.

**Architecture:** A new `park_assets` service discovers per-park images by slug convention (`static/img/parks/<slug>/`). `trip_pages.py` passes a hero-image URL (all trips) and a park-maps list (car mode). The car-camping section embeds a Leaflet route map (Leaflet Routing Machine + OSRM, client-side) and Leaflet `CRS.Simple` image viewers for true zoom/pan. Background photo is driven by a `--hero-image` CSS variable.

**Tech Stack:** FastAPI, Jinja2, Pydantic v2, Leaflet 1.9.4 + Leaflet Routing Machine 3.2.12 (CDN), vanilla JS. Tests via `python3 -m pytest`. Camis/survey mocked.

---

## File Structure

- `app/services/park_assets.py` — **new**: per-park image discovery (`hero_image`, `park_maps`). Filesystem-read, never raises.
- `app/config.py` — add `HOME_COORDS`, `HOME_LABEL` (Ajax drive origin).
- `app/services/getting_there.py` — add `home_coords`, `home_label`, `park_coords` to the context.
- `app/routes/trip_pages.py` — pass `hero_image` (all trips) + `park_maps` (context).
- `app/templates/trip.html` — set `--hero-image`; load Leaflet + LRM + `car_maps.js` for car mode.
- `app/templates/partials/section_getting_there.html` — route-map container in drive block; maps block.
- `app/static/css/trip.css` — drop journal stamp; `var(--hero-image)`; route/zoom-map layout.
- `app/static/js/car_maps.js` — **new**: route map + zoomable image viewers.
- `app/static/img/parks/balsam-lake/{campground-map.png,park-map.png,hero.jpg}` — **new** assets.

---

## Task 1: `park_assets` service

**Files:**
- Create: `app/services/park_assets.py`
- Test: `tests/test_park_assets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_park_assets.py
import app.services.park_assets as pa


def _mkparkdir(tmp_path, slug, files):
    d = tmp_path / slug
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_bytes(b"\x89PNG\r\n")  # dummy content; only presence matters
    return d


def test_hero_image_per_park(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path)
    _mkparkdir(tmp_path, "balsam-lake", ["hero.jpg"])
    assert pa.hero_image("balsam-lake") == "/static/img/parks/balsam-lake/hero.jpg"


def test_hero_image_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path)
    assert pa.hero_image("no-such-park") == pa.DEFAULT_HERO


def test_park_maps_lists_existing_campground_first(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path)
    _mkparkdir(tmp_path, "balsam-lake", ["park-map.png", "campground-map.png"])
    maps = pa.park_maps("balsam-lake")
    assert [m["title"] for m in maps] == ["Campground map", "Park map"]
    assert maps[0]["url"] == "/static/img/parks/balsam-lake/campground-map.png"


def test_park_maps_empty_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path)
    assert pa.park_maps("no-such-park") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_park_assets.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.park_assets`.

- [ ] **Step 3: Implement the service**

```python
# app/services/park_assets.py
"""Per-park image assets, discovered by slug convention.

Layout:  app/static/img/parks/<slug>/{hero.*, campground-map.*, park-map.*}
Pure filesystem reads; never raises. Adding a park = drop files in its dir.
"""
from __future__ import annotations

from app.config import STATIC_DIR

PARKS_IMG_DIR = STATIC_DIR / "img" / "parks"
DEFAULT_HERO = "/static/img/killarney-hero.jpg"

# (filename stem, display title) in display order — campground first.
_MAP_KINDS = [("campground-map", "Campground map"), ("park-map", "Park map")]
_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _find(slug: str, stem: str) -> str | None:
    """Return the /static URL for <slug>/<stem>.<ext> if a file exists."""
    base = PARKS_IMG_DIR / slug
    for ext in _IMG_EXTS:
        if (base / f"{stem}{ext}").is_file():
            return f"/static/img/parks/{slug}/{stem}{ext}"
    return None


def hero_image(slug: str) -> str:
    """Per-park hero URL if a hero.* file exists, else the default hero."""
    return _find(slug, "hero") or DEFAULT_HERO


def park_maps(slug: str) -> list[dict]:
    """List of {title, url} for whichever map images exist (campground first)."""
    out = []
    for stem, title in _MAP_KINDS:
        url = _find(slug, stem)
        if url:
            out.append({"title": title, "url": url})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_park_assets.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/park_assets.py tests/test_park_assets.py
git commit -m "feat(car-camping): park_assets service (per-park hero + maps by slug)"
```

---

## Task 2: Home coords in config + getting_there coords

**Files:**
- Modify: `app/config.py`, `app/services/getting_there.py`
- Test: `tests/test_getting_there.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_getting_there.py`:

```python
def test_build_includes_home_and_park_coords(monkeypatch):
    monkeypatch.setattr(gt.parks_svc, "load_park_info", lambda slug: {"name": "Balsam Lake"})
    monkeypatch.setattr(gt.site_surveys, "load_survey", lambda slug: None)
    monkeypatch.setattr(gt.weather, "PARK_COORDS", {"balsam-lake": (44.58, -78.85)})
    monkeypatch.setattr(gt.config, "HOME_COORDS", (43.851, -79.020))
    monkeypatch.setattr(gt.config, "HOME_LABEL", "Ajax")

    ctx = gt.build("balsam-lake", booked_site="")
    assert ctx["home_coords"] == (43.851, -79.020)
    assert ctx["home_label"] == "Ajax"
    assert ctx["park_coords"] == (44.58, -78.85)


def test_build_park_coords_none_when_unknown(monkeypatch):
    monkeypatch.setattr(gt.parks_svc, "load_park_info", lambda slug: {})
    monkeypatch.setattr(gt.site_surveys, "load_survey", lambda slug: None)
    monkeypatch.setattr(gt.weather, "PARK_COORDS", {})
    ctx = gt.build("unknown", booked_site="")
    assert ctx["park_coords"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_getting_there.py -q`
Expected: FAIL — `gt.config` does not exist / keys missing (`AttributeError`/`KeyError`).

- [ ] **Step 3: Add config constants**

In `app/config.py`, after the cache-TTL lines, add:

```python
# Drive origin for car-camping route maps (Ajax, ON).
HOME_COORDS = (43.851, -79.020)
HOME_LABEL = "Ajax"
```

- [ ] **Step 4: Extend getting_there.build**

In `app/services/getting_there.py`, add an import near the top (after `import weather`):

```python
from app import config
```

Then change `build` to compute park coords and include the three new keys. Replace the `build` function body's return with:

```python
def build(park_slug: str, booked_site: str) -> dict:
    """Return template context for the getting-there section.

    Keys: park_name, drive_label, directions_url, map_url, booked_site,
    home_coords, home_label, park_coords.
    """
    info = parks_svc.load_park_info(park_slug) or {}
    survey = site_surveys.load_survey(park_slug)
    coords = getattr(weather, "PARK_COORDS", {}).get(park_slug)
    try:
        park_coords = (coords[0], coords[1])
    except (TypeError, IndexError, KeyError):
        park_coords = None
    return {
        "park_name": info.get("name") or park_slug,
        "drive_label": info.get("driveFromAjax") or None,
        "directions_url": _directions_url(park_slug),
        "map_url": info.get("campgroundMapUrl") or None,
        "booked_site": site_surveys.find_site(survey, booked_site),
        "home_coords": getattr(config, "HOME_COORDS", None),
        "home_label": getattr(config, "HOME_LABEL", None),
        "park_coords": park_coords,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_getting_there.py -q`
Expected: PASS (existing 2 + new 2 = 4).

- [ ] **Step 6: Run full suite + commit**

Run: `python3 -m pytest -q` → all pass.

```bash
git add app/config.py app/services/getting_there.py tests/test_getting_there.py
git commit -m "feat(car-camping): home/park coords + Ajax origin for route map"
```

---

## Task 3: Copy Balsam Lake image assets

**Files:**
- Create: `app/static/img/parks/balsam-lake/campground-map.png`, `park-map.png`, `hero.jpg`

- [ ] **Step 1: Create the dir and copy the three source images**

The hero filename on the Desktop contains a colon — quote it exactly.

```bash
mkdir -p app/static/img/parks/balsam-lake
cp "/Users/alex/Desktop/oak fir campground map.png" app/static/img/parks/balsam-lake/campground-map.png
cp "/Users/alex/Desktop/park map.png" app/static/img/parks/balsam-lake/park-map.png
cp "/Users/alex/Desktop/balsam-lake:hero.jpg" app/static/img/parks/balsam-lake/hero.jpg
```

- [ ] **Step 2: Verify the three files exist and are valid images**

Run:
```bash
file app/static/img/parks/balsam-lake/campground-map.png \
     app/static/img/parks/balsam-lake/park-map.png \
     app/static/img/parks/balsam-lake/hero.jpg
```
Expected: each reported as PNG / JPEG image data (non-zero size). If the hero `cp` failed (colon/quoting), re-run with the exact quoted path; if the source is missing, STOP and ask the user for the hero path.

- [ ] **Step 3: Confirm park_assets now discovers them**

Run:
```bash
python3 -c "from app.services import park_assets as pa; print(pa.hero_image('balsam-lake')); print(pa.park_maps('balsam-lake'))"
```
Expected:
```
/static/img/parks/balsam-lake/hero.jpg
[{'title': 'Campground map', 'url': '/static/img/parks/balsam-lake/campground-map.png'}, {'title': 'Park map', 'url': '/static/img/parks/balsam-lake/park-map.png'}]
```

- [ ] **Step 4: Commit**

```bash
git add app/static/img/parks/balsam-lake/
git commit -m "data(car-camping): Balsam Lake hero + campground/park map images"
```

---

## Task 4: trip.css — remove stamp, per-park hero, map layout

**Files:**
- Modify: `app/static/css/trip.css`

(CSS-only; verified at the live-check task. No unit test.)

- [ ] **Step 1: Switch the page background to the hero variable**

In `app/static/css/trip.css`, in the `body.has-fixed-hero::before` rule, replace the line:

```css
    url("/static/img/killarney-hero.jpg") center / cover no-repeat;
```
with:
```css
    var(--hero-image, url("/static/img/killarney-hero.jpg")) center / cover no-repeat;
```

- [ ] **Step 2: Remove the journal-stamp pseudo-element**

Delete the entire `.trip-hero::before { ... }` rule (the block whose `content` is `"FIELD JOURNAL  \B7  EXPEDITION LOG"`). Use perl to remove it precisely:

```bash
perl -0pi -e 's/\.trip-hero::before \{.*?\}\n//s' app/static/css/trip.css
```
Then confirm it is gone:
```bash
grep -c "FIELD JOURNAL" app/static/css/trip.css   # expect 0
grep -c "trip-hero::before" app/static/css/trip.css  # expect 0
```

- [ ] **Step 3: Append route-map + zoom-map layout styles**

Append to the end of `app/static/css/trip.css`:

```css
/* ──────────────────────────────────────────────────────────────────────────
   Car-camping: route map + zoomable park maps
   ────────────────────────────────────────────────────────────────────────── */
#route-map {
  height: 320px;
  margin-top: 1rem;
  border-radius: 4px;
  box-shadow: var(--shadow);
}
.gt-maps-section { margin-top: 1.75rem; }
.gt-maps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1.25rem;
  margin: 0.5rem 0 1rem;
}
.gt-map-fig { margin: 0; }
.zoom-map {
  height: 360px;
  border-radius: 4px;
  background: var(--parchment-deep);
  box-shadow: var(--shadow);
}
.zoom-map .leaflet-container { background: var(--parchment-deep); }
.gt-map-caption {
  font-family: var(--font-mono);
  font-size: 0.74rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-soft);
  margin: 0.45rem 0 0;
}
```

- [ ] **Step 4: Commit**

```bash
git add app/static/css/trip.css
git commit -m "style(trip): remove journal stamp, per-park --hero-image, map layout"
```

---

## Task 5: trip_pages context + trip.html wiring

**Files:**
- Modify: `app/routes/trip_pages.py`, `app/templates/trip.html`
- Test: `tests/test_trip_page_modes.py` (add cases)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_trip_page_modes.py` (the file already has `_write_trip`, `client`, and imports `trips_svc`):

```python
def test_hero_image_set_per_park(client, tmp_path, monkeypatch):
    import app.services.park_assets as pa
    parks_root = tmp_path / "parksimg"
    (parks_root / "balsam-lake").mkdir(parents=True)
    (parks_root / "balsam-lake" / "hero.jpg").write_bytes(b"x")
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", parks_root)
    slug = _write_trip(tmp_path, monkeypatch, mode="car_camping", site="401")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert '--hero-image: url("/static/img/parks/balsam-lake/hero.jpg")' in r.text


def test_hero_image_default_when_absent(client, tmp_path, monkeypatch):
    import app.services.park_assets as pa
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path / "empty")
    slug = _write_trip(tmp_path, monkeypatch, mode="paddle")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    assert '--hero-image: url("/static/img/killarney-hero.jpg")' in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_trip_page_modes.py -q`
Expected: FAIL — no `--hero-image` in output yet.

- [ ] **Step 3: Pass hero_image + park_maps from the route**

In `app/routes/trip_pages.py`, add near the existing imports at the top:

```python
from app.services import park_assets
```

In the car-camping branch (where `getting_there = gt.build(...)` is built), after computing `getting_there`, add:

```python
        park_maps = park_assets.park_maps(trip.park)
```

And initialize `park_maps = []` alongside the other defaults (before the `if trip.mode == "car_camping":` branch) so paddle trips have it defined:

```python
    park_maps = []
```

Then add to the `TemplateResponse` context dict (alongside `"getting_there": getting_there,`):

```python
            "hero_image": park_assets.hero_image(trip.park),
            "park_maps": park_maps,
```

- [ ] **Step 4: Set --hero-image and load Leaflet for car mode in trip.html**

In `app/templates/trip.html`, in `{% block head_extra %}` (after the existing stylesheet links), add the hero variable for all trips and Leaflet assets for car mode:

```html
<style>:root { --hero-image: url("{{ hero_image }}"); }</style>
{% if trip.mode == "car_camping" %}
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.css"/>
{% endif %}
```

And near the end of the body block, after the existing `site_search.js` script line, add (car mode only):

```html
  {% if trip.mode == "car_camping" %}
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.js"></script>
  <script src="/static/js/car_maps.js?v={{ static_version }}"></script>
  {% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_trip_page_modes.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 6: Full suite + commit**

Run: `python3 -m pytest -q` → all pass.

```bash
git add app/routes/trip_pages.py app/templates/trip.html tests/test_trip_page_modes.py
git commit -m "feat(car-camping): per-park hero + Leaflet wiring on trip page"
```

---

## Task 6: section_getting_there.html — route map + maps block

**Files:**
- Modify: `app/templates/partials/section_getting_there.html`
- Test: `tests/test_trip_page_modes.py` (add a case)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_trip_page_modes.py`:

```python
def test_car_camping_renders_route_map_and_zoom_maps(client, tmp_path, monkeypatch):
    import app.services.park_assets as pa
    parks_root = tmp_path / "parksimg"
    (parks_root / "balsam-lake").mkdir(parents=True)
    for f in ("campground-map.png", "park-map.png"):
        (parks_root / "balsam-lake" / f).write_bytes(b"x")
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", parks_root)
    slug = _write_trip(tmp_path, monkeypatch, mode="car_camping", site="401")
    r = client.get(f"/trip/{slug}")
    assert r.status_code == 200
    # route map container with park coords (Balsam is in weather.PARK_COORDS)
    assert 'id="route-map"' in r.text
    assert 'data-park-lat=' in r.text and 'data-home-lat=' in r.text
    # one zoomable viewer per discovered map
    assert r.text.count('class="zoom-map"') == 2
    assert 'data-img="/static/img/parks/balsam-lake/campground-map.png"' in r.text
    # PDF link still present (campgroundMapUrl in parks.json)
    assert "Download official PDF" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_trip_page_modes.py::test_car_camping_renders_route_map_and_zoom_maps -q`
Expected: FAIL — no `route-map` / `zoom-map` yet.

- [ ] **Step 3: Add the route-map container to the drive block**

In `app/templates/partials/section_getting_there.html`, inside the `<div class="gt-drive">` block, after the "Get directions" link line and before the closing `</div>` of `gt-drive`, add:

```html
      {% if g.park_coords %}
      <div id="route-map"
           data-home-lat="{{ g.home_coords[0] if g.home_coords else '' }}"
           data-home-lon="{{ g.home_coords[1] if g.home_coords else '' }}"
           data-home-label="{{ g.home_label or 'Home' }}"
           data-park-lat="{{ g.park_coords[0] }}"
           data-park-lon="{{ g.park_coords[1] }}"></div>
      {% endif %}
```

- [ ] **Step 4: Replace the single map link with the maps block**

In the same file, replace the existing map block:

```html
    {% if g.map_url %}
    <div class="gt-map">
      <h3>Campground map</h3>
      <a class="btn btn-ghost" href="{{ g.map_url }}" target="_blank" rel="noopener">Open official park map ↗</a>
    </div>
    {% endif %}
```

with:

```html
    {% if park_maps or g.map_url %}
    <div class="gt-maps-section">
      <h3>Maps</h3>
      <div class="gt-maps">
        {% for m in park_maps %}
        <figure class="gt-map-fig">
          <div class="zoom-map" data-img="{{ m.url }}"></div>
          <figcaption class="gt-map-caption">{{ m.title }}</figcaption>
        </figure>
        {% endfor %}
      </div>
      {% if g.map_url %}<a class="btn btn-ghost" href="{{ g.map_url }}" target="_blank" rel="noopener">Download official PDF ↗</a>{% endif %}
    </div>
    {% endif %}
```

(The lightbox `<div>` added earlier and the `{% set s = ... %}` booked-site block stay unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_trip_page_modes.py -q`
Expected: PASS (all mode tests including the new one).

- [ ] **Step 6: Full suite + commit**

Run: `python3 -m pytest -q` → all pass.

```bash
git add app/templates/partials/section_getting_there.html tests/test_trip_page_modes.py
git commit -m "feat(car-camping): route-map + zoomable maps block in getting-there"
```

---

## Task 7: car_maps.js — route map + zoomable viewers

**Files:**
- Create: `app/static/js/car_maps.js`

(Browser JS; verified by `node --check` and the live Playwright task.)

- [ ] **Step 1: Create the file**

```bash
cat > app/static/js/car_maps.js <<'JS'
/* Car-camping trip page maps: an OSM driving route (Ajax → park) and
   zoomable park-map image viewers. Both reuse Leaflet. No-ops if Leaflet
   or the target elements are absent, so the page never breaks. */
(function () {
  function num(v) { var n = parseFloat(v); return isNaN(n) ? null : n; }

  function initRouteMap() {
    var el = document.getElementById('route-map');
    if (!el || typeof L === 'undefined') return;
    var plat = num(el.dataset.parkLat), plon = num(el.dataset.parkLon);
    if (plat === null || plon === null) return;
    var hlat = num(el.dataset.homeLat), hlon = num(el.dataset.homeLon);
    var park = L.latLng(plat, plon);

    var map = L.map(el);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    var routed = false;
    if (L.Routing && hlat !== null && hlon !== null) {
      try {
        L.Routing.control({
          waypoints: [L.latLng(hlat, hlon), park],
          router: L.Routing.osrmv1({ serviceUrl: 'https://router.project-osrm.org/route/v1' }),
          addWaypoints: false, draggableWaypoints: false, fitSelectedRoutes: true, show: false,
          lineOptions: { styles: [{ color: '#a8451f', weight: 5, opacity: 0.85 }] },
          createMarker: function (i, wp) { return L.marker(wp.latLng); }
        }).addTo(map);
        routed = true;
      } catch (e) { routed = false; }
    }
    if (!routed) {
      L.marker(park).addTo(map);
      if (hlat !== null && hlon !== null) {
        var home = L.latLng(hlat, hlon);
        L.marker(home).addTo(map);
        L.polyline([home, park], { color: '#a8451f', weight: 3, dashArray: '6,6' }).addTo(map);
        map.fitBounds(L.latLngBounds([home, park]).pad(0.2));
      } else {
        map.setView(park, 12);
      }
    }
  }

  function initZoomableMaps() {
    if (typeof L === 'undefined') return;
    document.querySelectorAll('.zoom-map').forEach(function (el) {
      var src = el.dataset.img;
      if (!src) return;
      var probe = new Image();
      probe.onload = function () {
        var h = probe.naturalHeight, w = probe.naturalWidth;
        var map = L.map(el, { crs: L.CRS.Simple, minZoom: -4, attributionControl: false });
        var bounds = [[0, 0], [h, w]];
        L.imageOverlay(src, bounds).addTo(map);
        map.fitBounds(bounds);
      };
      probe.src = src;
    });
  }

  function init() { initRouteMap(); initZoomableMaps(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else { init(); }
})();
JS
```

- [ ] **Step 2: Syntax-check**

Run: `node --check app/static/js/car_maps.js`
Expected: no output (valid). If `node` is unavailable, skip — the live task will catch errors.

- [ ] **Step 3: Commit**

```bash
git add app/static/js/car_maps.js
git commit -m "feat(car-camping): car_maps.js — OSM route + zoomable map viewers"
```

---

## Task 8: Live verification + regression

**Files:** none (verification only)

- [ ] **Step 1: Full regression**

Run: `python3 -m pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Start a fresh server**

```bash
(uvicorn app.main:app --port 8014 --log-level warning > "$CLAUDE_JOB_DIR/uv_maps.log" 2>&1 &) ; sleep 4
```

- [ ] **Step 3: Verify the real Balsam trip renders the new pieces**

```bash
curl -s http://127.0.0.1:8014/trip/balsam-lake-2026-05 | grep -o 'id="route-map"\|class="zoom-map"\|data-img="/static/img/parks/balsam-lake/campground-map.png"\|Download official PDF\|--hero-image: url("/static/img/parks/balsam-lake/hero.jpg")\|FIELD JOURNAL' | sort | uniq -c
```
Expected: `route-map` ×1, `zoom-map` ×2, the campground `data-img`, the PDF link, the Balsam `--hero-image`; **zero** `FIELD JOURNAL`.

- [ ] **Step 4: Playwright visual check**

Navigate (Playwright MCP) to `http://127.0.0.1:8014/trip/balsam-lake-2026-05`:
- Confirm the background is the Balsam Lake photo, no "FIELD JOURNAL · EXPEDITION LOG" stamp.
- The Drive block shows an OSM map with a route line from Ajax to Balsam (give the OSRM request a moment; if it doesn't draw, the fallback dashed line + two pins must show).
- The Maps block shows two map panels; scroll-zoom and drag pan work on each.
- The booked-site card (Site 401) and "Download official PDF" link are present.
- Check console: only the benign favicon 404 is acceptable; no Leaflet/JS errors.

Then verify a paddle trip is unaffected:
```bash
curl -s http://127.0.0.1:8014/trip/killarney-2026-05 | grep -o 'data-section="route"\|id="route-map"\|--hero-image: url("/static/img/killarney-hero.jpg")' | sort | uniq -c
```
Expected: `data-section="route"` present, `route-map` absent, default `--hero-image`.

- [ ] **Step 5: Stop the server**

```bash
pkill -f "uvicorn app.main:app --port 8014" 2>/dev/null
```

---

## Self-Review Notes

- **Spec coverage:** per-park asset convention + `park_assets` (T1, T3); per-park background via `--hero-image` (T4, T5); remove journal stamp (T4); home/park coords + Ajax origin (T2); OSM driving route w/ LRM+OSRM + fallback (T5 wiring, T6 container, T7 JS); two zoomable maps + PDF link (T6 template, T7 JS); car-only Leaflet load + paddle unaffected (T5, T8). No gaps.
- **Type consistency:** `park_assets.hero_image(slug)->str`, `park_maps(slug)->list[{title,url}]`, module attr `PARKS_IMG_DIR` (monkeypatched in T1/T5/T6). `getting_there.build` adds `home_coords/home_label/park_coords` (T2) consumed by section (T6) and `car_maps.js` reads `data-home-lat/lon`, `data-park-lat/lon` (T6 emits, T7 reads). `hero_image`/`park_maps` passed in context by T5, consumed by T5 (`--hero-image`) and T6 (`park_maps`).
- **Deferred (spec non-goals):** offline tiles, turn-by-turn list, server-side routing, paddle-path changes.
