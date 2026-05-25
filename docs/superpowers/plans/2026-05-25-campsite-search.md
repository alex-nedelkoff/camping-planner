# Campsite Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a browse-only, per-park "Campsite Search" tab reachable from the home page, data-driven so future parks appear by dropping in a survey file.

**Architecture:** A reusable compile script normalizes raw Camis resources JSON into one survey file per park under `app/data/site_surveys/`. A service layer lists/loads surveys and derives per-park filter options. Two FastAPI routes render an index and a per-park filterable grid using the app's cartographer theme; client-side JS filters cards by data-attributes. No availability, no API calls at view time, no trip coupling.

**Tech Stack:** FastAPI, Jinja2, vanilla JS, pytest + FastAPI TestClient, Playwright (manual verify).

**Spec:** `docs/superpowers/specs/2026-05-25-campsite-search-design.md`

---

## File Structure

- Create `app/services/site_surveys.py` — list/load surveys + `derive_filters()`.
- Modify `app/config.py` — add `SITE_SURVEYS_DIR`.
- Create `scripts/compile_site_survey.py` — raw resources -> normalized survey JSON.
- Create `app/data/site_surveys/balsam-lake.json` — generated survey (committed).
- Create `app/routes/sites.py` — `/sites` and `/sites/{slug}`.
- Modify `app/main.py` — register the sites router.
- Create `app/templates/sites_index.html`, `app/templates/sites_park.html`.
- Create `app/static/js/site_search.js`, `app/static/css/sites.css`.
- Modify `app/templates/index.html` — add the "Campsite Search" header link.
- Create tests: `tests/test_site_surveys.py`, `tests/test_compile_site_survey.py`, `tests/test_sites_routes.py`.

---

## Task 1: Config path + survey service (list/load/derive_filters)

**Files:**
- Modify: `app/config.py`
- Create: `app/services/site_surveys.py`
- Test: `tests/test_site_surveys.py`

- [ ] **Step 1: Add the survey directory to config**

In `app/config.py`, after the `STATIC_DIR = APP_DIR / "static"` line, add:

```python
SITE_SURVEYS_DIR = APP_DIR / "data" / "site_surveys"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_site_surveys.py`:

```python
import json

import pytest

from app import config
from app.services import site_surveys


@pytest.fixture
def surveys_dir(tmp_path, monkeypatch):
    d = tmp_path / "site_surveys"
    d.mkdir()
    monkeypatch.setattr(config, "SITE_SURVEYS_DIR", d)
    monkeypatch.setattr(site_surveys, "SITE_SURVEYS_DIR", d)
    return d


def _write(d, slug, park_name=None, site_count=1, sites=None):
    payload = {
        "park_slug": slug,
        "park_name": park_name or slug,
        "pulled_on": "2026-05-24",
        "site_count": site_count,
        "sites": sites if sites is not None else [
            {"name": "1", "campground": "A", "equipment_bucket": "Tent only",
             "description": "", "max_capacity": 6, "attributes": {}, "photos": []}
        ],
    }
    (d / f"{slug}.json").write_text(json.dumps(payload))


def test_list_surveys_returns_summaries(surveys_dir):
    _write(surveys_dir, "balsam-lake", park_name="Balsam Lake", site_count=3)
    out = site_surveys.list_surveys()
    assert len(out) == 1
    assert out[0]["park_slug"] == "balsam-lake"
    assert out[0]["site_count"] == 3
    assert out[0]["pulled_on"] == "2026-05-24"


def test_list_surveys_sorted_by_name(surveys_dir):
    _write(surveys_dir, "z-park", park_name="Zed")
    _write(surveys_dir, "a-park", park_name="Algonquin")
    out = site_surveys.list_surveys()
    assert [e["park_name"] for e in out] == ["Algonquin", "Zed"]


def test_list_surveys_empty_when_no_dir(tmp_path, monkeypatch):
    missing = tmp_path / "nope"
    monkeypatch.setattr(site_surveys, "SITE_SURVEYS_DIR", missing)
    assert site_surveys.list_surveys() == []


def test_load_survey_returns_full(surveys_dir):
    _write(surveys_dir, "balsam-lake")
    s = site_surveys.load_survey("balsam-lake")
    assert s["park_slug"] == "balsam-lake"
    assert "sites" in s


def test_load_survey_missing_returns_none(surveys_dir):
    assert site_surveys.load_survey("nope") is None


def test_derive_filters():
    sites = [
        {"campground": "A", "equipment_bucket": "Tent only",
         "attributes": {"Privacy": "Good", "Site Length (m)": 12}},
        {"campground": "B", "equipment_bucket": "RV / big rig",
         "attributes": {"Privacy": "Poor", "Site Length (m)": 24}},
        {"campground": "A", "equipment_bucket": "Tent only", "attributes": {}},
    ]
    f = site_surveys.derive_filters(sites)
    assert f["campgrounds"] == ["A", "B"]
    assert f["privacy"] == ["Good", "Poor"]
    assert f["has_unrated"] is True
    assert f["equipment"] == ["Tent only", "RV / big rig"]
    assert f["len_min"] == 12 and f["len_max"] == 24
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_site_surveys.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.site_surveys'`.

