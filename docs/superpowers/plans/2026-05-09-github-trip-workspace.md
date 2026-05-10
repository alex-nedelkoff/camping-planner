# GitHub Trip Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the camping-planner project from Google Drive/Sheets collaboration to a private GitHub repo with a markdown-first trip-doc workflow. Build a small `build_trip.py` generator that turns per-trip markdown into a self-contained HTML page. First real trip is Killarney 2026-05-15 → 2026-05-18.

**Architecture:** Existing Python tooling (ontario_parks.py, weather.py, route_map.py) stays unchanged. A new `build_trip.py` reads a trip directory of markdown files (with YAML frontmatter in `trip.md`), composes them with weather and route data, and writes `trip.html`. Markdown is the source of truth; HTML is regenerated from it. Obsolete artifacts move to `legacy/`. Repo is private; collaborator `pizza-zip` joins via `gh api` invite.

**Tech Stack:** Python 3 (`markdown` for rendering, `pyyaml` for frontmatter, `pytest` for tests), git, GitHub CLI (`gh`).

**Spec:** `docs/superpowers/specs/2026-05-09-github-trip-workspace-design.md`

---

## File Structure

**New files (in repo root):**
- `build_trip.py` — markdown-to-HTML trip page generator (~250 lines, single file)
- `tests/test_build_trip.py` — pytest tests for the generator
- `tests/__init__.py` — empty, makes `tests/` a package

**New folders:**
- `legacy/` — obsolete Sheet-flow artifacts moved here in Task 1
- `templates/trip-template/` — six markdown skeletons + `route-placeholder.md` (none — just the six)
- `trips/killarney-2026-05/` — first real trip
- `tests/fixtures/sample-trip/` — pytest fixture, a tiny valid trip dir

**Modified files:**
- `requirements.txt` — add markdown, pyyaml, pytest
- `README.md` — rewrite for the new collab workflow
- `.gitignore` — new file (project is currently not a git repo)

**Files moved into `legacy/` in Task 1:**
- `trip_planner.py`, `trip_killarney_jul10.html`, `sample_resources_killarney.json`,
  `sample_resources_killarney.xlsx`, `sample_resources_killarney_clean.csv`,
  `download.html`, `GOOGLE_FORM_SETUP.md`

**Files deliberately NOT modified:**
- `ontario_parks.py`, `weather.py`, `route_map.py`, `parks.json`, `park_activities.json`,
  `api_attribute_filterable.json`, `map_names_cache.json`, `CLAUDE.md`

---

## Task 1: Initialize git repo, write .gitignore, reorganize legacy files

**Files:**
- Create: `/Users/alex/Documents/camping-planner/.gitignore`
- Move (7 files): see list below
- Init: git repo in `/Users/alex/Documents/camping-planner`

- [ ] **Step 1: Initialize the git repo**

```bash
cd /Users/alex/Documents/camping-planner
git init
git branch -M main
```

Expected: `Initialized empty Git repository in /Users/alex/Documents/camping-planner/.git/` (and rename of master to main if applicable).

- [ ] **Step 2: Write .gitignore**

Create `/Users/alex/Documents/camping-planner/.gitignore` with this exact content:

```
__pycache__/
*.pyc
.venv/
.DS_Store
private/
*.local.md
.pytest_cache/
```

- [ ] **Step 3: Create legacy/ and move obsolete files**

```bash
cd /Users/alex/Documents/camping-planner
mkdir legacy
git mv -k trip_planner.py legacy/ 2>/dev/null || mv trip_planner.py legacy/
mv trip_killarney_jul10.html legacy/
mv sample_resources_killarney.json legacy/
mv sample_resources_killarney.xlsx legacy/
mv sample_resources_killarney_clean.csv legacy/
mv download.html legacy/
mv GOOGLE_FORM_SETUP.md legacy/
```