- [ ] **Step 4: Implement the service**

Create `app/services/site_surveys.py`:

```python
"""Load/list normalized site-survey JSON files for the Campsite Search pages.

A survey file is produced by `scripts/compile_site_survey.py` and lives at
`app/data/site_surveys/<park-slug>.json`. Browse-only: no availability.
"""

from __future__ import annotations

import json

from app.config import SITE_SURVEYS_DIR

PRIVACY_ORDER = ["Good", "Average", "Poor"]
EQUIPMENT_ORDER = [
    "Tent only", "Small trailer / pop-up", "Trailer / motorhome",
    "RV / big rig", "Other / special",
]


def list_surveys() -> list[dict]:
    """Return lightweight summaries of every survey file, sorted by park name."""
    if not SITE_SURVEYS_DIR.exists():
        return []
    out = []
    for f in sorted(SITE_SURVEYS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "park_slug": d.get("park_slug") or f.stem,
            "park_name": d.get("park_name") or f.stem,
            "site_count": d.get("site_count") or len(d.get("sites") or []),
            "pulled_on": d.get("pulled_on"),
        })
    out.sort(key=lambda e: e["park_name"])
    return out


def load_survey(slug: str) -> dict | None:
    """Return the full survey for a slug, or None if there is no file."""
    path = SITE_SURVEYS_DIR / f"{slug}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def derive_filters(sites: list[dict]) -> dict:
    """Compute the filter option sets present in a park's sites."""
    campgrounds = sorted({s.get("campground") for s in sites if s.get("campground")})
    privacy_present = {(s.get("attributes") or {}).get("Privacy") for s in sites}
    privacy = [p for p in PRIVACY_ORDER if p in privacy_present]
    has_unrated = any(not (s.get("attributes") or {}).get("Privacy") for s in sites)
    eq_present = {s.get("equipment_bucket") for s in sites}
    equipment = [e for e in EQUIPMENT_ORDER if e in eq_present]
    lengths = [(s.get("attributes") or {}).get("Site Length (m)") for s in sites]
    lengths = [x for x in lengths if isinstance(x, (int, float))]
    len_min = int(min(lengths)) if lengths else 0
    len_max = int(max(lengths)) if lengths else 50
    return {
        "campgrounds": campgrounds,
        "privacy": privacy,
        "has_unrated": has_unrated,
        "equipment": equipment,
        "len_min": len_min,
        "len_max": len_max,
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_site_surveys.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/services/site_surveys.py tests/test_site_surveys.py
git commit -m "feat(sites): survey load/list service + filter derivation"
```

---

## Task 2: Compile script (raw resources -> normalized survey JSON)

**Files:**
- Create: `scripts/compile_site_survey.py`
- Test: `tests/test_compile_site_survey.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_compile_site_survey.py`:

```python
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "compile_site_survey.py"
spec = importlib.util.spec_from_file_location("compile_site_survey", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_compile_resolves_enums_buckets_photos():
    attr_defs = {
        -32762: {"name": "Privacy", "values": {0: "Poor", 1: "Average", 2: "Good"}},
        -32743: {"name": "Site Length (m)", "values": {}},
    }
    resources = {
        "1": {
            "resourceId": 1,
            "localizedValues": [
                {"name": "312", "description": "nice", "cultureName": "en-CA"}
            ],
            "mapIds": [10],
            "maxCapacity": 6,
            "allowedEquipment": [1, 2, 3, 4, 5],
            "definedAttributes": [
                {"attributeDefinitionId": -32762, "value": None, "values": [2]},
                {"attributeDefinitionId": -32743, "value": 20.0, "values": []},
            ],
            "photos": [{"photoUrlResult": {"url": "https://x/1.jpg"}}],
        }
    }
    survey = mod.compile_survey(resources, attr_defs, "test-park", "Test Park", "2026-05-24")
    assert survey["park_slug"] == "test-park"
    assert survey["park_name"] == "Test Park"
    assert survey["pulled_on"] == "2026-05-24"
    assert survey["site_count"] == 1
    site = survey["sites"][0]
    assert site["name"] == "312"
    assert site["description"] == "nice"
    assert site["max_capacity"] == 6
    assert site["attributes"]["Privacy"] == "Good"
    assert site["attributes"]["Site Length (m)"] == 20.0
    assert site["equipment_bucket"] == "Trailer / motorhome"
    assert site["photos"] == ["https://x/1.jpg"]
    assert site["campground"].startswith("Sites #312")


def test_load_attr_defs_reads_enum_labels(tmp_path):
    catalog = tmp_path / "cat.json"
    catalog.write_text(
        '{"a": {"attributeDefinitionId": -32762,'
        ' "localizedValues": [{"cultureName": "en-CA", "displayName": "Privacy"}],'
        ' "values": [{"enumValue": 2,'
        '   "localizedValues": [{"cultureName": "en-CA", "displayName": "Good"}]}]}}'
    )
    defs = mod.load_attr_defs(catalog)
    assert defs[-32762]["name"] == "Privacy"
    assert defs[-32762]["values"][2] == "Good"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_compile_site_survey.py -q`
Expected: FAIL — `FileNotFoundError`/import error because `scripts/compile_site_survey.py` does not exist yet.

- [ ] **Step 3: Implement the compile script**

Create `scripts/compile_site_survey.py`:

```python
#!/usr/bin/env python3
"""Compile a Camis park resources dump into a normalized site-survey JSON.

Browse-only reference data for the in-app Campsite Search. Availability is
intentionally NOT included (date-specific + rate-limited; the home-page
availability check covers that).

Add a future park:
    python scripts/compile_site_survey.py \
        --resources <raw_resources.json> \
        --park-slug balsam-lake \
        --park-name "Balsam Lake Provincial Park" \
        --out app/data/site_surveys/balsam-lake.json

Then commit the output file; it appears on /sites automatically.

Camis quirks handled here:
- Enum attributes store ints in definedAttributes[].values (a LIST); numeric
  attributes store a scalar in definedAttributes[].value.
- The attribute catalog maps enum ints to labels under each attribute's
  `values` list (entry keys: enumValue + localizedValues), NOT `enumValues`.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "api_attribute_filterable.json"

# Site-length attribute id, used for the equipment bucket heuristic.
SITE_LENGTH_ATTR_ID = -32743


def load_attr_defs(catalog_path) -> dict:
    """Build {attributeDefinitionId: {name, values:{enumInt: label}}}."""
    raw = json.loads(Path(catalog_path).read_text())
    defs = {}
    for a in (raw.values() if isinstance(raw, dict) else raw):
        if not isinstance(a, dict):
            continue
        aid = a.get("attributeDefinitionId")
        name = None
        for lv in (a.get("localizedValues") or []):
            if lv.get("cultureName", "").startswith("en"):
                name = lv.get("displayName") or lv.get("name")
                break
        if not name and a.get("localizedValues"):
            first = a["localizedValues"][0]
            name = first.get("displayName") or first.get("name")
        name = name or f"attr_{aid}"
        values = {}
        for v in (a.get("values") or []):
            vid = v.get("enumValue")
            vname = None
            for lv in (v.get("localizedValues") or []):
                if lv.get("cultureName", "").startswith("en"):
                    vname = lv.get("displayName") or lv.get("name")
                    break
            if not vname and v.get("localizedValues"):
                first = v["localizedValues"][0]
                vname = first.get("displayName") or first.get("name")
            values[vid] = vname or str(vid)
        defs[aid] = {"name": name, "values": values}
    return defs


def attr_get(da: dict, attr_defs: dict):
    """Return (name, value_or_label) for one definedAttributes entry."""
    aid = da.get("attributeDefinitionId")
    if aid not in attr_defs:
        return None, None
    name = attr_defs[aid]["name"]
    enum_vals = da.get("values") or []
    if enum_vals:
        labels = [attr_defs[aid]["values"].get(v, str(v)) for v in enum_vals]
        return name, (", ".join(labels) if len(labels) > 1 else labels[0])
    scalar = da.get("value")
    if scalar is not None:
        return name, scalar
    return name, None


def derive_campground_label(names: list[str]) -> str:
    """Label a map group from its site-number range or name prefixes."""
    nums, prefixes = [], set()
    for n in names:
        m = re.match(r"^(\d+)", n)
        if m:
            nums.append(int(m.group(1)))
        pm = re.match(r"^([A-Za-z]+)", n)
        if pm:
            prefixes.add(pm.group(1))
    if nums:
        return f"Sites #{min(nums)}-{max(nums)} ({len(names)})"
    if "E" in prefixes:
        return f"E sites - electric ({len(names)})"
    if "T" in prefixes:
        return f"T sites ({len(names)})"
    if "Picnic" in prefixes:
        return f"Picnic shelters ({len(names)})"
    if "RA" in prefixes:
        return f"RA - roofed accommodation ({len(names)})"
    if any(p in prefixes for p in {"Bike", "Canoe", "Kayak", "Paddle", "SUP",
                                    "Water", "Floater", "Deposit"}):
        return f"Rentals - day-use ({len(names)})"
    if "DVP" in prefixes or "Bus" in prefixes:
        return f"Permits ({len(names)})"
    return f"Other ({len(names)})"


def equipment_bucket(s: dict) -> str:
    """Coarse equipment class from allowed-equipment count + site length."""
    n_eq = len(s.get("allowedEquipment") or [])
    length = None
    for da in (s.get("definedAttributes") or []):
        if da.get("attributeDefinitionId") == SITE_LENGTH_ATTR_ID:
            try:
                length = float(da.get("value") or 0) or None
            except (TypeError, ValueError):
                pass
    if n_eq == 0:
        return "Other / special"
    if length and length >= 24:
        return "RV / big rig"
    if n_eq >= 5 or (length and length >= 18):
        return "Trailer / motorhome"
    if n_eq >= 3:
        return "Small trailer / pop-up"
    return "Tent only"


def compile_survey(resources: dict, attr_defs: dict, park_slug: str,
                   park_name: str, pulled_on: str | None = None) -> dict:
    by_map = defaultdict(list)
    for _sid, s in resources.items():
        nm = (s.get("localizedValues") or [{}])[0].get("name") or ""
        mid = (s.get("mapIds") or [None])[0]
        by_map[mid].append(nm)
    campground_labels = {
        mid: derive_campground_label(names) for mid, names in by_map.items()
    }

    sites = []
    for _sid, s in resources.items():
        lv = (s.get("localizedValues") or [{}])[0]
        name = lv.get("name") or lv.get("displayName") or ""
        mid = (s.get("mapIds") or [None])[0]
        attributes = {}
        for da in (s.get("definedAttributes") or []):
            n, v = attr_get(da, attr_defs)
            if n and v is not None and v != "":
                attributes[n] = v
        photos = []
        for p in (s.get("photos") or []):
            urlres = p.get("photoUrlResult") or {}
            url = urlres.get("url") or urlres.get("avifUrl")
            if url:
                photos.append(url)
        sites.append({
            "name": name,
            "campground": campground_labels.get(mid, "Other"),
            "equipment_bucket": equipment_bucket(s),
            "description": lv.get("description") or "",
            "max_capacity": s.get("maxCapacity"),
            "attributes": attributes,
            "photos": photos,
        })
    sites.sort(key=lambda r: (r["campground"], r["name"]))
    return {
        "park_slug": park_slug,
        "park_name": park_name,
        "pulled_on": pulled_on or date.today().isoformat(),
        "site_count": len(sites),
        "sites": sites,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resources", required=True)
    ap.add_argument("--park-slug", required=True)
    ap.add_argument("--park-name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--catalog", default=str(CATALOG))
    ap.add_argument("--pulled-on", default=None)
    args = ap.parse_args()

    resources = json.loads(Path(args.resources).read_text())
    attr_defs = load_attr_defs(args.catalog)
    survey = compile_survey(resources, attr_defs, args.park_slug,
                            args.park_name, args.pulled_on)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(survey, indent=2, ensure_ascii=False))
    print(f"Wrote {out} - {survey['site_count']} sites")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_compile_site_survey.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/compile_site_survey.py tests/test_compile_site_survey.py
git commit -m "feat(sites): reusable compile_site_survey script"
```