(Plain `mv` is fine here since the repo is empty of history — there's nothing to preserve through `git mv`.)

- [ ] **Step 4: Verify the move and the working tree**

Run: `ls /Users/alex/Documents/camping-planner/`
Expected to see: `CLAUDE.md`, `README.md`, `api_attribute_filterable.json`, `build_trip.py` (no — not yet), `docs/`, `legacy/`, `map_names_cache.json`, `ontario_parks.py`, `park_activities.json`, `parks.json`, `requirements.txt`, `route_map.py`, `weather.py`.

Run: `ls /Users/alex/Documents/camping-planner/legacy/`
Expected: 7 files listed in Step 3.

- [ ] **Step 5: Initial commit**

```bash
cd /Users/alex/Documents/camping-planner
git add .gitignore
git add CLAUDE.md README.md requirements.txt
git add ontario_parks.py weather.py route_map.py
git add parks.json park_activities.json api_attribute_filterable.json map_names_cache.json
git add legacy/
git add docs/
git commit -m "chore: initialize repo, move obsolete artifacts to legacy/"
```

Expected: commit succeeds with files listed.

---

## Task 2: Add trip template skeleton

**Files:**
- Create: `templates/trip-template/trip.md`
- Create: `templates/trip-template/itinerary.md`
- Create: `templates/trip-template/gear.md`
- Create: `templates/trip-template/food.md`
- Create: `templates/trip-template/packing.md`
- Create: `templates/trip-template/costs.md`

- [ ] **Step 1: Create the template directory**

```bash
mkdir -p /Users/alex/Documents/camping-planner/templates/trip-template
```

- [ ] **Step 2: Write `templates/trip-template/trip.md`**

```markdown
---
park: park-slug-here
start_date: YYYY-MM-DD
end_date: YYYY-MM-DD
participants:
  - Name 1
  - Name 2
meeting_point: Where you meet up before driving
access_point: Park access point name
nights:
  - date: YYYY-MM-DD
    site: Site number or name
    location: Lake or area
---

# Trip name

Free-form intro. What's the goal of the trip, anything special, who suggested it.
```

- [ ] **Step 3: Write `templates/trip-template/itinerary.md`**

```markdown
## Day 1 — Friday

- 06:00 — depart Ajax
- 10:30 — arrive at access point
- 11:00 — launch
- 16:00 — arrive at site, set up camp

## Day 2 — Saturday

## Day 3 — Sunday

## Day 4 — Monday — return
```

- [ ] **Step 4: Write `templates/trip-template/gear.md`**

```markdown
## Shared gear

| Item | Who's bringing | Notes |
|---|---|---|
| Canoe | | |
| Paddles | | |
| PFDs | | |
| Tarp | | |
| Stove + fuel | | |
| Water filter | | |
| First aid kit | | |
| Map + compass | | |

## Personal gear

Each person brings their own — see `packing.md`.
```

- [ ] **Step 5: Write `templates/trip-template/food.md`**

```markdown
## Friday dinner

- _meal idea_ — _who's bringing_

## Saturday breakfast

## Saturday lunch

## Saturday dinner

## Sunday breakfast

## Sunday lunch

## Sunday dinner

## Monday breakfast
```

- [ ] **Step 6: Write `templates/trip-template/packing.md`**

```markdown
## Shelter & sleep

- [ ] Tent
- [ ] Sleeping bag
- [ ] Sleeping pad
- [ ] Pillow / stuff sack

## Kitchen

- [ ] Stove
- [ ] Fuel canister
- [ ] Pot / pan
- [ ] Lighter / matches
- [ ] Bowl + utensils
- [ ] Water bottles

## Clothing

- [ ] Rain jacket
- [ ] Warm layer (fleece/down)
- [ ] Quick-dry shirts
- [ ] Quick-dry pants/shorts
- [ ] Wool socks
- [ ] Camp shoes
- [ ] Hat

## Personal

- [ ] Headlamp + spare batteries
- [ ] Toothbrush + toothpaste
- [ ] Sunscreen
- [ ] Bug spray
- [ ] Personal meds
- [ ] Phone charger / power bank

## Paddling

- [ ] PFD
- [ ] Dry bag
- [ ] Quick-dry towel
```

- [ ] **Step 7: Write `templates/trip-template/costs.md`**

```markdown
| Item | Who paid | Amount |
|---|---|---|
| Permit / reservation | | |
| Gas | | |
| Groceries | | |

**Total per person:**
```

- [ ] **Step 8: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add templates/
git commit -m "feat: add trip template skeleton"
```

---

## Task 3: Add Python dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Read current requirements.txt**

Current contents (verified):
```
requests>=2.31.0
playwright>=1.40.0
```

- [ ] **Step 2: Append new dependencies**

Append to `/Users/alex/Documents/camping-planner/requirements.txt` so the final file reads:

```
requests>=2.31.0
playwright>=1.40.0
markdown==3.7
pyyaml==6.0.2
pytest>=8.0.0
```

The pinned versions for `markdown` and `pyyaml` are intentional — both you and pizza-zip should render identically.

- [ ] **Step 3: Install**

```bash
cd /Users/alex/Documents/camping-planner
pip install -r requirements.txt
```

Expected: installs `markdown-3.7`, `pyyaml-6.0.2`, `pytest>=8.0.0` (others already present).

- [ ] **Step 4: Verify imports**

```bash
python3 -c "import markdown, yaml, pytest; print(markdown.__version__, yaml.__version__, pytest.__version__)"
```

Expected: prints three version strings, no ImportError.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "chore: add markdown, pyyaml, pytest dependencies"
```

---

## Task 4: build_trip.py — `load_trip()` (TDD)

Loads a trip directory: parses YAML frontmatter from `trip.md`, reads the five section markdown files, detects an optional route file.

**Files:**
- Create: `build_trip.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_build_trip.py`

- [ ] **Step 1: Create the test file with three failing tests**

Create `/Users/alex/Documents/camping-planner/tests/__init__.py` as empty.

Create `/Users/alex/Documents/camping-planner/tests/test_build_trip.py`:

```python
"""Tests for build_trip.py."""
from pathlib import Path

import pytest

from build_trip import load_trip


def _write_minimal_trip(trip_dir: Path) -> None:
    """Create a minimal valid trip directory at trip_dir."""
    trip_dir.mkdir(parents=True, exist_ok=True)
    (trip_dir / "trip.md").write_text(
        "---\n"
        "park: killarney\n"
        "start_date: 2026-05-15\n"
        "end_date: 2026-05-18\n"
        "participants:\n"
        "  - Alex\n"
        "  - Friend\n"
        "nights:\n"
        "  - date: 2026-05-15\n"
        "    site: '61'\n"
        "    location: OSA Lake\n"
        "---\n"
        "\n"
        "Intro text body.\n"
    )
    (trip_dir / "itinerary.md").write_text("## Day 1\n\nPaddle.\n")
    (trip_dir / "gear.md").write_text("Gear list.\n")
    (trip_dir / "food.md").write_text("")
    (trip_dir / "packing.md").write_text("- [ ] Tent\n")
    (trip_dir / "costs.md").write_text("")


def test_load_trip_parses_frontmatter_and_sections(tmp_path):
    trip_dir = tmp_path / "test-trip"
    _write_minimal_trip(trip_dir)

    result = load_trip(trip_dir)

    assert result["frontmatter"]["park"] == "killarney"
    assert result["frontmatter"]["start_date"] == "2026-05-15"
    assert result["frontmatter"]["participants"] == ["Alex", "Friend"]
    assert result["frontmatter"]["nights"][0]["site"] == "61"
    assert result["frontmatter"]["nights"][0]["location"] == "OSA Lake"
    assert "Intro text body." in result["intro"]
    assert "Paddle." in result["itinerary"]
    assert "- [ ] Tent" in result["packing"]
    assert result["route_file"] is None


def test_load_trip_picks_up_gpx_route(tmp_path):
    trip_dir = tmp_path / "test-trip"
    _write_minimal_trip(trip_dir)
    (trip_dir / "route.gpx").write_text("<gpx></gpx>")

    result = load_trip(trip_dir)

    assert result["route_file"] is not None
    assert result["route_file"].name == "route.gpx"


def test_load_trip_prefers_gpx_over_kml(tmp_path):
    trip_dir = tmp_path / "test-trip"
    _write_minimal_trip(trip_dir)
    (trip_dir / "route.gpx").write_text("<gpx></gpx>")
    (trip_dir / "route.kml").write_text("<kml></kml>")

    result = load_trip(trip_dir)

    assert result["route_file"].name == "route.gpx"


def test_load_trip_raises_on_missing_frontmatter(tmp_path):
    trip_dir = tmp_path / "test-trip"
    trip_dir.mkdir()
    (trip_dir / "trip.md").write_text("No frontmatter here.\n")
    for n in ("itinerary", "gear", "food", "packing", "costs"):
        (trip_dir / f"{n}.md").write_text("")

    with pytest.raises(ValueError, match="frontmatter"):
        load_trip(trip_dir)
```

- [ ] **Step 2: Run tests to verify they fail (no module yet)**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_build_trip.py -v
```

Expected: 4 tests fail with `ModuleNotFoundError: No module named 'build_trip'`.

- [ ] **Step 3: Implement `load_trip()` — create `build_trip.py`**

Create `/Users/alex/Documents/camping-planner/build_trip.py`:

```python
"""
Generate a self-contained trip HTML page from a directory of markdown files.

Usage: python3 build_trip.py trips/<trip-name>/
"""
import re
from pathlib import Path

import yaml

SECTION_FILES = ["itinerary", "gear", "food", "packing", "costs"]
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)