---

## Task 3: Generate and commit the Balsam Lake survey

**Files:**
- Create: `app/data/site_surveys/balsam-lake.json` (generated)

- [ ] **Step 1: Run the compile script against the raw Balsam resources**

The raw dump lives in the background job dir as `balsam_resources.json`. Run:

```bash
python scripts/compile_site_survey.py \
  --resources "$CLAUDE_JOB_DIR/balsam_resources.json" \
  --park-slug balsam-lake \
  --park-name "Balsam Lake Provincial Park" \
  --pulled-on 2026-05-24 \
  --out app/data/site_surveys/balsam-lake.json
```

Expected: `Wrote app/data/site_surveys/balsam-lake.json - 532 sites`.

(If `$CLAUDE_JOB_DIR/balsam_resources.json` is unavailable, the same raw file may be re-pulled, or copied from a prior run; it is the Camis resources response for Balsam Lake.)

- [ ] **Step 2: Sanity-check the output**

Run:

```bash
python -c "import json; d=json.load(open('app/data/site_surveys/balsam-lake.json')); \
print(d['site_count'], 'sites'); \
import collections; c=collections.Counter(s['attributes'].get('Privacy','(none)') for s in d['sites']); \
print('privacy:', dict(c))"
```

Expected: ~532 sites and a Privacy distribution with Good/Average/Poor populated (not all `(none)`).

- [ ] **Step 3: Commit**

```bash
git add app/data/site_surveys/balsam-lake.json
git commit -m "data(sites): Balsam Lake site survey (532 sites)"
```

---

## Task 4: Routes + router registration