def load_trip(trip_dir) -> dict:
    """Parse a trip directory.

    Returns dict with keys:
      frontmatter (dict from trip.md YAML),
      intro (str, markdown body of trip.md after frontmatter),
      itinerary, gear, food, packing, costs (str, markdown content),
      route_file (Path or None — prefers route.gpx over route.kml).
    """
    trip_dir = Path(trip_dir)
    trip_md_path = trip_dir / "trip.md"
    trip_md = trip_md_path.read_text()

    match = FRONTMATTER_RE.match(trip_md)
    if not match:
        raise ValueError(f"{trip_md_path}: missing YAML frontmatter")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    intro = match.group(2).strip()

    sections = {}
    for name in SECTION_FILES:
        path = trip_dir / f"{name}.md"
        sections[name] = path.read_text() if path.exists() else ""

    route_file = None
    for ext in ("gpx", "kml"):
        candidate = trip_dir / f"route.{ext}"
        if candidate.exists():
            route_file = candidate
            break

    return {
        "frontmatter": frontmatter,
        "intro": intro,
        "route_file": route_file,
        **sections,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_build_trip.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add build_trip.py tests/__init__.py tests/test_build_trip.py
git commit -m "feat: add load_trip() to parse trip directories"
```

---

## Task 5: build_trip.py — `render_section()` with task-list checkboxes (TDD)

Renders a single markdown section to HTML, converting `- [ ]` / `- [x]` into real `<input type="checkbox">` elements with stable `data-cb-key` attributes for localStorage persistence.

**Files:**
- Modify: `build_trip.py`
- Modify: `tests/test_build_trip.py`

- [ ] **Step 1: Append failing tests**

Append to `/Users/alex/Documents/camping-planner/tests/test_build_trip.py`:

```python
from build_trip import render_section


def test_render_section_converts_unchecked_task_to_checkbox():
    md = "- [ ] First item\n"
    html = render_section(md, "packing")
    assert 'type="checkbox"' in html
    assert 'data-cb-key="packing--first-item"' in html
    # Unchecked must NOT include the literal " checked" attribute.
    assert " checked" not in html


def test_render_section_converts_checked_task_to_checkbox():
    md = "- [x] Done item\n"
    html = render_section(md, "packing")
    assert 'data-cb-key="packing--done-item"' in html
    assert "checked" in html


def test_render_section_renders_tables():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    html = render_section(md, "gear")
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_render_section_handles_headings_and_paragraphs():
    md = "## Hello\n\nA paragraph.\n"
    html = render_section(md, "intro")
    assert "<h2>Hello</h2>" in html
    assert "<p>A paragraph.</p>" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_build_trip.py -v
```

Expected: 4 new tests fail with `ImportError: cannot import name 'render_section' from 'build_trip'`. The earlier 4 tests still pass.

- [ ] **Step 3: Implement `render_section()`**

Add these imports at the top of `build_trip.py` (under existing imports):

```python
from html import escape

import markdown as _md
```

Add these constants/functions to `build_trip.py` (after `load_trip`):

```python
TASK_LINE_RE = re.compile(
    r"^(?P<prefix>\s*[-*+]\s+)\[(?P<mark>[ xX])\]\s+(?P<label>.+)$",
    re.MULTILINE,
)


def _slugify(text: str) -> str:
    """Lowercase, replace non-alphanumerics with hyphens, trim hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def render_section(md_text: str, section_id: str) -> str:
    """Render markdown to HTML. Task-list items become persistent checkboxes."""
    def replace(match):
        prefix = match.group("prefix")
        mark = match.group("mark")
        label = match.group("label")
        checked = "checked" if mark in "xX" else ""
        key = f"{section_id}--{_slugify(label)}"
        attrs = f'type="checkbox" data-cb-key="{escape(key)}"'
        if checked:
            attrs += " checked"
        return f"{prefix}<input {attrs}> {label}"

    processed = TASK_LINE_RE.sub(replace, md_text)
    return _md.markdown(processed, extensions=["tables", "fenced_code"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_build_trip.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add build_trip.py tests/test_build_trip.py
git commit -m "feat: render markdown sections with persistent task checkboxes"
```

---

## Task 6: build_trip.py — weather and route map integration

Integration code that calls existing `weather.py` and `route_map.py`. No unit tests (network calls; integration-tested by the smoke test in Task 10).

**Files:**
- Modify: `build_trip.py`

- [ ] **Step 1: Add weather widget renderer**

First, add these two imports to the top of `build_trip.py` alongside the existing imports:

```python
import weather as _weather
import route_map as _route_map
```

Then add this function definition after `render_section`:

```python
def render_weather_section(park_slug: str, start_date: str, end_date: str) -> str:
    """Render the weather widget HTML using weather.get_weather()."""
    data = _weather.get_weather(
        park_key=park_slug, start_date=start_date, end_date=end_date,
    )
    if data["source"] == "unavailable" or not data["days"]:
        return '<section id="weather"><h2>Weather</h2><p>Weather data unavailable.</p></section>'

    label = "Forecast" if data["source"] == "forecast" else "Historical averages"
    rows = []
    for day in data["days"]:
        chance = ""
        if day.get("precip_chance") is not None:
            chance = f"{day['precip_chance']}% rain"
        elif day.get("precip_mm", 0) > 0:
            chance = f"~{day['precip_mm']}mm"
        rows.append(
            f"<tr><td>{day['date']}</td>"
            f"<td>{day.get('icon', '')} {day.get('description', '')}</td>"
            f"<td>{day['high']}&deg;C / {day['low']}&deg;C</td>"
            f"<td>{chance}</td></tr>"
        )

    return (
        '<section id="weather"><h2>Weather</h2>'
        f"<p><em>{label}</em></p>"
        '<table><thead><tr><th>Date</th><th>Conditions</th>'
        '<th>High / Low</th><th>Precip</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )
```

- [ ] **Step 2: Add route map renderer**

Add to `build_trip.py`:

```python
def render_route_section(route_file) -> str:
    """Render the route map section, or empty string if no route file."""
    if route_file is None:
        return ""
    data = _route_map.parse_route_file(str(route_file))
    return _route_map.generate_map_section(data)
```

- [ ] **Step 3: Sanity check imports**

```bash
cd /Users/alex/Documents/camping-planner
python3 -c "import build_trip; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Re-run unit tests (should still pass — no behavior change to existing functions)**

```bash
python3 -m pytest tests/test_build_trip.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add build_trip.py
git commit -m "feat: add weather widget and route map integration"
```

---

## Task 7: build_trip.py — full HTML assembler + CLI (integration TDD)

Stitches everything into a single self-contained HTML file and exposes a CLI.

**Files:**
- Modify: `build_trip.py`
- Modify: `tests/test_build_trip.py`
- Create: `tests/fixtures/sample-trip/` (six markdown files)

- [ ] **Step 1: Create the fixture trip directory**

```bash
mkdir -p /Users/alex/Documents/camping-planner/tests/fixtures/sample-trip
```

Create `tests/fixtures/sample-trip/trip.md`:

```markdown
---
park: killarney
start_date: 2026-05-15
end_date: 2026-05-18
participants:
  - Alex
  - Friend
access_point: George Lake
nights:
  - date: 2026-05-15
    site: '61'
    location: OSA Lake
---

Welcome to the test trip.
```

Create `tests/fixtures/sample-trip/itinerary.md`:

```markdown
## Day 1

Paddle to OSA.
```

Create `tests/fixtures/sample-trip/gear.md`:

```markdown
| Item | Who |
|---|---|
| Canoe | Alex |
```

Create `tests/fixtures/sample-trip/food.md`:

```markdown
## Friday dinner

Pasta — Friend
```

Create `tests/fixtures/sample-trip/packing.md`:

```markdown
- [ ] Tent
- [x] Stove
```

Create `tests/fixtures/sample-trip/costs.md`:

```markdown
| Item | Amount |
|---|---|
| Permit | $50 |
```

- [ ] **Step 2: Append integration test**

Append to `/Users/alex/Documents/camping-planner/tests/test_build_trip.py`:

```python
from unittest.mock import patch

from build_trip import build_html


_FAKE_WEATHER = {
    "source": "forecast",
    "days": [
        {
            "date": "2026-05-15",
            "high": 18.0,
            "low": 5.0,
            "precip_mm": 0.0,
            "precip_chance": 10,
            "code": 1,
            "description": "Mainly clear",
            "icon": "☀️",
        }
    ],
}


def test_build_html_assembles_full_page():
    fixture = Path(__file__).parent / "fixtures" / "sample-trip"
    with patch("build_trip._weather.get_weather", return_value=_FAKE_WEATHER):
        html = build_html(fixture)

    # Sections present in expected order.
    for marker in ("Welcome to the test trip", "Day 1", "Canoe", "Friday dinner",
                   "Tent", "Permit"):
        assert marker in html, f"missing: {marker}"

    # Weather table populated from the mocked data.
    assert "Mainly clear" in html
    assert "18" in html and "5" in html

    # Frontmatter rendered into header.
    assert "Killarney" in html or "killarney" in html
    assert "2026-05-15" in html
    assert "Alex" in html

    # Task list became real checkboxes with stable keys.
    assert 'type="checkbox"' in html
    assert 'data-cb-key="packing--tent"' in html
    assert 'data-cb-key="packing--stove"' in html

    # Self-contained: contains its own <style> and <script> blocks.
    assert "<style>" in html
    assert "<script>" in html

    # No route file in fixture → no map section.
    assert "Route Map" not in html
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_build_trip.py::test_build_html_assembles_full_page -v
```

Expected: fails with `ImportError: cannot import name 'build_html' from 'build_trip'`.

- [ ] **Step 4: Implement `build_html()` and `main()`**

Append to `/Users/alex/Documents/camping-planner/build_trip.py`:

```python
import argparse
import json
import sys


_PAGE_CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       max-width: 900px; margin: 0 auto; padding: 1.5rem; color: #222;
       line-height: 1.55; background: #fafafa; }
h1, h2, h3 { color: #1f3a3a; }
h1 { border-bottom: 3px solid #2d5016; padding-bottom: 0.3rem; }
section { background: white; padding: 1.25rem 1.5rem; margin: 1rem 0;
          border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
table { width: 100%; border-collapse: collapse; margin: 0.5rem 0; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }
th { background: #f0f4ee; }
input[type=checkbox] { margin-right: 0.5rem; transform: scale(1.2); }
.trip-header { background: #2d5016; color: white; padding: 1.5rem 1.5rem 1rem;
               border-radius: 10px; margin-bottom: 1rem; }
.trip-header h1 { color: white; border-bottom: none; margin: 0 0 0.5rem; }
.trip-meta { display: flex; gap: 1.5rem; flex-wrap: wrap; opacity: 0.95; }
@media print { body { background: white; } section { box-shadow: none; } }
"""

_PAGE_JS = """
(function() {
  document.querySelectorAll('input[type=checkbox][data-cb-key]').forEach(function(cb) {
    var key = 'cb:' + cb.dataset.cbKey;
    var saved = localStorage.getItem(key);
    if (saved === '1') cb.checked = true;
    if (saved === '0') cb.checked = false;
    cb.addEventListener('change', function() {
      localStorage.setItem(key, cb.checked ? '1' : '0');
    });
  });
})();
"""


def _load_park_info(park_slug: str) -> dict:
    """Look up park name + drive time from parks.json. Returns {} if not found."""
    repo_root = Path(__file__).parent
    parks_path = repo_root / "parks.json"
    if not parks_path.exists():
        return {}
    data = json.loads(parks_path.read_text())
    return data.get("parks", {}).get(park_slug, {})


def _render_header(fm: dict) -> str:
    park_info = _load_park_info(fm.get("park", ""))
    park_name = park_info.get("name", fm.get("park", "Trip"))
    drive = park_info.get("driveFromAjax", "")
    participants = ", ".join(fm.get("participants", []) or [])
    nights_rows = ""
    for night in fm.get("nights", []) or []:
        nights_rows += (
            f"<tr><td>{night.get('date', '')}</td>"
            f"<td>{night.get('site', '')}</td>"
            f"<td>{night.get('location', '')}</td></tr>"
        )
    nights_table = ""
    if nights_rows:
        nights_table = (
            '<table><thead><tr><th>Date</th><th>Site</th><th>Location</th>'
            f"</tr></thead><tbody>{nights_rows}</tbody></table>"
        )
    return (
        '<header class="trip-header">'
        f'<h1>{park_name} &middot; {fm.get("start_date", "")} → '
        f'{fm.get("end_date", "")}</h1>'
        '<div class="trip-meta">'
        f'<span><strong>Participants:</strong> {participants}</span>'
        + (f'<span><strong>Access:</strong> {fm.get("access_point", "")}</span>'
           if fm.get("access_point") else "")
        + (f'<span><strong>Drive from Ajax:</strong> {drive}</span>'
           if drive else "")
        + '</div>'
        + nights_table
        + '</header>'
    )


def build_html(trip_dir) -> str:
    """Build the full self-contained HTML page for a trip directory."""
    trip = load_trip(trip_dir)
    fm = trip["frontmatter"]

    sections_html = []
    if trip["intro"]:
        sections_html.append(
            f'<section id="intro">{render_section(trip["intro"], "intro")}</section>'
        )
    sections_html.append(
        f'<section id="itinerary"><h2>Itinerary</h2>'
        f'{render_section(trip["itinerary"], "itinerary")}</section>'
    )
    sections_html.append(render_route_section(trip["route_file"]))
    sections_html.append(render_weather_section(
        fm.get("park", ""), fm.get("start_date", ""), fm.get("end_date", ""),
    ))
    sections_html.append(
        f'<section id="gear"><h2>Gear</h2>'
        f'{render_section(trip["gear"], "gear")}</section>'
    )
    sections_html.append(
        f'<section id="food"><h2>Food</h2>'
        f'{render_section(trip["food"], "food")}</section>'
    )
    sections_html.append(
        f'<section id="packing"><h2>Packing</h2>'
        f'{render_section(trip["packing"], "packing")}</section>'
    )
    sections_html.append(
        f'<section id="costs"><h2>Costs</h2>'
        f'{render_section(trip["costs"], "costs")}</section>'
    )

    body = _render_header(fm) + "\n".join(s for s in sections_html if s)
    title = (
        f'{_load_park_info(fm.get("park", "")).get("name", "Trip")} '
        f'{fm.get("start_date", "")}'
    )
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title>'
        f'<style>{_PAGE_CSS}</style>'
        '</head><body>'
        f'{body}'
        f'<script>{_PAGE_JS}</script>'
        '</body></html>'
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trip_dir", help="Path to trip directory (contains trip.md)")
    args = parser.parse_args(argv)

    trip_dir = Path(args.trip_dir)
    html = build_html(trip_dir)
    out_path = trip_dir / "trip.html"
    out_path.write_text(html)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run all tests**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m pytest tests/test_build_trip.py -v
```

Expected: 9 tests pass (the 8 previous + the new integration test).

- [ ] **Step 6: Commit**

```bash
git add build_trip.py tests/test_build_trip.py tests/fixtures/
git commit -m "feat: assemble full trip HTML and add CLI"
```

---

## Task 8: Rewrite README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README with collab-focused content**

Overwrite `/Users/alex/Documents/camping-planner/README.md` with:

```markdown
# camping-planner

Shared trip planning for canoe and camping trips with friends. Markdown is the
source of truth; a small Python script generates a self-contained HTML page
per trip.

## Quick start

```bash
git clone git@github.com:alex-nedelkoff/camping-planner.git
cd camping-planner
pip install -r requirements.txt
```

## Editing a trip

1. `cd trips/<trip-name>/`
2. Edit any of `trip.md`, `itinerary.md`, `gear.md`, `food.md`, `packing.md`,
   `costs.md` in your editor.
3. `git pull --rebase && git commit -am "..." && git push`.

GitHub renders `.md` files when you click them on github.com — no build step
needed for the markdown.

## Previewing the HTML

The repo is private, so `htmlpreview.github.io` doesn't work. Run a local
server instead:

```bash
python3 -m http.server
```

Then open `http://localhost:8000/trips/<trip-name>/trip.html`.

## Regenerating the HTML

After editing markdown, regenerate the trip page:

```bash
python3 build_trip.py trips/<trip-name>/
```

Commit both the markdown changes and the regenerated `trip.html`.

## Starting a new trip

```bash
cp -r templates/trip-template trips/<new-trip-name>/
$EDITOR trips/<new-trip-name>/trip.md  # fill in frontmatter
python3 build_trip.py trips/<new-trip-name>/
git add trips/<new-trip-name>/
git commit -m "feat: add <new-trip-name>"
```

## Sensitive content

Anything you don't want committed (phone numbers, emergency contacts,
satellite-messenger PINs) goes in:

- `private/` — gitignored top-level folder
- `*.local.md` — gitignored anywhere

Both you and your collaborator sync these out-of-band.

## Park availability checks

Use the existing tooling against the Ontario Parks API:

```bash
python3 ontario_parks.py check killarney --start 2026-05-15 --end 2026-05-18
```

See `CLAUDE.md` for the full API reference, including rate-limit warnings.

## Repo layout

- `build_trip.py` — markdown → HTML trip page generator
- `ontario_parks.py` — Ontario Parks availability checks
- `weather.py`, `route_map.py` — used by `build_trip.py`
- `parks.json`, `park_activities.json` — park metadata
- `templates/trip-template/` — copy this to start a new trip
- `trips/` — one folder per trip
- `legacy/` — older Sheet-driven flow, kept for reference
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for the new GitHub workflow"
```

---

## Task 9: Create the Killarney trip from the template

**Files:**
- Create: `trips/killarney-2026-05/trip.md`
- Create: `trips/killarney-2026-05/itinerary.md`
- Create: `trips/killarney-2026-05/gear.md`
- Create: `trips/killarney-2026-05/food.md`
- Create: `trips/killarney-2026-05/packing.md`
- Create: `trips/killarney-2026-05/costs.md`

- [ ] **Step 1: Copy the template**

```bash
cd /Users/alex/Documents/camping-planner
mkdir -p trips
cp -r templates/trip-template trips/killarney-2026-05
```

- [ ] **Step 2: Fill in `trips/killarney-2026-05/trip.md`**

Replace the contents with:

```markdown
---
park: killarney
start_date: 2026-05-15
end_date: 2026-05-18
participants:
  - Alex
  - pizza-zip