**Files:**
- Create: `app/routes/sites.py`
- Modify: `app/main.py`
- Test: `tests/test_sites_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sites_routes.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import site_surveys


@pytest.fixture
def client(tmp_path, monkeypatch):
    d = tmp_path / "site_surveys"
    d.mkdir()
    (d / "balsam-lake.json").write_text(json.dumps({
        "park_slug": "balsam-lake",
        "park_name": "Balsam Lake",
        "pulled_on": "2026-05-24",
        "site_count": 1,
        "sites": [{
            "name": "312", "campground": "Sites #300-360",
            "equipment_bucket": "Tent only", "description": "lakeside",
            "max_capacity": 6,
            "attributes": {"Privacy": "Good", "Site Length (m)": 15},
            "photos": [],
        }],
    }))
    monkeypatch.setattr(config, "SITE_SURVEYS_DIR", d)
    monkeypatch.setattr(site_surveys, "SITE_SURVEYS_DIR", d)
    return TestClient(app)


def test_sites_index_lists_park(client):
    r = client.get("/sites")
    assert r.status_code == 200
    assert "Balsam Lake" in r.text
    assert "/sites/balsam-lake" in r.text


def test_sites_park_renders_sites_and_filters(client):
    r = client.get("/sites/balsam-lake")
    assert r.status_code == 200
    assert "312" in r.text
    assert "Campground" in r.text
    assert 'class="f-priv"' in r.text


def test_sites_park_unknown_returns_404(client):
    r = client.get("/sites/does-not-exist")
    assert r.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sites_routes.py -q`
Expected: FAIL — `/sites` returns 404 (route not registered) so assertions fail.

- [ ] **Step 3: Implement the routes**

Create `app/routes/sites.py`:

```python
"""Campsite Search - browse-only per-park site reference pages."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.services import site_surveys
from app.templating import templates

router = APIRouter()

KEY_ATTRS = [
    "Privacy", "Quality", "Site Shade", "Site Length (m)", "Site Width (m)",
    "Ground Cover", "Pad Slope", "Shoreline Access", "Dogs Allowed",
    "Double Site", "Pull-through", "Fire Pit Available",
]


@router.get("/sites", response_class=HTMLResponse)
def sites_index(request: Request):
    return templates.TemplateResponse(request, "sites_index.html", {
        "surveys": site_surveys.list_surveys(),
        "nav": {"home_href": "/", "show_user_pill": True},
    })


@router.get("/sites/{slug}", response_class=HTMLResponse)
def sites_park(request: Request, slug: str):
    survey = site_surveys.load_survey(slug)
    if survey is None:
        raise HTTPException(status_code=404, detail="No survey for that park")
    sites = survey.get("sites") or []
    return templates.TemplateResponse(request, "sites_park.html", {
        "survey": survey,
        "sites": sites,
        "filters": site_surveys.derive_filters(sites),
        "key_attrs": KEY_ATTRS,
        "nav": {"home_href": "/", "back_href": "/sites",
                "back_label": "All parks", "show_user_pill": True},
    })
```

- [ ] **Step 4: Register the router in main.py**

In `app/main.py`, update the import line:

```python
from app.routes import checklist, identity, pages, parks, sites, trip_pages, trips
```

and add, after `app.include_router(parks.router)`:

```python
app.include_router(sites.router)
```

Note: the templates referenced by these routes are created in Task 5; the route tests in this task will pass only after Task 5. Proceed to Task 5 before running Step 5 below. (Registration and route code are committed here; the rendering tests go green once templates exist.)

- [ ] **Step 5: Commit**

```bash
git add app/routes/sites.py app/main.py tests/test_sites_routes.py
git commit -m "feat(sites): /sites index + /sites/{slug} routes"
```

---

## Task 5: Templates (index + per-park grid)

**Files:**
- Create: `app/templates/sites_index.html`
- Create: `app/templates/sites_park.html`

- [ ] **Step 1: Create the index template**

Create `app/templates/sites_index.html`:

```html
{% extends "base.html" %}
{% block title %}Campsite Search{% endblock %}
{% block head_extra %}<link rel="stylesheet" href="/static/css/sites.css?v={{ static_version }}">{% endblock %}
{% block body %}
{% include "partials/nav_band.html" %}
<header class="page-title">
  <h1>🔍 Campsite Search</h1>
</header>
{% if surveys %}
<div class="survey-grid">
  {% for s in surveys %}
  <a class="survey-card" href="/sites/{{ s.park_slug }}">
    <h2>{{ s.park_name }}</h2>
    <p>{{ s.site_count }} sites{% if s.pulled_on %} · surveyed {{ s.pulled_on }}{% endif %}</p>
  </a>
  {% endfor %}
</div>
{% else %}
<p class="empty">No park surveys yet. Run <code>scripts/compile_site_survey.py</code> to add one.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Create the per-park grid template**

Create `app/templates/sites_park.html`:

```html
{% extends "base.html" %}
{% block title %}{{ survey.park_name }} — Sites{% endblock %}
{% block body_class %}sites-page{% endblock %}
{% block head_extra %}<link rel="stylesheet" href="/static/css/sites.css?v={{ static_version }}">{% endblock %}
{% block body %}
{% include "partials/nav_band.html" %}
<header class="page-title">
  <h1>{{ survey.park_name }}</h1>
  <p class="sub">{{ survey.site_count }} sites{% if survey.pulled_on %} · surveyed {{ survey.pulled_on }}{% endif %} · <span id="counter"></span></p>