access_point: George Lake
nights:
  - date: 2026-05-15
    site: '61'
    location: OSA Lake
  - date: 2026-05-16
    site: '82'
    location: Baie Fine
  - date: 2026-05-17
    site: '12'
    location: Killarney Lake
---

# Killarney 2026-05-15 → 2026-05-18

3-night interior canoe trip in Killarney Provincial Park. George Lake put-in,
moving sites each day: OSA Lake → Baie Fine → Killarney Lake → back to George
Lake on Monday. La Cloche white quartzite ridges, deep clear lakes, classic
Group of Seven country.
```

- [ ] **Step 3: Fill in `trips/killarney-2026-05/itinerary.md`**

Replace contents with:

```markdown
## Friday 2026-05-15 — Day 1

- Depart Ajax in the morning (~5h drive to George Lake access)
- Permit pickup at George Lake park office
- Launch from George Lake
- Portage / paddle into Killarney Lake then north to OSA Lake
- Camp: site 61, OSA Lake

## Saturday 2026-05-16 — Day 2

- Pack up, paddle south back through Killarney Lake
- Three Narrows portage into Baie Fine
- Camp: site 82, Baie Fine

## Sunday 2026-05-17 — Day 3

- Pack up, paddle / portage back into Killarney Lake
- Camp: site 12, Killarney Lake