</header>

<div class="filters">
  <div class="filter-group">
    <label class="title">Campground</label>
    <div class="checks">
      {% for c in filters.campgrounds %}
      <label class="opt"><input type="checkbox" class="f-camp" value="{{ c }}" checked> {{ c }}</label>
      {% endfor %}
    </div>
  </div>
  <div class="filter-group">
    <label class="title">Privacy</label>
    <div class="checks">
      {% for p in filters.privacy %}
      <label class="opt"><input type="checkbox" class="f-priv" value="{{ p }}" checked> {{ p }}</label>
      {% endfor %}
      {% if filters.has_unrated %}
      <label class="opt"><input type="checkbox" class="f-priv" value="" checked> Unrated</label>
      {% endif %}
    </div>
  </div>
  <div class="filter-group">
    <label class="title">Equipment type</label>
    <div class="checks">
      {% for e in filters.equipment %}
      <label class="opt"><input type="checkbox" class="f-eq" value="{{ e }}" checked> {{ e }}</label>
      {% endfor %}
    </div>
  </div>
  <div class="filter-group">
    <label class="title">Site length (m)</label>
    <div class="range-row">
      ≥ <input type="number" id="len-min" value="{{ filters.len_min }}" min="{{ filters.len_min }}" max="{{ filters.len_max }}">
      ≤ <input type="number" id="len-max" value="{{ filters.len_max }}" min="{{ filters.len_min }}" max="{{ filters.len_max }}">
    </div>
  </div>
  <div class="filter-group">
    <label class="title">Other</label>
    <label class="opt"><input type="checkbox" id="with-photos"> Has photos</label>
    <input type="search" id="q" placeholder="search name / desc">
  </div>
  <div class="actions">
    <button id="reset-filters" type="button">Reset</button>
    <button id="check-none-camp" type="button">Camp: none</button>
    <button id="check-all-camp" type="button">Camp: all</button>
    <span class="count" id="count"></span>
  </div>
</div>

<div class="grid" id="grid" data-len-min="{{ filters.len_min }}" data-len-max="{{ filters.len_max }}">
  {% for s in sites %}
  {% set length_num = s.attributes.get("Site Length (m)") %}
  <div class="site"
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
  {% endfor %}
</div>

<div class="lightbox" id="lb" onclick="this.classList.remove('open')"><img id="lbi"></div>
{% endblock %}
{% block scripts %}
<script src="/static/js/site_search.js?v={{ static_version }}"></script>
{% endblock %}
```

- [ ] **Step 3: Run the route tests to verify they now pass**

Run: `python -m pytest tests/test_sites_routes.py -q`
Expected: PASS (3 passed).

- [ ] **Step 4: Commit**

```bash
git add app/templates/sites_index.html app/templates/sites_park.html
git commit -m "feat(sites): index + per-park grid templates"
```

---

## Task 6: Client filter JS + stylesheet

**Files:**
- Create: `app/static/js/site_search.js`
- Create: `app/static/css/sites.css`

- [ ] **Step 1: Create the filter script**

Create `app/static/js/site_search.js`:

```javascript
(function () {
  const grid = document.getElementById('grid');
  if (!grid) return;
  const cards = Array.from(document.querySelectorAll('.site'));
  const lenMinDefault = parseFloat(grid.dataset.lenMin) || 0;
  const lenMaxDefault = parseFloat(grid.dataset.lenMax);

  function getChecked(cls) {
    return new Set(
      Array.from(document.querySelectorAll('.' + cls + ':checked')).map(e => e.value)
    );
  }

  function apply() {
    const camp = getChecked('f-camp');
    const priv = getChecked('f-priv');
    const eq = getChecked('f-eq');
    const lminRaw = parseFloat(document.getElementById('len-min').value);
    const lmaxRaw = parseFloat(document.getElementById('len-max').value);
    const lmin = isNaN(lminRaw) ? -Infinity : lminRaw;
    const lmax = isNaN(lmaxRaw) ? Infinity : lmaxRaw;
    const wp = document.getElementById('with-photos').checked;
    const q = document.getElementById('q').value.toLowerCase();
    let visible = 0;
    cards.forEach(c => {
      const okC = camp.size === 0 || camp.has(c.dataset.camp);
      const okP = priv.size === 0 || priv.has(c.dataset.priv);
      const okE = eq.size === 0 || eq.has(c.dataset.eq);
      const len = parseFloat(c.dataset.len);
      const okL = isNaN(len) ? true : (len >= lmin && len <= lmax);
      const okPh = !wp || parseInt(c.dataset.photos, 10) > 0;
      const okQ = !q || (c.dataset.q || '').includes(q);
      const show = okC && okP && okE && okL && okPh && okQ;
      c.classList.toggle('hidden', !show);
      if (show) visible++;
    });
    const summary = visible + ' / ' + cards.length;
    document.getElementById('count').textContent = summary + ' visible';
    const counter = document.getElementById('counter');
    if (counter) counter.textContent = summary + ' sites match';
  }

  document.querySelectorAll('.filters input').forEach(el => {
    el.addEventListener('change', apply);
    if (el.type === 'search' || el.type === 'number') {
      el.addEventListener('input', apply);
    }
  });

  document.getElementById('reset-filters').onclick = () => {
    document.querySelectorAll('.filters input[type="checkbox"]').forEach(e => {
      e.checked = e.id !== 'with-photos';
    });
    document.getElementById('len-min').value = lenMinDefault;
    if (!isNaN(lenMaxDefault)) document.getElementById('len-max').value = lenMaxDefault;
    document.getElementById('q').value = '';
    apply();
  };
  document.getElementById('check-none-camp').onclick = () => {
    document.querySelectorAll('.f-camp').forEach(e => { e.checked = false; });
    apply();
  };
  document.getElementById('check-all-camp').onclick = () => {
    document.querySelectorAll('.f-camp').forEach(e => { e.checked = true; });
    apply();
  };

  apply();
})();