## Monday 2026-05-18 — Day 4

- Pack up, paddle out to George Lake access
- Drive home to Ajax
```

- [ ] **Step 4: Fill in `trips/killarney-2026-05/gear.md`**

Replace contents with:

```markdown
## Shared gear

| Item | Who's bringing | Notes |
|---|---|---|
| Canoe (rental?) | TBD | confirm with George Lake outfitter if renting |
| Paddles (2-3) | | |
| PFDs (2) | | |
| Throw bag | | |
| Tarp + ridgeline | | |
| Stove + fuel | | |
| Cookpot + lid | | |
| Water filter / pump | | |
| Bear barrel or hang rope | | mandatory in Killarney interior |
| First aid kit | | |
| Map (waterproof) + compass | | Chrismar Killarney recommended |
| Lighter + matches in dry bag | | |
| Repair kit (duct tape, multitool) | | |

## Personal gear

Each person brings their own — see `packing.md`.
```

- [ ] **Step 5: Fill in `trips/killarney-2026-05/food.md`**

Replace contents with:

```markdown
3 breakfasts, 3 lunches, 3 dinners. Backcountry — no cooler, weight matters.

## Friday dinner

- _meal idea_ — _who_

## Saturday breakfast

## Saturday lunch

(On the water — wraps / bars / cheese.)

## Saturday dinner

## Sunday breakfast

## Sunday lunch

## Sunday dinner

## Monday breakfast

(Quick — break camp and paddle out.)
```

- [ ] **Step 6: Leave packing.md and costs.md as the template defaults**

(Already populated by the `cp -r` in Step 1.)

- [ ] **Step 7: Commit**

```bash
cd /Users/alex/Documents/camping-planner
git add trips/killarney-2026-05/
git commit -m "feat: scaffold Killarney 2026-05-15 trip from template"
```

---

## Task 10: Render the Killarney trip.html and smoke test

**Files:**
- Create: `trips/killarney-2026-05/trip.html`

- [ ] **Step 1: Run the generator**

```bash
cd /Users/alex/Documents/camping-planner
python3 build_trip.py trips/killarney-2026-05/
```

Expected: prints `Wrote trips/killarney-2026-05/trip.html`. May take 1-2 seconds for the weather API call. Trip starts 2026-05-15, today is 2026-05-09 → 6 days out → forecast (not historical).

- [ ] **Step 2: Verify the file exists and has expected content**

```bash
test -f trips/killarney-2026-05/trip.html && echo "exists: $(wc -l < trips/killarney-2026-05/trip.html) lines"
grep -q "OSA Lake" trips/killarney-2026-05/trip.html && echo "OSA Lake: ok"
grep -q "Killarney" trips/killarney-2026-05/trip.html && echo "Killarney: ok"
grep -q 'type="checkbox"' trips/killarney-2026-05/trip.html && echo "checkboxes: ok"
grep -q "Forecast\|Historical" trips/killarney-2026-05/trip.html && echo "weather: ok"
```

Expected: 5 lines printed, all confirming.

- [ ] **Step 3: Smoke-test in a browser**

```bash
cd /Users/alex/Documents/camping-planner
python3 -m http.server 8000 &
sleep 1
open "http://localhost:8000/trips/killarney-2026-05/trip.html"
```

Manually verify:
- Header shows park name, dates, participants, drive time, and the per-night
  table (3 rows: OSA / Baie Fine / Killarney Lake).
- Weather section has a table with at least one row.
- Itinerary, Gear, Food, Packing, Costs sections all render.
- Packing section has clickable checkboxes; clicking one and reloading the
  page keeps it checked.
- No broken layout / no JS errors in the browser console.

When done: `kill %1` to stop the http.server.

- [ ] **Step 4: Commit the rendered HTML**

```bash
cd /Users/alex/Documents/camping-planner
git add trips/killarney-2026-05/trip.html
git commit -m "feat: render Killarney trip HTML"
```

---

## Task 11: Create private GitHub repo and push

**External state change** — creates a new GitHub repo under `alex-nedelkoff`. Easily reversible via `gh repo delete alex-nedelkoff/camping-planner --yes` if needed.

- [ ] **Step 1: Verify gh CLI is authenticated as alex-nedelkoff**

```bash
gh auth status
```

Expected: shows `alex-nedelkoff` as the active account with `repo` scope.

- [ ] **Step 2: Create the repo and push main**

```bash
cd /Users/alex/Documents/camping-planner
gh repo create alex-nedelkoff/camping-planner --private --source=. --push --description "Shared trip planning for canoe and camping trips"
```

Expected: prints the repo URL like `https://github.com/alex-nedelkoff/camping-planner`. The `--push` flag pushes the existing `main` branch.