window.siteLightbox = function (src) {
  document.getElementById('lbi').src = src;
  document.getElementById('lb').classList.add('open');
};
```

- [ ] **Step 2: Create the stylesheet**

Create `app/static/css/sites.css` (cartographer tokens are already defined in `index.css`, which `base.html` loads first; these rules layer on top):

```css
.survey-grid { display: grid; gap: 1rem;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); margin-top: 1rem; }
.survey-card { display: block; padding: 1rem 1.2rem; text-decoration: none;
  color: var(--ink, #1f2a23); background: var(--parchment, #f5efe1);
  border: 1px solid var(--rule, #cbbf9f); border-radius: 6px; }
.survey-card:hover { border-color: var(--rust, #a8451f); }
.survey-card h2 { margin: 0 0 0.3rem; font-size: 1.15rem; }
.survey-card p { margin: 0; color: var(--ink-soft, #4a5d4f); font-size: 0.88rem; }

.sites-page .sub { color: var(--ink-soft, #4a5d4f); margin: 0.2rem 0 0; font-size: 0.92rem; }

.filters { background: var(--parchment, #f5efe1); border: 1px solid var(--rule, #cbbf9f);
  border-radius: 6px; padding: 0.85rem 1rem; margin: 1rem 0;
  position: sticky; top: 0; z-index: 30; display: grid; gap: 0.7rem 1.2rem;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.filter-group label.title { display: block; font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--ink-soft, #4a5d4f); margin-bottom: 0.3rem; font-weight: 600; }
.filter-group .checks { display: flex; flex-wrap: wrap; gap: 0.3rem 0.7rem;
  max-height: 6rem; overflow-y: auto; padding-right: 0.3rem; }
.filter-group label.opt { font-size: 0.85rem; cursor: pointer; display: inline-flex;
  align-items: center; gap: 0.3rem; white-space: nowrap; }
.filter-group input[type="number"] { width: 5rem; padding: 0.25rem 0.4rem;
  border: 1px solid var(--rule, #cbbf9f); border-radius: 3px; }
.filter-group .range-row { display: flex; gap: 0.5rem; align-items: center; font-size: 0.85rem; }
.filter-group input[type="search"] { width: 100%; padding: 0.35rem 0.6rem;
  border: 1px solid var(--rule, #cbbf9f); border-radius: 3px; font: inherit; margin-top: 0.3rem; }
.actions { display: flex; gap: 0.5rem; align-items: center; grid-column: 1 / -1;
  padding-top: 0.3rem; border-top: 1px dashed var(--rule, #cbbf9f); }
.actions button { font: inherit; padding: 0.3rem 0.8rem; border: 1px solid var(--rule, #cbbf9f);
  border-radius: 3px; background: white; cursor: pointer; }
.actions button:hover { background: #f0efe9; }
.count { color: var(--ink-soft, #4a5d4f); font-size: 0.9rem; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 1rem; }
.site { background: var(--parchment, #f5efe1); border: 1px solid var(--rule, #cbbf9f);
  border-radius: 6px; overflow: hidden; display: flex; flex-direction: column; }
.site.hidden { display: none; }
.site .photos { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; background: var(--rule, #cbbf9f); }
.site .photos img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block;
  background: #ccc; cursor: zoom-in; }
.site .photos.single img { grid-column: 1 / -1; aspect-ratio: 16/9; }
.site .photos.empty { padding: 1.2rem 0; text-align: center; color: #888;
  background: #e6e2d8; font-size: 0.85rem; }
.site .body { padding: 0.7rem 0.9rem; }
.site h3 { margin: 0; font-size: 1.1rem; }
.site .area { color: var(--ink-soft, #4a5d4f); font-size: 0.82rem; }
.site dl { display: grid; grid-template-columns: auto 1fr; gap: 0.15rem 0.5rem;
  margin: 0.5rem 0 0; font-size: 0.82rem; }
.site dt { color: var(--ink-soft, #4a5d4f); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.68rem; align-self: center; }
.site dd { margin: 0; font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; }

.lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85);
  z-index: 1000; align-items: center; justify-content: center; cursor: zoom-out; }
.lightbox.open { display: flex; }
.lightbox img { max-width: 95vw; max-height: 95vh; object-fit: contain; }
```

- [ ] **Step 3: Commit**

```bash
git add app/static/js/site_search.js app/static/css/sites.css
git commit -m "feat(sites): client-side filter logic + stylesheet"
```

---

## Task 7: Home page navigation link

**Files:**
- Modify: `app/templates/index.html`
- Test: `tests/test_sites_routes.py` (add one assertion)

- [ ] **Step 1: Add a failing assertion for the home link**

Append to `tests/test_sites_routes.py`:

```python
def test_home_page_links_to_sites(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/sites"' in r.text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_sites_routes.py::test_home_page_links_to_sites -q`
Expected: FAIL — no `href="/sites"` in the home page yet.

- [ ] **Step 3: Add the link to the home header**

In `app/templates/index.html`, inside the `<div class="header-actions">` block, add this line immediately before the `<button class="btn" onclick="toggleNewTrip()">+ New Trip</button>` line:

```html
    <a class="btn btn-ghost" href="/sites" title="Browse campsite details &amp; photos">🔍 Campsite Search</a>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_sites_routes.py::test_home_page_links_to_sites -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/templates/index.html tests/test_sites_routes.py
git commit -m "feat(sites): link Campsite Search from the home header"
```

---

## Task 8: Full suite + Playwright verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass (the prior baseline plus the new sites tests).

- [ ] **Step 2: Start the server**

Run (background): `uvicorn app.main:app --port 8011`

- [ ] **Step 3: Playwright check of the live page**

Using the Playwright MCP tools:
1. Navigate to `http://localhost:8011/` and confirm the "🔍 Campsite Search" link is present in the header.
2. Click it / navigate to `http://localhost:8011/sites` and confirm the Balsam Lake card shows ~532 sites.
3. Navigate to `http://localhost:8011/sites/balsam-lake`.
4. Read the "N / 532 visible" count, uncheck every Privacy box except "Poor", and confirm the count drops.
5. Set the Site length max to the minimum bound and confirm the count drops further.
6. Click a site photo and confirm the lightbox opens; click it to close.
7. Click "Reset" and confirm the count returns to the full set.

Expected: counts update on every filter change; lightbox opens/closes; no console errors.

- [ ] **Step 4: Stop the server**

Stop the background `uvicorn` process.

- [ ] **Step 5: Final commit (if any verification tweaks were needed)**

```bash
git add -A
git commit -m "test(sites): verify campsite search end-to-end"
```

(If no tweaks were needed, skip this commit.)

---

## Self-Review Notes

- **Spec coverage:** data layer (Task 2), normalized JSON shape (Task 2/3), discovery service (Task 1), routes (Task 4), filter derivation (Task 1), templates/JS/CSS (Tasks 5-6), nav link (Task 7), Balsam migration (Task 3), tests + Playwright (all tasks + Task 8). Availability is intentionally excluded per spec.
- **Type consistency:** `compile_survey(resources, attr_defs, park_slug, park_name, pulled_on)`, `load_attr_defs(catalog_path)`, `attr_get(da, attr_defs)`, `list_surveys()`, `load_survey(slug)`, `derive_filters(sites)` are used identically wherever referenced. The JS lightbox is `window.siteLightbox` and the template calls `siteLightbox(...)`. Filter dict keys (`campgrounds`, `privacy`, `has_unrated`, `equipment`, `len_min`, `len_max`) match between `derive_filters`, the template, and the JS (`data-len-min`/`data-len-max`).
- **Ordering note:** Task 4's route tests go green only after Task 5 creates the templates; this is called out in Task 4 Step 4 and verified in Task 5 Step 3.