- [ ] **Step 3: Verify push**

```bash
gh repo view alex-nedelkoff/camping-planner
git log --oneline origin/main | head -10
```

Expected: repo metadata prints; `git log` shows all the commits from Tasks 1-10.

---

## Task 12: Invite pizza-zip as a collaborator

**External state change** — sends an email invite to pizza-zip. Reversible via `gh api -X DELETE repos/alex-nedelkoff/camping-planner/collaborators/pizza-zip`.

- [ ] **Step 1: Send the invite**

```bash
gh api -X PUT repos/alex-nedelkoff/camping-planner/collaborators/pizza-zip -f permission=push
```

Expected: returns a JSON object with the invitation details (a 201 response). pizza-zip will receive an email and a notification on github.com.

- [ ] **Step 2: Confirm the invite is pending**

```bash
gh api repos/alex-nedelkoff/camping-planner/invitations
```

Expected: lists at least one invitation with `invitee.login = "pizza-zip"` and `permissions = "write"`.

- [ ] **Step 3: Notify the user**

Tell the user: the repo is at `https://github.com/alex-nedelkoff/camping-planner`, the Killarney trip page is at `trips/killarney-2026-05/trip.html` (preview locally with `python3 -m http.server`), and pizza-zip has been invited and should accept the invite at `https://github.com/alex-nedelkoff/camping-planner/invitations`.

---

## Verification checklist (run after Task 12)

- [ ] `git log --oneline | wc -l` shows ~10 commits
- [ ] `python3 -m pytest tests/ -v` shows 9 passing tests
- [ ] `gh repo view alex-nedelkoff/camping-planner --json visibility -q .visibility` returns `PRIVATE`
- [ ] `ls trips/killarney-2026-05/` shows 7 files (6 .md + 1 .html)
- [ ] Browser preview of `trip.html` looks reasonable

If all five pass, the migration is complete.
