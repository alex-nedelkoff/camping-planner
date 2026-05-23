# Trip data → JSON + sibling nav — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-trip `.md` files with one `trip.json` per trip, switch the trip page from `build_trip.py` baking to server-rendered Jinja, and add a shared nav band so `/overlay/` and trip pages are no longer dead-ends.

**Architecture:** `trip.json` is the source of truth (validated by Pydantic). `GET /trip/<slug>` renders a Jinja template that reads `trip.json` + cached weather/route data. Sections are inline-editable; saves go through per-section PUT endpoints. A shared `nav_band.html` partial gives every page a home link, sibling-trip chevrons + dropdown, and a back-to-trip on overlay.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, Jinja2, `python-markdown`, SQLite, vanilla JS (no framework), Leaflet.

**Branch:** `local/water-polygon-union` (do NOT merge `origin/main` — deferred per spec). The branch has 13 modified files + 13 untracked files from prior unrelated work. **Never use `git add .` or `git add -A`** — always stage specific files only.

**Reference spec:** `docs/superpowers/specs/2026-05-22-trip-json-and-nav-design.md`

**Test command:** `python3.11 -m pytest <path>` (project rule — `python3.11` explicitly).

**Test boundaries:** Never hit Open-Meteo or Ontario Parks from tests — mock at the service boundary. The existing `tests/test_routes.py` already establishes this pattern.

---

## Milestones

| After… | You have… |
|---|---|
| Phase 3 | Pydantic models + trip.json read/write service + working migration script |
| Phase 5 | `/trip/<slug>` server-rendered, read-only, fully functional (weather + route + nav) |
| Phase 9 | All sections inline-editable |
| Phase 12 | Old endpoints + `build_trip.py` removed, MD files archived |

---

## Files created or modified

**New files:**
- `app/models_trip.py` — Pydantic models for trip.json sections
- `app/services/trip_store.py` — load/save `trip.json` with validation
- `app/services/route_cache.py` — Leaflet config + distance computation cache
- `app/routes/trip_pages.py` — `GET /trip/<slug>` server-rendered page
- `app/templates/trip.html`, `app/templates/overlay.html`
- `app/templates/partials/nav_band.html`, `partials/trip_header.html`
- `app/templates/partials/section_{itinerary,gear,food,packing,costs,route,weather}.html`
- `app/static/css/trip.css`
- `app/static/js/section_{meta,itinerary,gear,food,packing,costs,route}.js`
- `scripts/migrate_md_to_json.py`
- `tests/test_models_trip.py`, `tests/test_trip_store.py`, `tests/test_migrate_md_to_json.py`, `tests/test_route_cache.py`, `tests/test_trip_pages.py`, `tests/test_routes_trips.py`, `tests/test_templates.py`
- `tests/fixtures/migration/<case>/`

**Modified:** `app/main.py`, `app/routes/pages.py`, `app/routes/trips.py`, `app/models.py`, `app/templates/index.html`, `app/templates/partials/trip_card.html`, `app/templates/base.html`, `app/static/css/index.css`, `app/static/js/index.js`

**Deleted at end:** `build_trip.py`, `weather.py`, `tests/test_build_trip.py`, `tests/test_md_table.py`, `jeffs_osm_overlay.html`, `trips/<slug>/{itinerary,gear,food,costs,packing}.md`, `trips/<slug>/trip.html`

---

## Phase 0 — Pydantic models

### Task 1: Define core trip models with version + meta

**Files:**
- Create: `app/models_trip.py`
- Test: `tests/test_models_trip.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_models_trip.py
import pytest
from pydantic import ValidationError

from app.models_trip import Trip, TripDates, Night


def test_trip_minimal_validates():
    t = Trip(
        schema_version=1,
        name="killarney-2026-05",
        park="killarney",
        dates=TripDates(start="2026-05-15", end="2026-05-18"),
        participants=["Alex"],
        access_point="George Lake",
        nights=[],
        itinerary=[],
        gear={"shared": [], "personal": []},
        food=[],
        costs=[],
        packing=[],
    )
    assert t.schema_version == 1
    assert t.dates.start.isoformat() == "2026-05-15"


def test_trip_rejects_wrong_schema_version():
    with pytest.raises(ValidationError):
        Trip(schema_version=99, name="x", park="y",
             dates=TripDates(start="2026-01-01", end="2026-01-02"),
             participants=[], access_point="", nights=[],
             itinerary=[], gear={"shared": [], "personal": []},
             food=[], costs=[], packing=[])


def test_night_optional_gps():
    n = Night(date="2026-05-15", site="61", location="OSA Lake")
    assert n.gps is None
    n2 = Night(date="2026-05-15", site="61", location="OSA",
               gps=[46.04, -81.50])
    assert n2.gps == [46.04, -81.50]
```

- [ ] **Step 2: Verify it fails**

Run: `python3.11 -m pytest tests/test_models_trip.py -v`
Expected: `ModuleNotFoundError: No module named 'app.models_trip'`

- [ ] **Step 3: Implement minimal models**

```python
# app/models_trip.py
"""Pydantic models for the trip.json schema (v1)."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


SCHEMA_VERSION = 1


class TripDates(BaseModel):
    start: date
    end: date


class Night(BaseModel):
    date: date
    site: str = ""
    location: str = ""
    gps: Optional[list[float]] = None


class GearItem(BaseModel):
    item: str
    who: str = ""
    notes: str = ""


class PersonalGear(BaseModel):
    person: str
    items: list[GearItem] = Field(default_factory=list)


class GearSection(BaseModel):
    shared: list[GearItem] = Field(default_factory=list)
    personal: list[PersonalGear] = Field(default_factory=list)


class FoodItem(BaseModel):
    name: str
    who: str = ""


class FoodSlot(BaseModel):
    slot: str
    label: str
    items: list[FoodItem] = Field(default_factory=list)
    notes: str = ""


class CostRow(BaseModel):
    item: str
    who_paid: str = ""
    amount: Optional[float] = None
    currency: str = "CAD"


class PackingItem(BaseModel):
    label: str
    checked: bool = False


class PackingCategory(BaseModel):
    category: str
    items: list[PackingItem] = Field(default_factory=list)


class ItineraryDay(BaseModel):
    date: date
    label: str = ""
    notes: str = ""


class Trip(BaseModel):
    schema_version: Literal[1]
    name: str
    park: str
    dates: TripDates
    participants: list[str] = Field(default_factory=list)
    access_point: str = ""
    nights: list[Night] = Field(default_factory=list)
    itinerary: list[ItineraryDay] = Field(default_factory=list)
    gear: GearSection = Field(default_factory=GearSection)
    food: list[FoodSlot] = Field(default_factory=list)
    costs: list[CostRow] = Field(default_factory=list)
    packing: list[PackingCategory] = Field(default_factory=list)
```

- [ ] **Step 4: Verify tests pass**

Run: `python3.11 -m pytest tests/test_models_trip.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/models_trip.py tests/test_models_trip.py
git commit -m "feat(models): pydantic schema for trip.json v1"
```

---

## Phase 1 — Trip store service

### Task 2: trip_store.load + save (round-trip)

**Files:**
- Create: `app/services/trip_store.py`
- Test: `tests/test_trip_store.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_trip_store.py
import json
from pathlib import Path

import pytest

from app.models_trip import Trip
from app.services import trip_store


@pytest.fixture
def sample_trip_dict():
    return {
        "schema_version": 1,
        "name": "test-2026-05",
        "park": "killarney",
        "dates": {"start": "2026-05-15", "end": "2026-05-18"},
        "participants": ["Alex"],
        "access_point": "George Lake",
        "nights": [],
        "itinerary": [],
        "gear": {"shared": [], "personal": []},
        "food": [],
        "costs": [],
        "packing": [],
    }


def test_load_reads_and_validates(tmp_path, sample_trip_dict):
    trip_dir = tmp_path / "test-2026-05"
    trip_dir.mkdir()
    (trip_dir / "trip.json").write_text(json.dumps(sample_trip_dict))
    trip = trip_store.load(trip_dir)
    assert isinstance(trip, Trip)
    assert trip.name == "test-2026-05"


def test_save_writes_indented_json(tmp_path, sample_trip_dict):
    trip_dir = tmp_path / "test-2026-05"
    trip_dir.mkdir()
    trip = Trip.model_validate(sample_trip_dict)
    trip_store.save(trip_dir, trip)
    on_disk = json.loads((trip_dir / "trip.json").read_text())
    assert on_disk["name"] == "test-2026-05"
    raw = (trip_dir / "trip.json").read_text()
    assert raw.startswith("{\n")  # pretty-printed


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        trip_store.load(tmp_path / "nope")


def test_load_rejects_unknown_schema_version(tmp_path, sample_trip_dict):
    sample_trip_dict["schema_version"] = 99
    trip_dir = tmp_path / "test-2026-05"
    trip_dir.mkdir()
    (trip_dir / "trip.json").write_text(json.dumps(sample_trip_dict))
    with pytest.raises(trip_store.SchemaVersionError):
        trip_store.load(trip_dir)
```

- [ ] **Step 2: Verify it fails**

Run: `python3.11 -m pytest tests/test_trip_store.py -v`
Expected: ImportError on `trip_store`

- [ ] **Step 3: Implement service**

```python
# app/services/trip_store.py
"""Load/save the canonical trip.json file. Source-of-truth gateway."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.models_trip import SCHEMA_VERSION, Trip


TRIP_JSON_NAME = "trip.json"


class SchemaVersionError(Exception):
    """Raised when trip.json has an unknown or unsupported schema_version."""


def load(trip_dir: Path) -> Trip:
    path = trip_dir / TRIP_JSON_NAME
    if not path.exists():
        raise FileNotFoundError(f"no trip.json in {trip_dir}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"trip.json schema_version={version!r}, expected {SCHEMA_VERSION}"
        )
    return Trip.model_validate(raw)


def save(trip_dir: Path, trip: Trip) -> None:
    path = trip_dir / TRIP_JSON_NAME
    trip_dir.mkdir(parents=True, exist_ok=True)
    payload = trip.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def exists(trip_dir: Path) -> bool:
    return (trip_dir / TRIP_JSON_NAME).exists()
```

- [ ] **Step 4: Verify tests pass**

Run: `python3.11 -m pytest tests/test_trip_store.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/trip_store.py tests/test_trip_store.py
git commit -m "feat(trip_store): load/save trip.json with schema-version guard"
```

---

(Plan continues in next file write — Phases 2-12)

## Phase 2 — Migration script

### Task 3: Migration core — frontmatter + itinerary + food parsing

**Files:**
- Create: `scripts/migrate_md_to_json.py`
- Create: `tests/fixtures/migration/full/{trip.md,itinerary.md,food.md,gear.md,costs.md,packing.md}`
- Create: `tests/fixtures/migration/full/expected.json`
- Create: `tests/test_migrate_md_to_json.py`

- [ ] **Step 1: Create fixture inputs**

Create `tests/fixtures/migration/full/trip.md`:
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
    gps: [46.044041, -81.503845]
---
```

Create `tests/fixtures/migration/full/itinerary.md`:
```markdown
## Friday 2026-05-15 — Day 1

- Depart Ajax in the morning
- Permit pickup at George Lake

## Saturday 2026-05-16 — Day 2

- Pack up, paddle south
```

Create `tests/fixtures/migration/full/food.md`:
```markdown
3 breakfasts, 3 lunches, 3 dinners.

## Friday dinner

- _meal idea_ — _who_

## Saturday breakfast
```

(`gear.md`, `costs.md`, `packing.md` fixtures created in Task 4.)

- [ ] **Step 2: Write failing test**

```python
# tests/test_migrate_md_to_json.py
import json
from pathlib import Path

import pytest

from scripts.migrate_md_to_json import migrate_trip

FIXTURES = Path(__file__).parent / "fixtures" / "migration"


def test_migrate_full_trip_frontmatter_and_itinerary(tmp_path):
    src = FIXTURES / "full"
    dest = tmp_path / "killarney-2026-05"
    dest.mkdir()
    for f in src.iterdir():
        if f.suffix == ".md":
            (dest / f.name).write_text(f.read_text())
    migrate_trip(dest, slug="killarney-2026-05")
    result = json.loads((dest / "trip.json").read_text())
    assert result["schema_version"] == 1
    assert result["park"] == "killarney"
    assert result["dates"]["start"] == "2026-05-15"
    assert result["participants"] == ["Alex", "pizza-zip"]
    assert len(result["nights"]) == 2
    assert result["nights"][1]["gps"] == [46.044041, -81.503845]
    assert len(result["itinerary"]) == 2
    assert result["itinerary"][0]["label"].startswith("Friday")
    assert "Depart Ajax" in result["itinerary"][0]["notes"]
    assert len(result["food"]) == 2
    assert result["food"][0]["slot"] == "friday-dinner"


def test_migrate_refuses_overwrite_without_force(tmp_path):
    dest = tmp_path / "x"
    dest.mkdir()
    (dest / "trip.json").write_text("{}")
    (dest / "trip.md").write_text("---\npark: x\nstart_date: 2026-01-01\nend_date: 2026-01-02\n---\n")
    with pytest.raises(FileExistsError):
        migrate_trip(dest, slug="x")
```

- [ ] **Step 3: Verify it fails**

Run: `python3.11 -m pytest tests/test_migrate_md_to_json.py -v`
Expected: ImportError on `scripts.migrate_md_to_json`

- [ ] **Step 4: Implement migration script**

```python
# scripts/migrate_md_to_json.py
"""One-shot converter: trips/<slug>/*.md  →  trips/<slug>/trip.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.models_trip import (  # noqa: E402
    SCHEMA_VERSION, Trip, TripDates, Night, ItineraryDay, FoodSlot,
)

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "section"


def _split_sections(md: str) -> list[tuple[str, str]]:
    """Split markdown on `## headings`. Returns [(heading, body), ...]."""
    parts = re.split(r"^## (.+)$", md, flags=re.MULTILINE)
    # parts[0] = preamble; then alternating heading, body
    out = []
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        out.append((heading, body))
    return out


def _parse_frontmatter(trip_md_text: str) -> dict:
    m = FRONTMATTER_RE.match(trip_md_text)
    if not m:
        raise ValueError("trip.md has no frontmatter")
    return yaml.safe_load(m.group(1)) or {}


def _itinerary_from_md(text: str) -> list[dict]:
    days = []
    for heading, body in _split_sections(text):
        # Try to extract a YYYY-MM-DD if present in the heading
        m = re.search(r"(\d{4}-\d{2}-\d{2})", heading)
        date_iso = m.group(1) if m else None
        days.append({
            "date": date_iso,
            "label": heading,
            "notes": body,
        })
    return days


def _food_from_md(text: str) -> list[dict]:
    slots = []
    for heading, body in _split_sections(text):
        slots.append({
            "slot": _slugify(heading),
            "label": heading,
            "items": [],
            "notes": body,
        })
    return slots


def _gear_from_md(text: str) -> dict:
    # Placeholder — full implementation in Task 4.
    return {"shared": [], "personal": []}


def _costs_from_md(text: str) -> list[dict]:
    return []  # Placeholder — Task 4.


def _packing_from_md(text: str) -> list[dict]:
    return []  # Placeholder — Task 4.


def migrate_trip(trip_dir: Path, slug: str, force: bool = False,
                 dry_run: bool = False) -> dict:
    """Convert one trip's MD files to a trip.json dict.

    Writes trip.json unless dry_run=True. Returns the dict either way.
    Moves source .md files into trip_dir/_archive/ on success (unless dry_run).
    """
    trip_json_path = trip_dir / "trip.json"
    if trip_json_path.exists() and not force:
        raise FileExistsError(f"{trip_json_path} already exists (use --force)")

    trip_md = trip_dir / "trip.md"
    if not trip_md.exists():
        raise FileNotFoundError(f"no trip.md in {trip_dir}")

    fm = _parse_frontmatter(trip_md.read_text(encoding="utf-8"))

    def _read(name: str) -> str:
        p = trip_dir / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    payload = {
        "schema_version": SCHEMA_VERSION,
        "name": slug,
        "park": fm.get("park", ""),
        "dates": {
            "start": str(fm.get("start_date") or fm.get("start") or ""),
            "end": str(fm.get("end_date") or fm.get("end") or ""),
        },
        "participants": fm.get("participants") or [],
        "access_point": fm.get("access_point", ""),
        "nights": [
            {
                "date": str(n.get("date", "")),
                "site": str(n.get("site", "")),
                "location": n.get("location", ""),
                "gps": n.get("gps"),
            }
            for n in (fm.get("nights") or [])
        ],
        "itinerary": _itinerary_from_md(_read("itinerary.md")),
        "gear": _gear_from_md(_read("gear.md")),
        "food": _food_from_md(_read("food.md")),
        "costs": _costs_from_md(_read("costs.md")),
        "packing": _packing_from_md(_read("packing.md")),
    }

    # Validate via Pydantic before writing
    Trip.model_validate(payload)

    if dry_run:
        return payload

    trip_json_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    archive = trip_dir / "_archive"
    archive.mkdir(exist_ok=True)
    for name in ("trip.md", "itinerary.md", "gear.md", "food.md",
                 "costs.md", "packing.md"):
        p = trip_dir / name
        if p.exists():
            p.rename(archive / name)

    return payload


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("trip_dir", type=Path)
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    slug = args.trip_dir.name
    payload = migrate_trip(args.trip_dir, slug=slug, force=args.force,
                            dry_run=args.dry_run)
    if args.dry_run:
        print(json.dumps(payload, indent=2))
    else:
        print(f"wrote {args.trip_dir}/trip.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Verify tests pass**

Run: `python3.11 -m pytest tests/test_migrate_md_to_json.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_md_to_json.py tests/test_migrate_md_to_json.py \
        tests/fixtures/migration/full/trip.md \
        tests/fixtures/migration/full/itinerary.md \
        tests/fixtures/migration/full/food.md
git commit -m "feat(migrate): md→json frontmatter, itinerary, food parsing"
```


### Task 4: Migration — gear/costs/packing parsers

**Files:**
- Modify: `scripts/migrate_md_to_json.py`
- Create: `tests/fixtures/migration/full/gear.md`
- Create: `tests/fixtures/migration/full/costs.md`
- Create: `tests/fixtures/migration/full/packing.md`
- Modify: `tests/test_migrate_md_to_json.py`

- [ ] **Step 1: Create fixture files**

`tests/fixtures/migration/full/gear.md`:
```markdown
## Shared gear

| Item | Who's bringing | Notes |
|---|---|---|
| Canoe | TBD | confirm with outfitter |
| Paddles (2-3) | | |

## Personal gear

### Alex

- Sleeping bag
- Headlamp
```

`tests/fixtures/migration/full/costs.md`:
```markdown
| Item | Who paid | Amount |
|---|---|---|
| Permit | Alex | 45.00 |
| Gas | | |
```

`tests/fixtures/migration/full/packing.md`:
```markdown
## Shelter & sleep

- [ ] Tent
- [x] Sleeping bag

## Kitchen

- [ ] Stove
```

- [ ] **Step 2: Add tests**

Add to `tests/test_migrate_md_to_json.py`:
```python
def test_migrate_gear_costs_packing(tmp_path):
    src = FIXTURES / "full"
    dest = tmp_path / "x"
    dest.mkdir()
    for f in src.iterdir():
        if f.suffix == ".md":
            (dest / f.name).write_text(f.read_text())
    migrate_trip(dest, slug="x")
    result = json.loads((dest / "trip.json").read_text())

    assert result["gear"]["shared"] == [
        {"item": "Canoe", "who": "TBD", "notes": "confirm with outfitter"},
        {"item": "Paddles (2-3)", "who": "", "notes": ""},
    ]
    assert result["gear"]["personal"] == [
        {"person": "Alex",
         "items": [{"item": "Sleeping bag", "notes": ""},
                   {"item": "Headlamp", "notes": ""}]}
    ]
    assert result["costs"] == [
        {"item": "Permit", "who_paid": "Alex", "amount": 45.0, "currency": "CAD"},
        {"item": "Gas", "who_paid": "", "amount": None, "currency": "CAD"},
    ]
    assert result["packing"] == [
        {"category": "Shelter & sleep",
         "items": [{"label": "Tent", "checked": False},
                   {"label": "Sleeping bag", "checked": True}]},
        {"category": "Kitchen",
         "items": [{"label": "Stove", "checked": False}]},
    ]


def test_migrate_archives_md_files(tmp_path):
    src = FIXTURES / "full"
    dest = tmp_path / "x"
    dest.mkdir()
    for f in src.iterdir():
        if f.suffix == ".md":
            (dest / f.name).write_text(f.read_text())
    migrate_trip(dest, slug="x")
    assert not (dest / "trip.md").exists()
    assert (dest / "_archive" / "trip.md").exists()
    assert (dest / "trip.json").exists()
```

- [ ] **Step 3: Verify gear/costs/packing tests fail**

Run: `python3.11 -m pytest tests/test_migrate_md_to_json.py -v`
Expected: `test_migrate_gear_costs_packing` fails (empty results vs expected)

- [ ] **Step 4: Replace gear/costs/packing parsers in scripts/migrate_md_to_json.py**

Replace the three placeholder functions:
```python
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[(?P<mark>[ xX])\]\s+(?P<label>.+)$",
                          re.MULTILINE)


def _parse_md_table(text: str) -> list[list[str]]:
    """Return data rows (header + separator stripped) as list-of-lists."""
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 3:
        return []
    rows = []
    for ln in lines[2:]:  # skip header + separator
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def _gear_from_md(text: str) -> dict:
    shared = []
    personal = []
    sections = _split_sections(text)
    for heading, body in sections:
        if heading.lower().startswith("shared"):
            for row in _parse_md_table(body):
                row = (row + ["", "", ""])[:3]
                shared.append({"item": row[0], "who": row[1], "notes": row[2]})
        elif heading.lower().startswith("personal"):
            # Body has ### per-person subsections
            person_parts = re.split(r"^### (.+)$", body, flags=re.MULTILINE)
            for i in range(1, len(person_parts), 2):
                person = person_parts[i].strip()
                items_block = person_parts[i + 1] if i + 1 < len(person_parts) else ""
                items = []
                for ln in items_block.splitlines():
                    m = re.match(r"^\s*[-*+]\s+(.+)$", ln)
                    if m:
                        items.append({"item": m.group(1).strip(), "notes": ""})
                personal.append({"person": person, "items": items})
    return {"shared": shared, "personal": personal}


def _costs_from_md(text: str) -> list[dict]:
    rows = _parse_md_table(text)
    out = []
    for row in rows:
        row = (row + ["", "", ""])[:3]
        item, who, amount_str = row
        try:
            amount = float(amount_str) if amount_str.strip() else None
        except ValueError:
            amount = None
        out.append({"item": item, "who_paid": who,
                    "amount": amount, "currency": "CAD"})
    return out


def _packing_from_md(text: str) -> list[dict]:
    out = []
    for heading, body in _split_sections(text):
        items = []
        for m in CHECKBOX_RE.finditer(body):
            items.append({
                "label": m.group("label").strip(),
                "checked": m.group("mark").lower() == "x",
            })
        out.append({"category": heading, "items": items})
    return out
```

- [ ] **Step 5: Verify tests pass**

Run: `python3.11 -m pytest tests/test_migrate_md_to_json.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_md_to_json.py tests/test_migrate_md_to_json.py \
        tests/fixtures/migration/full/gear.md \
        tests/fixtures/migration/full/costs.md \
        tests/fixtures/migration/full/packing.md
git commit -m "feat(migrate): gear/costs/packing parsers + archiving"
```

---

### Task 5: Run migration on killarney-2026-05

**Files:** none new — script run + commit of generated `trip.json`.

- [ ] **Step 1: Dry-run first**

```bash
python3.11 scripts/migrate_md_to_json.py trips/killarney-2026-05 --dry-run | less
```
Expected: prints JSON to stdout. Eyeball the gear, costs, packing sections — fix any unexpected output by editing the source `.md` files first if needed, NOT by patching the script (the script is generic).

- [ ] **Step 2: Run for real**

```bash
python3.11 scripts/migrate_md_to_json.py trips/killarney-2026-05
```
Expected: `wrote trips/killarney-2026-05/trip.json`, and `trips/killarney-2026-05/_archive/` now contains the .md files.

- [ ] **Step 3: Sanity check**

```bash
ls trips/killarney-2026-05/
# Expect: _archive/  manual_routes.json  trip.html  trip.json
python3.11 -c "from app.services.trip_store import load; from pathlib import Path; t = load(Path('trips/killarney-2026-05')); print(t.name, len(t.itinerary), 'days')"
```

- [ ] **Step 4: Commit**

```bash
git add trips/killarney-2026-05/trip.json trips/killarney-2026-05/_archive/
git commit -m "data: migrate killarney-2026-05 to trip.json (md files archived)"
```

---

## Phase 3 — Read API

### Task 6: GET /api/trips list with prev/next

**Files:**
- Modify: `app/services/trips.py` (add `list_trips_v2`)
- Modify: `app/routes/trips.py` (add new endpoint)
- Modify: `app/models.py` (add `TripsListResponse`)
- Create: `tests/test_routes_trips.py`

- [ ] **Step 1: Add response model to app/models.py**

Append:
```python
class TripListEntry(BaseModel):
    slug: str
    name: str
    park: str
    park_name: Optional[str] = None
    start: date
    end: date
    participant_count: int
    prev_slug: Optional[str] = None
    next_slug: Optional[str] = None


class TripsListResponse(BaseModel):
    ok: bool = True
    trips: list[TripListEntry]
```

(Note: add `from datetime import date` at the top if not already imported.)

- [ ] **Step 2: Write failing test**

`tests/test_routes_trips.py`:
```python
"""Tests for the new /api/trips endpoints (trip.json era)."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, trips as trips_svc

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    tmp_trips = tmp_path / "trips"
    tmp_trips.mkdir()
    # Two minimal JSON trips
    for slug, start in [("a-2026-04", "2026-04-01"),
                         ("b-2026-06", "2026-06-15")]:
        d = tmp_trips / slug
        d.mkdir()
        (d / "trip.json").write_text(json.dumps({
            "schema_version": 1, "name": slug,
            "park": "killarney" if slug.startswith("a") else "killbear",
            "dates": {"start": start,
                       "end": start[:8] + str(int(start[8:]) + 2).zfill(2)},
            "participants": ["Alex"], "access_point": "",
            "nights": [], "itinerary": [], "gear": {"shared": [], "personal": []},
            "food": [], "costs": [], "packing": [],
        }))
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    tmp_db = tmp_path / "test.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)
    yield TestClient(app)


def test_list_trips_returns_sorted_with_neighbours(client):
    r = client.get("/api/trips")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    slugs = [t["slug"] for t in body["trips"]]
    assert slugs == ["a-2026-04", "b-2026-06"]
    assert body["trips"][0]["prev_slug"] is None
    assert body["trips"][0]["next_slug"] == "b-2026-06"
    assert body["trips"][1]["prev_slug"] == "a-2026-04"
    assert body["trips"][1]["next_slug"] is None
```

- [ ] **Step 3: Verify it fails**

Run: `python3.11 -m pytest tests/test_routes_trips.py -v`
Expected: 404 (endpoint doesn't exist yet).

- [ ] **Step 4: Implement service helper**

In `app/services/trips.py`, append:
```python
from app.services import trip_store


def list_trips_v2(trips_dir: Path | None = None) -> list[dict]:
    """List trips by reading trip.json. Sorted by start date."""
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    entries = []
    if not trips_dir.exists():
        return entries
    for sub in sorted(trips_dir.iterdir()):
        if not sub.is_dir() or not trip_store.exists(sub):
            continue
        try:
            t = trip_store.load(sub)
        except Exception:
            continue
        park_info = build_trip._load_park_info(t.park) if t.park else {}
        entries.append({
            "slug": sub.name,
            "name": t.name,
            "park": t.park,
            "park_name": park_info.get("name"),
            "start": t.dates.start,
            "end": t.dates.end,
            "participant_count": len(t.participants),
        })
    entries.sort(key=lambda e: e["start"])
    for i, e in enumerate(entries):
        e["prev_slug"] = entries[i - 1]["slug"] if i > 0 else None
        e["next_slug"] = entries[i + 1]["slug"] if i < len(entries) - 1 else None
    return entries
```

- [ ] **Step 5: Add endpoint**

In `app/routes/trips.py`, append:
```python
from app.models import TripsListResponse, TripListEntry
from app.services import trips as trips_svc


@router.get("/trips", response_model=TripsListResponse)
def list_trips():
    entries = trips_svc.list_trips_v2()
    return TripsListResponse(
        trips=[TripListEntry(**e) for e in entries]
    )
```

- [ ] **Step 6: Run tests**

Run: `python3.11 -m pytest tests/test_routes_trips.py -v`
Expected: 1 passed

- [ ] **Step 7: Commit**

```bash
git add app/models.py app/services/trips.py app/routes/trips.py \
        tests/test_routes_trips.py
git commit -m "feat(api): GET /api/trips list with sibling slugs"
```

---

### Task 7: GET /api/trips/<slug>

**Files:**
- Modify: `app/routes/trips.py`
- Modify: `tests/test_routes_trips.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_routes_trips.py`:
```python
def test_get_trip_returns_json(client):
    r = client.get("/api/trips/a-2026-04")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "a-2026-04"
    assert body["dates"]["start"] == "2026-04-01"


def test_get_trip_404(client):
    r = client.get("/api/trips/does-not-exist")
    assert r.status_code == 404
```

- [ ] **Step 2: Verify it fails**

Run: `python3.11 -m pytest tests/test_routes_trips.py::test_get_trip_returns_json -v`
Expected: 404 (route missing)

- [ ] **Step 3: Add endpoint**

Append to `app/routes/trips.py`:
```python
from fastapi import HTTPException
from app.services import trip_store


@router.get("/trips/{slug}")
def get_trip(slug: str):
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        t = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return t.model_dump(mode="json")
```

- [ ] **Step 4: Verify all tests pass**

Run: `python3.11 -m pytest tests/test_routes_trips.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/routes/trips.py tests/test_routes_trips.py
git commit -m "feat(api): GET /api/trips/<slug> returns trip.json"
```


---

## Phase 4 — Server-rendered trip page (read-only)

### Task 8: GET /trip/<slug> with all section partials in read mode

**Files:**
- Create: `app/routes/trip_pages.py`
- Create: `app/templates/trip.html`
- Create: `app/templates/partials/trip_header.html`
- Create: `app/templates/partials/section_itinerary.html`
- Create: `app/templates/partials/section_gear.html`
- Create: `app/templates/partials/section_food.html`
- Create: `app/templates/partials/section_costs.html`
- Create: `app/templates/partials/section_packing.html`
- Create: `app/templates/partials/section_route.html` (stub — full impl in Phase 6)
- Create: `app/templates/partials/section_weather.html` (stub — full impl in Phase 6)
- Create: `app/static/css/trip.css`
- Modify: `app/main.py` (register router)
- Create: `tests/test_trip_pages.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_trip_pages.py
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, trips as trips_svc


@pytest.fixture
def client(tmp_path, monkeypatch):
    tmp_trips = tmp_path / "trips"
    tmp_trips.mkdir()
    d = tmp_trips / "k-2026-05"
    d.mkdir()
    (d / "trip.json").write_text(json.dumps({
        "schema_version": 1, "name": "k-2026-05", "park": "killarney",
        "dates": {"start": "2026-05-15", "end": "2026-05-18"},
        "participants": ["Alex"], "access_point": "George Lake",
        "nights": [{"date": "2026-05-15", "site": "61",
                    "location": "OSA Lake", "gps": None}],
        "itinerary": [{"date": "2026-05-15", "label": "Day 1",
                       "notes": "Depart Ajax"}],
        "gear": {"shared": [{"item": "Canoe", "who": "TBD", "notes": ""}],
                 "personal": []},
        "food": [{"slot": "friday-dinner", "label": "Friday dinner",
                  "items": [], "notes": ""}],
        "costs": [{"item": "Permit", "who_paid": "Alex",
                   "amount": 45.0, "currency": "CAD"}],
        "packing": [{"category": "Sleep",
                     "items": [{"label": "Tent", "checked": False}]}],
    }))
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    tmp_db = tmp_path / "x.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)
    yield TestClient(app)


def test_trip_page_renders(client):
    r = client.get("/trip/k-2026-05")
    assert r.status_code == 200
    html = r.text
    assert "k-2026-05" in html
    assert "OSA Lake" in html
    assert "Day 1" in html
    assert "Depart Ajax" in html
    assert "Canoe" in html
    assert "Friday dinner" in html
    assert "Permit" in html
    assert "Tent" in html


def test_trip_page_404(client):
    r = client.get("/trip/does-not-exist")
    assert r.status_code == 404
```

- [ ] **Step 2: Verify it fails**

Run: `python3.11 -m pytest tests/test_trip_pages.py -v`
Expected: 404 (route missing)

- [ ] **Step 3: Create the page route**

```python
# app/routes/trip_pages.py
"""Server-rendered HTML trip detail page."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import markdown as _md

from app.config import JINJA_TEMPLATES_DIR
from app.services import trip_store, trips as trips_svc

router = APIRouter()
templates = Jinja2Templates(directory=str(JINJA_TEMPLATES_DIR))


def _md_filter(text: str) -> str:
    return _md.markdown(text or "", extensions=["extra", "sane_lists"])


templates.env.filters["md"] = _md_filter


@router.get("/trip/{slug}", response_class=HTMLResponse)
def trip_page(slug: str, request: Request):
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        trip = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="trip not found")
    siblings = trips_svc.list_trips_v2()
    me = next((s for s in siblings if s["slug"] == slug), None)
    return templates.TemplateResponse("trip.html", {
        "request": request,
        "trip": trip,
        "slug": slug,
        "siblings": siblings,
        "prev_slug": me["prev_slug"] if me else None,
        "next_slug": me["next_slug"] if me else None,
    })
```

- [ ] **Step 4: Create the templates**

`app/templates/trip.html`:
```html
{% extends "base.html" %}
{% block title %}{{ trip.name }}{% endblock %}
{% block head_extra %}
<link rel="stylesheet" href="/static/css/trip.css">
{% endblock %}
{% block body %}
  {# nav band — fully wired in Phase 5 #}
  <div class="trip-page">
    {% include "partials/trip_header.html" %}
    {% include "partials/section_route.html" %}
    {% include "partials/section_weather.html" %}
    {% include "partials/section_itinerary.html" %}
    {% include "partials/section_gear.html" %}
    {% include "partials/section_food.html" %}
    {% include "partials/section_packing.html" %}
    {% include "partials/section_costs.html" %}
  </div>
{% endblock %}
```

`app/templates/partials/trip_header.html`:
```html
<header class="trip-hero">
  <h1>{{ trip.name }}</h1>
  <div class="trip-meta">
    <span><strong>Park:</strong> {{ trip.park }}</span>
    <span><strong>Dates:</strong> {{ trip.dates.start }} → {{ trip.dates.end }}</span>
    <span><strong>Access:</strong> {{ trip.access_point }}</span>
    <span><strong>Who:</strong> {{ trip.participants | join(", ") }}</span>
  </div>
  {% if trip.nights %}
  <table class="nights-table">
    <thead><tr><th>Date</th><th>Site</th><th>Location</th></tr></thead>
    <tbody>
      {% for n in trip.nights %}
      <tr><td>{{ n.date }}</td><td>{{ n.site }}</td><td>{{ n.location }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}
</header>
```

`app/templates/partials/section_itinerary.html`:
```html
<section id="itinerary" class="trip-section" data-section="itinerary">
  <header class="section-header">
    <h2>Itinerary</h2>
    <button class="btn btn-ghost edit-btn" data-section="itinerary">Edit</button>
  </header>
  <div class="section-body">
    {% for day in trip.itinerary %}
    <article class="itinerary-day">
      <h3>{{ day.label or day.date }}</h3>
      <div class="day-notes">{{ day.notes | md | safe }}</div>
    </article>
    {% else %}
    <p class="empty">No itinerary yet.</p>
    {% endfor %}
  </div>
</section>
```

`app/templates/partials/section_gear.html`:
```html
<section id="gear" class="trip-section" data-section="gear">
  <header class="section-header">
    <h2>Gear</h2>
    <button class="btn btn-ghost edit-btn" data-section="gear">Edit</button>
  </header>
  <div class="section-body">
    <h3>Shared</h3>
    <table>
      <thead><tr><th>Item</th><th>Who</th><th>Notes</th></tr></thead>
      <tbody>
        {% for row in trip.gear.shared %}
        <tr><td>{{ row.item }}</td><td>{{ row.who }}</td><td>{{ row.notes }}</td></tr>
        {% else %}
        <tr><td colspan="3" class="empty">Empty</td></tr>
        {% endfor %}
      </tbody>
    </table>
    <h3>Personal</h3>
    {% for person in trip.gear.personal %}
    <div class="person-gear">
      <h4>{{ person.person }}</h4>
      <ul>{% for it in person.items %}<li>{{ it.item }}{% if it.notes %} — {{ it.notes }}{% endif %}</li>{% endfor %}</ul>
    </div>
    {% else %}
    <p class="empty">No personal lists yet.</p>
    {% endfor %}
  </div>
</section>
```

`app/templates/partials/section_food.html`:
```html
<section id="food" class="trip-section" data-section="food">
  <header class="section-header">
    <h2>Food</h2>
    <button class="btn btn-ghost edit-btn" data-section="food">Edit</button>
  </header>
  <div class="section-body">
    {% for slot in trip.food %}
    <article class="food-slot">
      <h3>{{ slot.label }}</h3>
      {% if slot.items %}
      <ul>{% for it in slot.items %}<li>{{ it.name }}{% if it.who %} — {{ it.who }}{% endif %}</li>{% endfor %}</ul>
      {% endif %}
      <div class="slot-notes">{{ slot.notes | md | safe }}</div>
    </article>
    {% else %}
    <p class="empty">No meals planned yet.</p>
    {% endfor %}
  </div>
</section>
```

`app/templates/partials/section_costs.html`:
```html
<section id="costs" class="trip-section" data-section="costs">
  <header class="section-header">
    <h2>Costs</h2>
    <button class="btn btn-ghost edit-btn" data-section="costs">Edit</button>
  </header>
  <div class="section-body">
    <table>
      <thead><tr><th>Item</th><th>Who paid</th><th>Amount</th></tr></thead>
      <tbody>
        {% set ns = namespace(total=0) %}
        {% for row in trip.costs %}
        {% if row.amount is not none %}{% set ns.total = ns.total + row.amount %}{% endif %}
        <tr>
          <td>{{ row.item }}</td>
          <td>{{ row.who_paid }}</td>
          <td>{% if row.amount is not none %}{{ "%.2f"|format(row.amount) }} {{ row.currency }}{% endif %}</td>
        </tr>
        {% else %}
        <tr><td colspan="3" class="empty">No costs recorded</td></tr>
        {% endfor %}
        {% if trip.costs %}
        <tr class="total-row"><td><strong>Total</strong></td><td></td>
            <td><strong>{{ "%.2f"|format(ns.total) }} CAD</strong></td></tr>
        {% endif %}
      </tbody>
    </table>
  </div>
</section>
```

`app/templates/partials/section_packing.html`:
```html
<section id="packing" class="trip-section" data-section="packing">
  <header class="section-header">
    <h2>Packing</h2>
    <button class="btn btn-ghost edit-btn" data-section="packing">Edit</button>
  </header>
  <div class="section-body">
    {% for cat in trip.packing %}
    <div class="packing-category">
      <h3>{{ cat.category }}</h3>
      <ul class="packing-list">
        {% for item in cat.items %}
        <li><label>
          <input type="checkbox" disabled {% if item.checked %}checked{% endif %}>
          {{ item.label }}
        </label></li>
        {% endfor %}
      </ul>
    </div>
    {% else %}
    <p class="empty">No packing list yet.</p>
    {% endfor %}
  </div>
</section>
```

`app/templates/partials/section_route.html` (stub):
```html
<section id="route" class="trip-section" data-section="route">
  <header class="section-header">
    <h2>Route</h2>
    <a class="btn btn-ghost" href="/overlay/?trip={{ slug }}">Open in overlay →</a>
  </header>
  <div class="section-body">
    <p class="placeholder">Route map renders here in Phase 6.</p>
  </div>
</section>
```

`app/templates/partials/section_weather.html` (stub):
```html
<section id="weather" class="trip-section" data-section="weather">
  <header class="section-header"><h2>Weather</h2></header>
  <div class="section-body">
    <p class="placeholder">Weather renders here in Phase 6.</p>
  </div>
</section>
```

`app/static/css/trip.css` (minimal — copy-extract more from build_trip.py later):
```css
.trip-page { max-width: 900px; margin: 0 auto; padding: 1.5rem; }
.trip-hero { background: #2d5016; color: white; padding: 1.5rem;
             border-radius: 10px; margin-bottom: 1rem; }
.trip-hero h1 { margin: 0 0 0.5rem; color: white; }
.trip-meta { display: flex; flex-wrap: wrap; gap: 1rem; opacity: 0.95; }
.trip-section { background: white; padding: 1.25rem 1.5rem; margin: 1rem 0;
                border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.section-header { display: flex; justify-content: space-between;
                  align-items: baseline; }
.section-header h2 { margin: 0; }
.edit-btn { font-size: 0.85rem; }
.empty { color: #888; font-style: italic; }
.nights-table { background: rgba(0,0,0,0.18); border-radius: 6px; margin-top: 0.75rem; }
.nights-table th, .nights-table td { color: white;
    border-bottom: 1px solid rgba(255,255,255,0.18); padding: 0.4rem 0.7rem; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }
.total-row td { border-top: 2px solid #2d5016; padding-top: 0.6rem; }
```

- [ ] **Step 5: Register router in app/main.py**

Find the line `from app.routes import checklist, identity, pages, parks, trips` and add `trip_pages` to it. Then add `app.include_router(trip_pages.router)` near the other includes.

- [ ] **Step 6: Verify base.html supports head_extra block**

Open `app/templates/base.html`. If it doesn't have `{% block head_extra %}{% endblock %}` in the `<head>`, add it. Same for `{% block body %}{% endblock %}` in the body.

- [ ] **Step 7: Run tests**

Run: `python3.11 -m pytest tests/test_trip_pages.py -v`
Expected: 2 passed

- [ ] **Step 8: Commit**

```bash
git add app/routes/trip_pages.py app/main.py \
        app/templates/trip.html app/templates/partials/trip_header.html \
        app/templates/partials/section_itinerary.html \
        app/templates/partials/section_gear.html \
        app/templates/partials/section_food.html \
        app/templates/partials/section_costs.html \
        app/templates/partials/section_packing.html \
        app/templates/partials/section_route.html \
        app/templates/partials/section_weather.html \
        app/static/css/trip.css tests/test_trip_pages.py
# Also stage app/templates/base.html ONLY IF you modified it in Step 6.
git commit -m "feat(trip): server-rendered /trip/<slug> read-only page"
```


---

## Phase 5 — Shared nav band

### Task 9: nav_band partial — applied to trip page + index

**Files:**
- Create: `app/templates/partials/nav_band.html`
- Modify: `app/templates/trip.html`
- Modify: `app/templates/index.html`
- Modify: `app/routes/pages.py` (pass nav context to index)
- Modify: `app/routes/trip_pages.py` (pass nav context)
- Modify: `app/static/css/index.css` (nav band styles — shared)
- Create: `tests/test_templates.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_templates.py
"""Snapshot-ish smoke tests for the nav band across pages."""

import json
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import db, trips as trips_svc


@pytest.fixture
def client(tmp_path, monkeypatch):
    tmp_trips = tmp_path / "trips"
    tmp_trips.mkdir()
    for slug, start in [("a-2026-04", "2026-04-01"),
                         ("b-2026-06", "2026-06-15")]:
        d = tmp_trips / slug
        d.mkdir()
        (d / "trip.json").write_text(json.dumps({
            "schema_version": 1, "name": slug,
            "park": "killarney",
            "dates": {"start": start, "end": start[:8] + "10"},
            "participants": ["Alex"], "access_point": "",
            "nights": [], "itinerary": [],
            "gear": {"shared": [], "personal": []},
            "food": [], "costs": [], "packing": [],
        }))
    monkeypatch.setattr(trips_svc, "TRIPS_DIR", tmp_trips)
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_trips)
    tmp_db = tmp_path / "x.sqlite3"
    db.init_schema(tmp_db)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_db)
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_db)
    yield TestClient(app)


def test_nav_band_on_trip_page_has_chevrons_and_dropdown(client):
    r = client.get("/trip/a-2026-04")
    assert r.status_code == 200
    html = r.text
    assert 'class="nav-band"' in html
    assert "trip-dropdown" in html
    # next button enabled since a-2026-04 has a sibling
    assert 'href="/trip/b-2026-06"' in html


def test_nav_band_on_trip_page_dropdown_lists_all_trips(client):
    r = client.get("/trip/a-2026-04")
    html = r.text
    assert "a-2026-04" in html and "b-2026-06" in html


def test_nav_band_on_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'class="nav-band"' in r.text
```

- [ ] **Step 2: Verify it fails**

Run: `python3.11 -m pytest tests/test_templates.py -v`
Expected: assertion failures (nav-band class not in HTML yet)

- [ ] **Step 3: Create the nav band partial**

`app/templates/partials/nav_band.html`:
```html
<nav class="nav-band">
  <a class="nav-home" href="{{ nav.home_href | default('/') }}" title="Trips home">🏕</a>
  <span class="nav-sep">/</span>

  {% if nav.trip_slug %}
    {% if nav.prev_slug %}
      <a class="nav-chevron" href="/trip/{{ nav.prev_slug }}" title="Previous trip">←</a>
    {% else %}
      <span class="nav-chevron disabled">←</span>
    {% endif %}

    <div class="trip-dropdown">
      <button type="button" class="trip-dropdown-trigger" onclick="this.parentElement.classList.toggle('open')">
        {{ nav.trip_label or nav.trip_slug }} ▼
      </button>
      <ul class="trip-dropdown-menu">
        {% for t in nav.trip_dropdown or [] %}
        <li><a href="/trip/{{ t.slug }}"
               class="{% if t.slug == nav.trip_slug %}current{% endif %}">
          {{ t.name }}
        </a></li>
        {% endfor %}
        <li class="divider"></li>
        <li><a href="/" class="new-trip">+ New trip</a></li>
      </ul>
    </div>

    {% if nav.next_slug %}
      <a class="nav-chevron" href="/trip/{{ nav.next_slug }}" title="Next trip">→</a>
    {% else %}
      <span class="nav-chevron disabled">→</span>
    {% endif %}
  {% elif nav.back_href %}
    <a class="nav-back" href="{{ nav.back_href }}">← {{ nav.back_label }}</a>
  {% endif %}

  <span class="nav-spacer"></span>
  {% if nav.show_user_pill | default(true) %}
    <button id="user-pill" class="user-pill unset" onclick="switchUser && switchUser()" title="Click to set / change name">…</button>
  {% endif %}
</nav>
```

- [ ] **Step 4: Append styles to app/static/css/index.css**

```css
.nav-band { display: flex; align-items: center; gap: 0.6rem;
            padding: 0.5rem 1rem; background: #1f3a3a; color: white;
            font-family: -apple-system, sans-serif; }
.nav-band a { color: white; text-decoration: none; }
.nav-band .nav-home { font-size: 1.3rem; }
.nav-band .nav-sep { opacity: 0.5; }
.nav-band .nav-chevron { padding: 0.2rem 0.6rem; border-radius: 4px; }
.nav-band .nav-chevron:hover { background: rgba(255,255,255,0.1); }
.nav-band .nav-chevron.disabled { opacity: 0.3; pointer-events: none; }
.nav-band .nav-spacer { flex: 1; }
.trip-dropdown { position: relative; }
.trip-dropdown-trigger { background: rgba(255,255,255,0.1); color: white;
    border: none; padding: 0.3rem 0.7rem; border-radius: 4px; cursor: pointer;
    font-family: inherit; font-size: 0.95rem; }
.trip-dropdown-trigger:hover { background: rgba(255,255,255,0.18); }
.trip-dropdown-menu { display: none; position: absolute; top: 100%; left: 0;
    background: white; color: #222; min-width: 220px; list-style: none;
    margin: 0.25rem 0 0; padding: 0.3rem 0; border-radius: 6px;
    box-shadow: 0 6px 18px rgba(0,0,0,0.18); z-index: 100; }
.trip-dropdown.open .trip-dropdown-menu { display: block; }
.trip-dropdown-menu li a { display: block; padding: 0.4rem 0.9rem;
    color: #222; }
.trip-dropdown-menu li a:hover { background: #f0f4ee; }
.trip-dropdown-menu li a.current { font-weight: 600; }
.trip-dropdown-menu li.divider { border-top: 1px solid #eee; margin: 0.3rem 0; }
.trip-dropdown-menu li a.new-trip { color: #2d5016; font-weight: 500; }
.nav-back { padding: 0.2rem 0.6rem; border-radius: 4px; }
.nav-back:hover { background: rgba(255,255,255,0.1); }
```

- [ ] **Step 5: Include nav band in trip.html**

In `app/templates/trip.html`, replace the placeholder comment `{# nav band — fully wired in Phase 5 #}` with:
```html
{% include "partials/nav_band.html" %}
```

- [ ] **Step 6: Pass nav context in trip_pages.py**

In `app/routes/trip_pages.py`, replace the `TemplateResponse` call's context with:
```python
return templates.TemplateResponse("trip.html", {
    "request": request,
    "trip": trip,
    "slug": slug,
    "nav": {
        "home_href": "/",
        "trip_slug": slug,
        "trip_label": trip.name,
        "trip_dropdown": [{"slug": s["slug"], "name": s["name"]} for s in siblings],
        "prev_slug": me["prev_slug"] if me else None,
        "next_slug": me["next_slug"] if me else None,
        "show_user_pill": True,
    },
})
```

- [ ] **Step 7: Include nav band in index.html**

In `app/templates/index.html`, replace the existing `<header class="trip-header">…</header>` block with:
```html
{% include "partials/nav_band.html" %}
<header class="page-title">
  <h1>🏕 Camping Trips</h1>
  <div class="header-actions">
    <a class="btn btn-ghost" href="/overlay/" target="_blank" rel="noopener" title="Detailed map overlay">🗺 Map overlay</a>
    <button class="btn" onclick="toggleNewTrip()">+ New Trip</button>
  </div>
</header>
```

- [ ] **Step 8: Pass nav context in pages.py for index**

In `app/routes/pages.py` `def index(request)`, add to the template context dict:
```python
"nav": {"home_href": "/", "show_user_pill": True},
```

- [ ] **Step 9: Verify tests pass**

Run: `python3.11 -m pytest tests/test_templates.py tests/test_trip_pages.py tests/test_routes.py -v`
Expected: all pass (existing index test still works because the page still has "Camping Trips").

- [ ] **Step 10: Commit**

```bash
git add app/templates/partials/nav_band.html app/templates/trip.html \
        app/templates/index.html app/routes/trip_pages.py \
        app/routes/pages.py app/static/css/index.css tests/test_templates.py
git commit -m "feat(nav): shared nav band with chevrons + trip dropdown"
```

---

### Task 10: Convert overlay HTML to template + apply nav band

**Files:**
- Create: `app/templates/overlay.html`
- Modify: `app/routes/pages.py`
- Modify: `tests/test_templates.py`
- (Will delete `jeffs_osm_overlay.html` in cleanup Phase 12 — leave it in place for now to make rollback easy.)

- [ ] **Step 1: Write failing test**

Append to `tests/test_templates.py`:
```python
def test_nav_band_on_overlay_with_trip(client):
    r = client.get("/overlay/?trip=a-2026-04")
    assert r.status_code == 200
    html = r.text
    assert 'class="nav-band"' in html
    assert "Back to" in html
    assert "a-2026-04" in html


def test_nav_band_on_overlay_without_trip(client):
    r = client.get("/overlay/")
    assert r.status_code == 200
    assert 'class="nav-band"' in r.text
```

- [ ] **Step 2: Verify it fails**

Run: `python3.11 -m pytest tests/test_templates.py::test_nav_band_on_overlay_with_trip -v`
Expected: nav-band not in HTML (the static file has no nav band).

- [ ] **Step 3: Create overlay.html template**

```bash
# Start from the existing static HTML — preserve everything below <body>
mkdir -p app/templates
```

Create `app/templates/overlay.html`:
```html
{% extends "base.html" %}
{% block title %}{{ trip_label or "Map overlay" }}{% endblock %}
{% block head_extra %}
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<!-- TODO: copy the inline <style> block from jeffs_osm_overlay.html here -->
{% endblock %}
{% block body %}
{% include "partials/nav_band.html" %}
{# Map + tooling: copy the entire <body> content of jeffs_osm_overlay.html
   (the <div id="map">…</div> and the <script> blocks) below this line. #}
<!-- Paste the body of jeffs_osm_overlay.html here, preserving its structure. -->
{% endblock %}
```

Then `python3.11 - <<'PY'
from pathlib import Path
src = Path("jeffs_osm_overlay.html").read_text()
# Extract inline <style> block content
import re
style_m = re.search(r"<style>(.*?)</style>", src, re.DOTALL)
body_m = re.search(r"<body>(.*?)</body>", src, re.DOTALL)
tpl = Path("app/templates/overlay.html").read_text()
tpl = tpl.replace(
    "<!-- TODO: copy the inline <style> block from jeffs_osm_overlay.html here -->",
    "<style>" + style_m.group(1) + "</style>"
)
tpl = tpl.replace(
    "<!-- Paste the body of jeffs_osm_overlay.html here, preserving its structure. -->",
    body_m.group(1).strip()
)
Path("app/templates/overlay.html").write_text(tpl)
print("Inlined style and body from jeffs_osm_overlay.html")
PY
```

- [ ] **Step 4: Update /overlay/ route in app/routes/pages.py**

Replace `overlay_html` function with:
```python
@router.get("/overlay/", response_class=HTMLResponse)
def overlay_html(request: Request, trip: str | None = None):
    nav_ctx = {"home_href": "/", "show_user_pill": True}
    trip_label = None
    if trip:
        # Best-effort lookup; tolerate missing
        try:
            from app.services import trip_store, trips as trips_svc
            t = trip_store.load(trips_svc.TRIPS_DIR / trip)
            trip_label = t.name
            nav_ctx["back_href"] = f"/trip/{trip}"
            nav_ctx["back_label"] = f"Back to {t.name}"
        except Exception:
            pass
    return templates.TemplateResponse("overlay.html", {
        "request": request,
        "nav": nav_ctx,
        "trip_label": trip_label,
    })
```

Ensure `templates = Jinja2Templates(directory=str(JINJA_TEMPLATES_DIR))` is imported at top of `pages.py` (it likely already is). If not, add it.

- [ ] **Step 5: Update overlay JS to read trip query param**

In `app/templates/overlay.html`, inside the existing JS block, find where `manual_routes.json` is loaded. Replace any hardcoded path with:
```javascript
const tripSlug = new URLSearchParams(window.location.search).get('trip');
const manualRoutesUrl = tripSlug
  ? `/trips/${tripSlug}/manual_routes.json`
  : '/data/manual_routes.json';  // fallback
```
(If the existing overlay loads routes a different way, adapt the fetch call accordingly. Search for `manual_routes` in the file to find the relevant code.)

- [ ] **Step 6: Run tests**

Run: `python3.11 -m pytest tests/test_templates.py -v`
Expected: all 5 pass

- [ ] **Step 7: Commit**

```bash
git add app/templates/overlay.html app/routes/pages.py tests/test_templates.py
git commit -m "feat(nav): /overlay/ as Jinja template with shared nav band"
```


---

## Phase 6 — Weather + Route wired into trip page

### Task 11: route_cache service

**Files:**
- Create: `app/services/route_cache.py`
- Create: `tests/test_route_cache.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_route_cache.py
import json
from pathlib import Path

import pytest

from app.services import route_cache, db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    p = tmp_path / "x.sqlite3"
    db.init_schema(p)
    monkeypatch.setattr(db, "DATABASE_PATH", p)
    return p


def test_route_cache_uses_provider_then_caches(tmp_path, tmp_db):
    routes_path = tmp_path / "manual_routes.json"
    routes_path.write_text(json.dumps([{"name": "a"}]))
    calls = []

    def fake_provider(routes_payload, trip_slug):
        calls.append(routes_payload)
        return {"html": "<div>map</div>", "distance_km": 12.3}

    out1 = route_cache.get_route_render(routes_path, "k-2026-05",
                                        provider=fake_provider)
    out2 = route_cache.get_route_render(routes_path, "k-2026-05",
                                        provider=fake_provider)
    assert out1 == out2
    assert len(calls) == 1  # second call hit cache


def test_route_cache_invalidates_on_routes_change(tmp_path, tmp_db):
    routes_path = tmp_path / "manual_routes.json"
    routes_path.write_text(json.dumps([{"name": "a"}]))
    calls = []
    def fake(payload, slug):
        calls.append(payload)
        return {"html": str(len(calls)), "distance_km": 0}
    route_cache.get_route_render(routes_path, "x", provider=fake)
    routes_path.write_text(json.dumps([{"name": "b"}]))
    route_cache.get_route_render(routes_path, "x", provider=fake)
    assert len(calls) == 2
```

- [ ] **Step 2: Verify failing**

Run: `python3.11 -m pytest tests/test_route_cache.py -v`
Expected: ImportError on route_cache.

- [ ] **Step 3: Implement service**

```python
# app/services/route_cache.py
"""Cache rendered route HTML + computed distances per trip.

Key: (trip_slug, sha256(manual_routes.json bytes)). On cache miss, calls
the provider (which wraps build_trip._render_auto_route / route_engine).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Optional

from app.services import db

CACHE_TABLE = "route_cache"
DEFAULT_TTL = 60 * 60 * 24 * 30  # 30 days — invalidate by content hash anyway


def _hash_file(path: Path) -> str:
    if not path.exists():
        return "no-routes"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def get_route_render(routes_path: Path, trip_slug: str,
                     provider: Optional[Callable] = None) -> dict:
    """Return {html, distance_km, ...} for this trip's routes, cached.

    `provider(routes_payload: list, trip_slug: str) -> dict` does the heavy work.
    Default provider in production wraps build_trip.render_route_section logic.
    """
    h = _hash_file(routes_path)
    key = (trip_slug, h)
    cached = db.cache_get(CACHE_TABLE, key, DEFAULT_TTL)
    if cached is not None:
        return cached

    if provider is None:
        from app.services import route_provider  # default — wired in Step 5
        provider = route_provider.render

    routes_payload = (json.loads(routes_path.read_text())
                       if routes_path.exists() else [])
    payload = provider(routes_payload, trip_slug)
    db.cache_set(CACHE_TABLE, key, payload)
    return payload


def invalidate(trip_slug: str) -> None:
    """Best-effort invalidation. Drops all cache rows for this trip."""
    db.cache_drop_prefix(CACHE_TABLE, (trip_slug,))
```

- [ ] **Step 4: Verify the cache_drop_prefix helper exists**

Open `app/services/db.py`. If `cache_drop_prefix` doesn't exist, add it:
```python
def cache_drop_prefix(table: str, key_prefix: tuple) -> None:
    """Delete rows whose key starts with the given tuple prefix."""
    import json
    prefix_json = json.dumps(list(key_prefix))[:-1]  # strip trailing ]
    with _conn() as c:
        c.execute(
            f"DELETE FROM {table} WHERE key LIKE ?",
            (prefix_json + "%",)
        )
```
(If the cache keying differs from this assumption, adapt to whatever `db.cache_set/get` actually stores. The intent: delete all entries for a given trip slug.)

- [ ] **Step 5: Run tests**

Run: `python3.11 -m pytest tests/test_route_cache.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add app/services/route_cache.py app/services/db.py tests/test_route_cache.py
git commit -m "feat(route_cache): hash-keyed cache for rendered route HTML"
```

---

### Task 12: Wire weather + route into trip page render

**Files:**
- Create: `app/services/route_provider.py` (default provider wrapping existing render logic)
- Modify: `app/routes/trip_pages.py` (call services, pass to template)
- Modify: `app/templates/partials/section_route.html`
- Modify: `app/templates/partials/section_weather.html`
- Modify: `tests/test_trip_pages.py`

- [ ] **Step 1: Write provider wrapper**

```python
# app/services/route_provider.py
"""Default route renderer: wraps build_trip's route section logic.

Kept thin so route_cache can swap it out in tests.
"""

from __future__ import annotations

from typing import Any

import build_trip


def render(routes_payload: list, trip_slug: str) -> dict[str, Any]:
    """Render routes to an HTML block + summary stats."""
    if not routes_payload:
        return {"html": "", "distance_km": 0, "empty": True}
    parts = []
    total_km = 0.0
    for route in routes_payload:
        block = build_trip._render_auto_route(route)
        parts.append(block)
        total_km += float(route.get("distance_km", 0) or 0)
    return {
        "html": "\n".join(parts),
        "distance_km": round(total_km, 1),
        "empty": False,
    }
```

- [ ] **Step 2: Update trip_pages.py**

Replace the body of `trip_page()` to fetch weather + route and pass to template:
```python
@router.get("/trip/{slug}", response_class=HTMLResponse)
def trip_page(slug: str, request: Request):
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        trip = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="trip not found")

    siblings = trips_svc.list_trips_v2()
    me = next((s for s in siblings if s["slug"] == slug), None)

    # Weather (best-effort — never 500 the page over an API hiccup)
    weather_payload = None
    weather_error = None
    try:
        from app.services import weather_cache
        weather_payload = weather_cache.get_weather(
            park_key=trip.park,
            start_date=str(trip.dates.start),
            end_date=str(trip.dates.end),
        )
    except Exception as exc:
        weather_error = str(exc)

    # Route render (also best-effort)
    from app.services import route_cache
    routes_path = trip_dir / "manual_routes.json"
    route_render = {"html": "", "distance_km": 0, "empty": True}
    route_error = None
    try:
        route_render = route_cache.get_route_render(routes_path, slug)
    except Exception as exc:
        route_error = str(exc)

    return templates.TemplateResponse("trip.html", {
        "request": request,
        "trip": trip,
        "slug": slug,
        "nav": {
            "home_href": "/",
            "trip_slug": slug,
            "trip_label": trip.name,
            "trip_dropdown": [{"slug": s["slug"], "name": s["name"]}
                              for s in siblings],
            "prev_slug": me["prev_slug"] if me else None,
            "next_slug": me["next_slug"] if me else None,
            "show_user_pill": True,
        },
        "weather": weather_payload,
        "weather_error": weather_error,
        "route_render": route_render,
        "route_error": route_error,
    })
```

- [ ] **Step 3: Replace section_route.html and section_weather.html**

`app/templates/partials/section_route.html`:
```html
<section id="route" class="trip-section" data-section="route">
  <header class="section-header">
    <h2>Route</h2>
    <div class="header-actions">
      <a class="btn btn-ghost" href="/overlay/?trip={{ slug }}">Open in overlay →</a>
      <button class="btn btn-ghost edit-btn" data-section="route">Edit waypoints</button>
      <form method="post" action="/api/trips/{{ slug }}/refresh-route" style="display:inline">
        <button class="btn btn-ghost" type="submit">↻ Refresh</button>
      </form>
    </div>
  </header>
  <div class="section-body">
    {% if route_error %}
      <p class="error">Route render failed: {{ route_error }} — <a href="?">retry</a></p>
    {% elif route_render.empty %}
      <p class="empty">No routes drawn yet. <a href="/overlay/?trip={{ slug }}">Open the overlay</a> to draw one.</p>
    {% else %}
      {% if route_render.distance_km %}
      <p class="route-summary">Total distance: {{ route_render.distance_km }} km</p>
      {% endif %}
      {{ route_render.html | safe }}
    {% endif %}
  </div>
</section>
```

`app/templates/partials/section_weather.html`:
```html
<section id="weather" class="trip-section" data-section="weather">
  <header class="section-header">
    <h2>Weather</h2>
    <form method="post" action="/api/trips/{{ slug }}/refresh-weather" style="display:inline">
      <button class="btn btn-ghost" type="submit">↻ Refresh</button>
    </form>
  </header>
  <div class="section-body">
    {% if weather_error %}
      <p class="error">Weather unavailable: {{ weather_error }} — <a href="?">retry</a></p>
    {% elif weather and weather.days %}
      <div class="weather-strip">
        {% for d in weather.days %}
        <div class="weather-day">
          <div class="wx-date">{{ d.date }}</div>
          <div class="wx-temps">{{ d.high }}° / {{ d.low }}°</div>
          <div class="wx-cond">{{ d.summary }}</div>
        </div>
        {% endfor %}
      </div>
    {% else %}
      <p class="empty">No weather available.</p>
    {% endif %}
  </div>
</section>
```

- [ ] **Step 4: Update tests**

In `tests/test_trip_pages.py` `client` fixture, monkeypatch weather + route to avoid network:
```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    # ... existing setup ...
    from app.services import weather_cache, route_cache
    monkeypatch.setattr(weather_cache, "get_weather",
                         lambda **kw: {"days": [
                             {"date": "2026-05-15", "high": 18,
                              "low": 5, "summary": "sun"}]})
    monkeypatch.setattr(route_cache, "get_route_render",
                         lambda *a, **kw: {"html": "<div>fake</div>",
                                            "distance_km": 12.3,
                                            "empty": False})
    yield TestClient(app)
```

Add assertion to `test_trip_page_renders`:
```python
    assert "12.3 km" in html
    assert "sun" in html
```

- [ ] **Step 5: Run tests**

Run: `python3.11 -m pytest tests/test_trip_pages.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add app/services/route_provider.py app/routes/trip_pages.py \
        app/templates/partials/section_route.html \
        app/templates/partials/section_weather.html \
        tests/test_trip_pages.py
git commit -m "feat(trip): wire weather + route render into trip page"
```

---

### Task 13: refresh-weather + refresh-route endpoints

**Files:**
- Modify: `app/routes/trips.py`
- Modify: `tests/test_routes_trips.py`

- [ ] **Step 1: Add failing test**

```python
def test_refresh_weather_invalidates_cache(client, monkeypatch):
    from app.services import weather_cache
    calls = []
    def fake(park_key, start_date, end_date):
        calls.append((park_key, start_date, end_date))
        return {"days": []}
    monkeypatch.setattr(weather_cache, "get_weather", fake)
    # Endpoint should drop cache then return ok
    r = client.post("/api/trips/a-2026-04/refresh-weather")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_refresh_route_invalidates_cache(client):
    r = client.post("/api/trips/a-2026-04/refresh-route")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_refresh_404_for_missing_trip(client):
    r = client.post("/api/trips/nope/refresh-weather")
    assert r.status_code == 404
```

- [ ] **Step 2: Verify failing**

Run: `python3.11 -m pytest tests/test_routes_trips.py::test_refresh_weather_invalidates_cache -v`
Expected: 404 (no endpoint)

- [ ] **Step 3: Implement endpoints**

Append to `app/routes/trips.py`:
```python
from app.models import OkResponse
from app.services import db


@router.post("/trips/{slug}/refresh-weather", response_model=OkResponse)
def refresh_weather(slug: str):
    trip_dir = trips_svc.TRIPS_DIR / slug
    if not trip_store.exists(trip_dir):
        raise HTTPException(status_code=404, detail="trip not found")
    db.cache_drop_prefix("weather_cache", (trips_svc.list_trips_v2.__name__,))
    # Simpler: drop the specific key. Read trip to get park + dates.
    t = trip_store.load(trip_dir)
    db.cache_drop_prefix("weather_cache", (t.park or "", str(t.dates.start)))
    return OkResponse(ok=True, message="weather cache cleared")


@router.post("/trips/{slug}/refresh-route", response_model=OkResponse)
def refresh_route(slug: str):
    from app.services import route_cache
    trip_dir = trips_svc.TRIPS_DIR / slug
    if not trip_store.exists(trip_dir):
        raise HTTPException(status_code=404, detail="trip not found")
    route_cache.invalidate(slug)
    return OkResponse(ok=True, message="route cache cleared")
```

- [ ] **Step 4: Run tests**

Run: `python3.11 -m pytest tests/test_routes_trips.py -v`
Expected: all pass (5+)

- [ ] **Step 5: Commit**

```bash
git add app/routes/trips.py tests/test_routes_trips.py
git commit -m "feat(api): refresh-weather + refresh-route invalidation"
```


---

## Phase 7 — Editing API + shared JS edit helper

### Task 14: PATCH meta + PUT section endpoints + shared section.js helper

**Files:**
- Modify: `app/routes/trips.py`
- Modify: `app/models.py` (add request schemas)
- Create: `app/static/js/section.js` (shared helper)
- Modify: `tests/test_routes_trips.py`

- [ ] **Step 1: Failing tests**

Add to `tests/test_routes_trips.py`:
```python
def test_patch_meta_updates_fields(client):
    r = client.patch("/api/trips/a-2026-04/meta",
                      json={"access_point": "George Lake"})
    assert r.status_code == 200
    r2 = client.get("/api/trips/a-2026-04")
    assert r2.json()["access_point"] == "George Lake"


def test_put_section_replaces_gear(client):
    r = client.put("/api/trips/a-2026-04/section/gear",
                    json={"shared": [{"item": "Canoe", "who": "Alex", "notes": ""}],
                          "personal": []})
    assert r.status_code == 200
    body = client.get("/api/trips/a-2026-04").json()
    assert body["gear"]["shared"][0]["item"] == "Canoe"


def test_put_section_rejects_unknown_section(client):
    r = client.put("/api/trips/a-2026-04/section/badname",
                    json={})
    assert r.status_code == 400


def test_put_section_validates(client):
    r = client.put("/api/trips/a-2026-04/section/gear",
                    json={"shared": [{"item": 123}], "personal": []})
    assert r.status_code == 422
```

- [ ] **Step 2: Implement endpoints**

Append to `app/routes/trips.py`:
```python
from app.models_trip import (
    GearSection, FoodSlot, CostRow, PackingCategory, ItineraryDay,
    TripDates, Night, Trip,
)

SECTION_FIELD_MAP = {
    "gear":      (GearSection, "gear",      False),  # object
    "food":      (FoodSlot,    "food",      True),   # list
    "costs":     (CostRow,     "costs",     True),
    "packing":   (PackingCategory, "packing", True),
    "itinerary": (ItineraryDay, "itinerary", True),
}


@router.patch("/trips/{slug}/meta")
def patch_meta(slug: str, body: dict):
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        trip = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(404)
    allowed = {"park", "dates", "participants", "access_point", "nights"}
    bad = set(body) - allowed
    if bad:
        raise HTTPException(400, detail={"error": f"unknown fields: {bad}"})
    data = trip.model_dump()
    data.update(body)
    new_trip = Trip.model_validate(data)
    trip_store.save(trip_dir, new_trip)
    return new_trip.model_dump(mode="json")


@router.put("/trips/{slug}/section/{name}")
def put_section(slug: str, name: str, body=Body(...)):
    if name not in SECTION_FIELD_MAP:
        raise HTTPException(400, detail={"error": f"unknown section: {name}"})
    model, field, is_list = SECTION_FIELD_MAP[name]
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        trip = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(404)
    if is_list:
        validated = [model.model_validate(item) for item in body]
        data = trip.model_dump()
        data[field] = [v.model_dump() for v in validated]
    else:
        validated = model.model_validate(body)
        data = trip.model_dump()
        data[field] = validated.model_dump()
    new_trip = Trip.model_validate(data)
    trip_store.save(trip_dir, new_trip)
    return new_trip.model_dump(mode="json")
```

Add `from fastapi import Body` to the imports.

- [ ] **Step 3: Shared JS edit helper**

```javascript
// app/static/js/section.js
/**
 * Shared section edit-mode helper. Each section module calls:
 *   SectionEditor.setup({ name, readEl, renderEdit, collectEdit, slug })
 *
 * - readEl: the <section> element
 * - renderEdit(currentData) -> HTMLElement to swap in
 * - collectEdit() -> data object to PUT
 */
window.SectionEditor = (function() {
  async function loadTrip(slug) {
    const r = await fetch(`/api/trips/${slug}`);
    if (!r.ok) throw new Error('load failed');
    return r.json();
  }

  async function saveSection(slug, name, data) {
    const r = await fetch(`/api/trips/${slug}/section/${name}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    if (!r.ok) {
      const err = await r.text();
      throw new Error(`save failed: ${r.status} ${err}`);
    }
    return r.json();
  }

  function setup(opts) {
    const editBtn = opts.readEl.querySelector('.edit-btn');
    if (!editBtn) return;
    editBtn.addEventListener('click', async () => {
      const trip = await loadTrip(opts.slug);
      const currentData = trip[opts.name];
      const editView = opts.renderEdit(currentData);
      const bodyEl = opts.readEl.querySelector('.section-body');
      const original = bodyEl.innerHTML;
      bodyEl.innerHTML = '';
      bodyEl.appendChild(editView);

      const saveBtn = document.createElement('button');
      saveBtn.className = 'btn'; saveBtn.textContent = 'Save';
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'btn btn-ghost'; cancelBtn.textContent = 'Cancel';
      const toolbar = document.createElement('div');
      toolbar.className = 'edit-toolbar';
      toolbar.append(saveBtn, cancelBtn);
      bodyEl.appendChild(toolbar);

      saveBtn.onclick = async () => {
        try {
          const newData = opts.collectEdit(editView);
          await saveSection(opts.slug, opts.name, newData);
          window.location.reload();
        } catch (e) {
          alert(e.message);
        }
      };
      cancelBtn.onclick = () => { bodyEl.innerHTML = original; };
    });
  }

  return { setup, loadTrip, saveSection };
})();
```

- [ ] **Step 4: Include section.js in base.html**

Add to `app/templates/base.html` before `</body>`:
```html
<script src="/static/js/section.js"></script>
```

- [ ] **Step 5: Verify tests pass**

Run: `python3.11 -m pytest tests/test_routes_trips.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add app/routes/trips.py app/static/js/section.js \
        app/templates/base.html tests/test_routes_trips.py
git commit -m "feat(api): PATCH meta + PUT section + shared edit JS helper"
```

---

### Task 15: Gear + Costs edit UIs (table editors)

**Files:**
- Create: `app/static/js/section_gear.js`
- Create: `app/static/js/section_costs.js`
- Modify: `app/templates/trip.html` (include scripts)

- [ ] **Step 1: Implement gear edit module**

```javascript
// app/static/js/section_gear.js
(function() {
  const sectionEl = document.querySelector('[data-section="gear"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function renderEdit(gear) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `
      <h3>Shared</h3>
      <table class="gear-shared-edit"><thead>
        <tr><th>Item</th><th>Who</th><th>Notes</th><th></th></tr>
      </thead><tbody></tbody></table>
      <button class="btn btn-ghost add-shared">+ row</button>
      <h3>Personal</h3>
      <div class="personal-edit"></div>
      <button class="btn btn-ghost add-person">+ person</button>`;
    const sharedTbody = wrap.querySelector('.gear-shared-edit tbody');
    function addSharedRow(row = {item:'', who:'', notes:''}) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><input value="${row.item || ''}"></td>
        <td><input value="${row.who || ''}"></td>
        <td><input value="${row.notes || ''}"></td>
        <td><button class="btn btn-ghost delete">×</button></td>`;
      tr.querySelector('.delete').onclick = () => tr.remove();
      sharedTbody.appendChild(tr);
    }
    (gear.shared || []).forEach(addSharedRow);
    wrap.querySelector('.add-shared').onclick = () => addSharedRow();

    const personalDiv = wrap.querySelector('.personal-edit');
    function addPerson(p = {person:'', items:[]}) {
      const block = document.createElement('div');
      block.className = 'person-edit';
      block.innerHTML = `<input class="person-name" value="${p.person || ''}" placeholder="name">
        <ul class="items"></ul>
        <button class="btn btn-ghost add-item">+ item</button>
        <button class="btn btn-ghost rm-person">remove person</button>`;
      const ul = block.querySelector('.items');
      function addItem(i = {item:'', notes:''}) {
        const li = document.createElement('li');
        li.innerHTML = `<input class="i-item" value="${i.item || ''}">
          <input class="i-notes" value="${i.notes || ''}" placeholder="notes">
          <button class="btn btn-ghost rm-item">×</button>`;
        li.querySelector('.rm-item').onclick = () => li.remove();
        ul.appendChild(li);
      }
      (p.items || []).forEach(addItem);
      block.querySelector('.add-item').onclick = () => addItem();
      block.querySelector('.rm-person').onclick = () => block.remove();
      personalDiv.appendChild(block);
    }
    (gear.personal || []).forEach(addPerson);
    wrap.querySelector('.add-person').onclick = () => addPerson();
    return wrap;
  }

  function collectEdit(root) {
    const shared = [];
    root.querySelectorAll('.gear-shared-edit tbody tr').forEach(tr => {
      const inputs = tr.querySelectorAll('input');
      shared.push({item: inputs[0].value, who: inputs[1].value, notes: inputs[2].value});
    });
    const personal = [];
    root.querySelectorAll('.person-edit').forEach(block => {
      const items = [];
      block.querySelectorAll('.items li').forEach(li => {
        items.push({
          item: li.querySelector('.i-item').value,
          notes: li.querySelector('.i-notes').value,
        });
      });
      personal.push({
        person: block.querySelector('.person-name').value,
        items,
      });
    });
    return {shared, personal};
  }

  SectionEditor.setup({
    name: 'gear', readEl: sectionEl, slug,
    renderEdit, collectEdit,
  });
})();
```

- [ ] **Step 2: Implement costs edit module**

```javascript
// app/static/js/section_costs.js
(function() {
  const sectionEl = document.querySelector('[data-section="costs"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function renderEdit(costs) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `
      <table class="costs-edit"><thead>
        <tr><th>Item</th><th>Who paid</th><th>Amount</th><th>Currency</th><th></th></tr>
      </thead><tbody></tbody></table>
      <button class="btn btn-ghost add-row">+ row</button>`;
    const tbody = wrap.querySelector('tbody');
    function addRow(r = {item:'', who_paid:'', amount:'', currency:'CAD'}) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><input class="c-item" value="${r.item||''}"></td>
        <td><input class="c-who" value="${r.who_paid||''}"></td>
        <td><input class="c-amt" type="number" step="0.01" value="${r.amount ?? ''}"></td>
        <td><input class="c-cur" value="${r.currency||'CAD'}" size="4"></td>
        <td><button class="btn btn-ghost rm">×</button></td>`;
      tr.querySelector('.rm').onclick = () => tr.remove();
      tbody.appendChild(tr);
    }
    (costs || []).forEach(addRow);
    wrap.querySelector('.add-row').onclick = () => addRow();
    return wrap;
  }

  function collectEdit(root) {
    const rows = [];
    root.querySelectorAll('.costs-edit tbody tr').forEach(tr => {
      const amt = tr.querySelector('.c-amt').value;
      rows.push({
        item: tr.querySelector('.c-item').value,
        who_paid: tr.querySelector('.c-who').value,
        amount: amt === '' ? null : Number(amt),
        currency: tr.querySelector('.c-cur').value || 'CAD',
      });
    });
    return rows;
  }

  SectionEditor.setup({
    name: 'costs', readEl: sectionEl, slug,
    renderEdit, collectEdit,
  });
})();
```

- [ ] **Step 3: Wire scripts in trip.html + add data-trip-slug**

In `app/templates/trip.html`, change the body block to:
```html
{% block body %}
<body data-trip-slug="{{ slug }}">
{% include "partials/nav_band.html" %}
<div class="trip-page">
  {% include "partials/trip_header.html" %}
  {% include "partials/section_route.html" %}
  {% include "partials/section_weather.html" %}
  {% include "partials/section_itinerary.html" %}
  {% include "partials/section_gear.html" %}
  {% include "partials/section_food.html" %}
  {% include "partials/section_packing.html" %}
  {% include "partials/section_costs.html" %}
</div>
<script src="/static/js/section_gear.js"></script>
<script src="/static/js/section_costs.js"></script>
{% endblock %}
```

(Note: depending on base.html, you may already be in a `<body>` from there. If so, set `data-trip-slug` via JS in a small inline script instead:
```html
<script>document.body.dataset.tripSlug = "{{ slug }}";</script>
```)

- [ ] **Step 4: Manual verification**

```bash
python3.11 -m uvicorn app.main:app --reload --port 8000
# Open http://localhost:8000/trip/killarney-2026-05
# Click "Edit" on Gear: rows show as inputs; add row; save; reload; verify persistence.
# Same for Costs. Verify trip.json on disk has updated data.
```

- [ ] **Step 5: Commit**

```bash
git add app/static/js/section_gear.js app/static/js/section_costs.js \
        app/templates/trip.html
git commit -m "feat(edit): gear + costs inline edit modules"
```

---

### Task 16: Packing + Itinerary edit UIs

**Files:**
- Create: `app/static/js/section_packing.js`
- Create: `app/static/js/section_itinerary.js`
- Modify: `app/templates/trip.html` (include scripts)

- [ ] **Step 1: Packing edit module**

```javascript
// app/static/js/section_packing.js
(function() {
  const sectionEl = document.querySelector('[data-section="packing"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function renderEdit(packing) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `<div class="categories"></div>
      <button class="btn btn-ghost add-cat">+ category</button>`;
    const catsDiv = wrap.querySelector('.categories');
    function addCat(c = {category:'', items:[]}) {
      const block = document.createElement('div');
      block.className = 'cat-edit';
      block.innerHTML = `<input class="cat-name" value="${c.category||''}">
        <ul class="items"></ul>
        <button class="btn btn-ghost add-item">+ item</button>
        <button class="btn btn-ghost rm-cat">remove category</button>`;
      const ul = block.querySelector('.items');
      function addItem(i = {label:'', checked:false}) {
        const li = document.createElement('li');
        li.innerHTML = `<input type="checkbox" ${i.checked?'checked':''}>
          <input class="lbl" value="${i.label||''}">
          <button class="btn btn-ghost rm">×</button>`;
        li.querySelector('.rm').onclick = () => li.remove();
        ul.appendChild(li);
      }
      (c.items || []).forEach(addItem);
      block.querySelector('.add-item').onclick = () => addItem();
      block.querySelector('.rm-cat').onclick = () => block.remove();
      catsDiv.appendChild(block);
    }
    (packing || []).forEach(addCat);
    wrap.querySelector('.add-cat').onclick = () => addCat();
    return wrap;
  }

  function collectEdit(root) {
    const cats = [];
    root.querySelectorAll('.cat-edit').forEach(block => {
      const items = [];
      block.querySelectorAll('.items li').forEach(li => {
        items.push({
          label: li.querySelector('.lbl').value,
          checked: li.querySelector('input[type=checkbox]').checked,
        });
      });
      cats.push({category: block.querySelector('.cat-name').value, items});
    });
    return cats;
  }

  SectionEditor.setup({name: 'packing', readEl: sectionEl, slug,
                       renderEdit, collectEdit});
})();
```

- [ ] **Step 2: Itinerary edit module**

```javascript
// app/static/js/section_itinerary.js
(function() {
  const sectionEl = document.querySelector('[data-section="itinerary"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function renderEdit(itinerary) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `<div class="days"></div>
      <button class="btn btn-ghost add-day">+ day</button>`;
    const daysDiv = wrap.querySelector('.days');
    function addDay(d = {date:'', label:'', notes:''}) {
      const block = document.createElement('div');
      block.className = 'day-edit';
      block.innerHTML = `<div class="day-head">
          <input type="date" class="d-date" value="${d.date||''}">
          <input class="d-label" placeholder="label" value="${d.label||''}">
          <button class="btn btn-ghost rm-day">remove</button>
        </div>
        <textarea class="d-notes" rows="6">${(d.notes||'').replace(/</g,'&lt;')}</textarea>`;
      block.querySelector('.rm-day').onclick = () => block.remove();
      daysDiv.appendChild(block);
    }
    (itinerary || []).forEach(addDay);
    wrap.querySelector('.add-day').onclick = () => addDay();
    return wrap;
  }

  function collectEdit(root) {
    const days = [];
    root.querySelectorAll('.day-edit').forEach(block => {
      days.push({
        date: block.querySelector('.d-date').value,
        label: block.querySelector('.d-label').value,
        notes: block.querySelector('.d-notes').value,
      });
    });
    return days;
  }

  SectionEditor.setup({name: 'itinerary', readEl: sectionEl, slug,
                       renderEdit, collectEdit});
})();
```

- [ ] **Step 3: Include scripts**

In `app/templates/trip.html` add:
```html
<script src="/static/js/section_packing.js"></script>
<script src="/static/js/section_itinerary.js"></script>
```

- [ ] **Step 4: Manual verify + commit**

```bash
# Test in browser as in Task 15.
git add app/static/js/section_packing.js app/static/js/section_itinerary.js \
        app/templates/trip.html
git commit -m "feat(edit): packing + itinerary inline edit modules"
```

---

### Task 17: Food + Meta edit UIs

**Files:**
- Create: `app/static/js/section_food.js`
- Create: `app/static/js/section_meta.js`
- Modify: `app/templates/trip.html`

- [ ] **Step 1: Food edit module**

Similar structure to itinerary, but with per-slot items list + notes textarea. The slot kebab-case key is generated from label on save if blank:

```javascript
// app/static/js/section_food.js
(function() {
  const sectionEl = document.querySelector('[data-section="food"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function slugify(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'') || 'slot';
  }

  function renderEdit(food) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `<div class="slots"></div>
      <button class="btn btn-ghost add-slot">+ meal slot</button>`;
    const slotsDiv = wrap.querySelector('.slots');
    function addSlot(s = {slot:'', label:'', items:[], notes:''}) {
      const block = document.createElement('div');
      block.className = 'slot-edit';
      block.innerHTML = `<div class="slot-head">
          <input class="s-label" value="${s.label||''}" placeholder="meal label">
          <button class="btn btn-ghost rm-slot">remove</button></div>
        <ul class="s-items"></ul>
        <button class="btn btn-ghost add-item">+ item</button>
        <textarea class="s-notes" rows="3" placeholder="notes (markdown)">${(s.notes||'').replace(/</g,'&lt;')}</textarea>`;
      const ul = block.querySelector('.s-items');
      function addItem(i = {name:'', who:''}) {
        const li = document.createElement('li');
        li.innerHTML = `<input class="i-name" value="${i.name||''}">
          <input class="i-who" value="${i.who||''}" placeholder="who">
          <button class="btn btn-ghost rm">×</button>`;
        li.querySelector('.rm').onclick = () => li.remove();
        ul.appendChild(li);
      }
      (s.items||[]).forEach(addItem);
      block.querySelector('.add-item').onclick = () => addItem();
      block.querySelector('.rm-slot').onclick = () => block.remove();
      block.dataset.slot = s.slot || '';
      slotsDiv.appendChild(block);
    }
    (food||[]).forEach(addSlot);
    wrap.querySelector('.add-slot').onclick = () => addSlot();
    return wrap;
  }

  function collectEdit(root) {
    const out = [];
    root.querySelectorAll('.slot-edit').forEach(block => {
      const label = block.querySelector('.s-label').value;
      const slotKey = block.dataset.slot || slugify(label);
      const items = [];
      block.querySelectorAll('.s-items li').forEach(li => {
        items.push({
          name: li.querySelector('.i-name').value,
          who: li.querySelector('.i-who').value,
        });
      });
      out.push({slot: slotKey, label, items,
                notes: block.querySelector('.s-notes').value});
    });
    return out;
  }

  SectionEditor.setup({name:'food', readEl:sectionEl, slug,
                       renderEdit, collectEdit});
})();
```

- [ ] **Step 2: Meta edit module (trip header)**

```javascript
// app/static/js/section_meta.js
(function() {
  const headerEl = document.querySelector('.trip-hero');
  if (!headerEl) return;
  const slug = document.body.dataset.tripSlug;

  // Add an Edit button to the hero (since it doesn't have one in the template)
  const btn = document.createElement('button');
  btn.className = 'btn btn-ghost edit-btn';
  btn.textContent = 'Edit trip details';
  btn.style.cssText = 'position:absolute; top:1rem; right:1rem;';
  headerEl.style.position = 'relative';
  headerEl.appendChild(btn);

  btn.addEventListener('click', async () => {
    const trip = await SectionEditor.loadTrip(slug);
    const form = document.createElement('form');
    form.innerHTML = `
      <label>Park <input name="park" value="${trip.park||''}"></label>
      <label>Start <input type="date" name="start" value="${trip.dates.start}"></label>
      <label>End <input type="date" name="end" value="${trip.dates.end}"></label>
      <label>Access point <input name="access_point" value="${trip.access_point||''}"></label>
      <label>Participants (comma-sep) <input name="participants" value="${(trip.participants||[]).join(', ')}"></label>
      <h3>Nights</h3>
      <table class="nights-edit"><thead>
        <tr><th>Date</th><th>Site</th><th>Location</th><th>GPS lat</th><th>GPS lng</th><th></th></tr>
      </thead><tbody></tbody></table>
      <button type="button" class="btn btn-ghost add-night">+ night</button>
      <div class="edit-toolbar">
        <button type="submit" class="btn">Save</button>
        <button type="button" class="btn btn-ghost cancel">Cancel</button>
      </div>`;
    const tbody = form.querySelector('.nights-edit tbody');
    function addNight(n = {date:'', site:'', location:'', gps:null}) {
      const tr = document.createElement('tr');
      const lat = n.gps ? n.gps[0] : '';
      const lng = n.gps ? n.gps[1] : '';
      tr.innerHTML = `<td><input type="date" class="n-date" value="${n.date||''}"></td>
        <td><input class="n-site" value="${n.site||''}"></td>
        <td><input class="n-loc" value="${n.location||''}"></td>
        <td><input class="n-lat" value="${lat}"></td>
        <td><input class="n-lng" value="${lng}"></td>
        <td><button type="button" class="btn btn-ghost rm">×</button></td>`;
      tr.querySelector('.rm').onclick = () => tr.remove();
      tbody.appendChild(tr);
    }
    (trip.nights||[]).forEach(addNight);
    form.querySelector('.add-night').onclick = () => addNight();

    const overlay = document.createElement('div');
    overlay.className = 'meta-edit-overlay';
    overlay.appendChild(form);
    document.body.appendChild(overlay);

    form.querySelector('.cancel').onclick = () => overlay.remove();
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const nights = [];
      tbody.querySelectorAll('tr').forEach(tr => {
        const lat = tr.querySelector('.n-lat').value;
        const lng = tr.querySelector('.n-lng').value;
        nights.push({
          date: tr.querySelector('.n-date').value,
          site: tr.querySelector('.n-site').value,
          location: tr.querySelector('.n-loc').value,
          gps: (lat && lng) ? [Number(lat), Number(lng)] : null,
        });
      });
      const fd = new FormData(form);
      const body = {
        park: fd.get('park'),
        dates: {start: fd.get('start'), end: fd.get('end')},
        access_point: fd.get('access_point'),
        participants: fd.get('participants').split(',').map(s => s.trim()).filter(Boolean),
        nights,
      };
      const r = await fetch(`/api/trips/${slug}/meta`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      if (!r.ok) { alert('save failed: ' + await r.text()); return; }
      window.location.reload();
    });
  });
})();
```

- [ ] **Step 3: Include scripts + add meta-edit overlay styles to trip.css**

In `app/templates/trip.html`:
```html
<script src="/static/js/section_food.js"></script>
<script src="/static/js/section_meta.js"></script>
```

Append to `app/static/css/trip.css`:
```css
.meta-edit-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5);
                     display: flex; align-items: center; justify-content: center;
                     z-index: 1000; }
.meta-edit-overlay form { background: white; padding: 1.5rem;
                          border-radius: 10px; max-width: 700px; width: 100%;
                          max-height: 90vh; overflow: auto; }
.meta-edit-overlay form label { display: block; margin-bottom: 0.5rem; }
.edit-toolbar { display: flex; gap: 0.5rem; margin-top: 1rem; }
```

- [ ] **Step 4: Manual verify + commit**

```bash
# Browser test: edit trip metadata, edit food slots, verify persistence.
git add app/static/js/section_food.js app/static/js/section_meta.js \
        app/templates/trip.html app/static/css/trip.css
git commit -m "feat(edit): food + trip meta inline editors"
```

---

## Phase 8 — Lightweight route inline editing

### Task 18: Reorder / rename / delete waypoints on trip page

**Files:**
- Modify: `app/routes/trips.py` (PUT /api/trips/<slug>/routes endpoint for manual_routes.json)
- Create: `app/static/js/section_route.js`
- Modify: `app/templates/partials/section_route.html` (already has edit btn from Task 12)
- Modify: `app/templates/trip.html`

- [ ] **Step 1: Endpoint — PUT manual_routes.json**

Append to `app/routes/trips.py`:
```python
import json as _json

@router.put("/trips/{slug}/routes")
def put_routes(slug: str, body=Body(...)):
    trip_dir = trips_svc.TRIPS_DIR / slug
    if not trip_store.exists(trip_dir):
        raise HTTPException(404)
    if not isinstance(body, list):
        raise HTTPException(400, detail={"error": "expected list of routes"})
    (trip_dir / "manual_routes.json").write_text(
        _json.dumps(body, indent=2) + "\n", encoding="utf-8"
    )
    # Invalidate route cache so the next page render recomputes
    from app.services import route_cache
    route_cache.invalidate(slug)
    return {"ok": True}


@router.get("/trips/{slug}/routes")
def get_routes(slug: str):
    trip_dir = trips_svc.TRIPS_DIR / slug
    p = trip_dir / "manual_routes.json"
    if not p.exists():
        return []
    return _json.loads(p.read_text())
```

- [ ] **Step 2: Test endpoint**

Add to `tests/test_routes_trips.py`:
```python
def test_put_routes_writes_file(client, tmp_path):
    r = client.put("/api/trips/a-2026-04/routes",
                    json=[{"name": "Day 1 paddle", "waypoints": []}])
    assert r.status_code == 200
    r2 = client.get("/api/trips/a-2026-04/routes")
    assert r2.json()[0]["name"] == "Day 1 paddle"
```

Run: `python3.11 -m pytest tests/test_routes_trips.py::test_put_routes_writes_file -v`
Expected: pass.

- [ ] **Step 3: Route inline edit JS**

```javascript
// app/static/js/section_route.js
(function() {
  const sectionEl = document.querySelector('[data-section="route"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;
  const btn = sectionEl.querySelector('.edit-btn');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const r = await fetch(`/api/trips/${slug}/routes`);
    const routes = await r.json();
    const wrap = document.createElement('div');
    wrap.innerHTML = `<p class="hint">Reorder, rename, or remove waypoints.
      To draw new lines, use <a href="/overlay/?trip=${slug}">the overlay</a>.</p>
      <div class="routes-edit"></div>`;
    const routesDiv = wrap.querySelector('.routes-edit');
    routes.forEach((route, i) => {
      const block = document.createElement('div');
      block.className = 'route-edit';
      block.dataset.index = i;
      block.innerHTML = `<h4><input class="r-name" value="${route.name||''}"></h4>
        <ul class="waypoints"></ul>
        <button class="btn btn-ghost rm-route">remove this route</button>`;
      const ul = block.querySelector('.waypoints');
      (route.waypoints || []).forEach((w, j) => {
        const li = document.createElement('li');
        li.draggable = true;
        li.dataset.index = j;
        li.innerHTML = `<span class="drag">⋮⋮</span>
          <input class="w-name" value="${w.name||''}">
          <span class="coords">${w.lat?.toFixed(4)}, ${w.lng?.toFixed(4)}</span>
          <button class="btn btn-ghost rm-wp">×</button>`;
        li.querySelector('.rm-wp').onclick = () => li.remove();
        // Drag reorder
        li.addEventListener('dragstart', e => {
          e.dataTransfer.setData('text/plain', j);
        });
        li.addEventListener('dragover', e => e.preventDefault());
        li.addEventListener('drop', e => {
          e.preventDefault();
          const from = Number(e.dataTransfer.getData('text/plain'));
          const items = Array.from(ul.children);
          ul.insertBefore(items[from], li);
        });
        ul.appendChild(li);
      });
      block.querySelector('.rm-route').onclick = () => block.remove();
      routesDiv.appendChild(block);
    });

    const body = sectionEl.querySelector('.section-body');
    const original = body.innerHTML;
    body.innerHTML = '';
    body.appendChild(wrap);
    const toolbar = document.createElement('div');
    toolbar.className = 'edit-toolbar';
    toolbar.innerHTML = `<button class="btn save">Save</button>
      <button class="btn btn-ghost cancel">Cancel</button>`;
    body.appendChild(toolbar);
    toolbar.querySelector('.cancel').onclick = () => { body.innerHTML = original; };
    toolbar.querySelector('.save').onclick = async () => {
      const out = [];
      routesDiv.querySelectorAll('.route-edit').forEach(block => {
        const i = Number(block.dataset.index);
        const orig = routes[i];
        const waypoints = [];
        block.querySelectorAll('.waypoints li').forEach(li => {
          const j = Number(li.dataset.index);
          const origWp = (orig.waypoints || [])[j];
          waypoints.push({...origWp, name: li.querySelector('.w-name').value});
        });
        out.push({...orig, name: block.querySelector('.r-name').value, waypoints});
      });
      const resp = await fetch(`/api/trips/${slug}/routes`, {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(out),
      });
      if (!resp.ok) { alert('save failed: ' + await resp.text()); return; }
      window.location.reload();
    };
  });
})();
```

- [ ] **Step 4: Include script**

In `app/templates/trip.html`:
```html
<script src="/static/js/section_route.js"></script>
```

- [ ] **Step 5: Manual verify + commit**

```bash
# Browser: click Edit waypoints, drag-reorder, rename, delete, save.
# Verify trips/<slug>/manual_routes.json updated.
git add app/routes/trips.py app/static/js/section_route.js \
        app/templates/trip.html tests/test_routes_trips.py
git commit -m "feat(edit): inline waypoint reorder/rename/delete on trip page"
```


---

## Phase 9 — Create + Delete

### Task 19: POST /api/trips (create) and DELETE /api/trips/<slug>

**Files:**
- Modify: `app/routes/trips.py`
- Modify: `app/services/trips.py` (add JSON-aware create helper)
- Modify: `tests/test_routes_trips.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_routes_trips.py`:
```python
def test_post_create_writes_trip_json(client, tmp_path):
    r = client.post("/api/trips", json={
        "park": "killarney", "start": "2027-06-01", "end": "2027-06-04",
        "participants": ["Alex"],
    })
    assert r.status_code == 200
    slug = r.json()["slug"]
    assert slug == "killarney-2027-06"
    body = client.get(f"/api/trips/{slug}").json()
    assert body["dates"]["start"] == "2027-06-01"
    assert body["participants"] == ["Alex"]


def test_post_create_409_on_duplicate(client):
    payload = {"park": "killarney", "start": "2027-06-01",
                "end": "2027-06-04", "participants": []}
    client.post("/api/trips", json=payload)
    r = client.post("/api/trips", json=payload)
    assert r.status_code == 409


def test_delete_trip_removes_dir(client):
    r = client.delete("/api/trips/a-2026-04")
    assert r.status_code == 200
    r2 = client.get("/api/trips/a-2026-04")
    assert r2.status_code == 404
```

- [ ] **Step 2: Implement create helper in services/trips.py**

```python
def create_trip_v2(park: str, start_date, end_date, participants: list[str]) -> str:
    """Create a new trip directory with trip.json. Returns the slug."""
    from datetime import date as _date
    if not park:
        raise ValueError("park required")
    sd = _date.fromisoformat(str(start_date))
    ed = _date.fromisoformat(str(end_date))
    if ed < sd:
        raise ValueError("end date before start")
    slug = f"{park}-{sd.year:04d}-{sd.month:02d}"
    trip_dir = TRIPS_DIR / slug
    if trip_dir.exists():
        raise FileExistsError(slug)
    trip_dir.mkdir(parents=True)
    from app.models_trip import Trip, TripDates
    trip = Trip(
        schema_version=1, name=slug, park=park,
        dates=TripDates(start=sd, end=ed),
        participants=participants or [], access_point="",
    )
    trip_store.save(trip_dir, trip)
    return slug
```

- [ ] **Step 3: Endpoints**

Append to `app/routes/trips.py`:
```python
from pydantic import BaseModel
from datetime import date as _date_t


class CreateTripRequest(BaseModel):
    park: str
    start: _date_t
    end: _date_t
    participants: list[str] = []


@router.post("/trips")
def create_trip(body: CreateTripRequest):
    try:
        slug = trips_svc.create_trip_v2(
            park=body.park, start_date=body.start, end_date=body.end,
            participants=body.participants,
        )
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail={"error": f"trip exists: {e}"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    return {"ok": True, "slug": slug}


@router.delete("/trips/{slug}")
def delete_trip(slug: str):
    import shutil
    trip_dir = trips_svc.TRIPS_DIR / slug
    if not trip_dir.exists():
        raise HTTPException(404)
    shutil.rmtree(trip_dir)
    return {"ok": True}
```

- [ ] **Step 4: Run tests**

Run: `python3.11 -m pytest tests/test_routes_trips.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add app/routes/trips.py app/services/trips.py tests/test_routes_trips.py
git commit -m "feat(api): POST /api/trips create + DELETE /api/trips/<slug>"
```

---

## Phase 10 — Cutover

### Task 20: Switch trip_card link + update index.js + remove deprecated routes

**Files:**
- Modify: `app/templates/partials/trip_card.html`
- Modify: `app/static/js/index.js`
- Modify: `app/templates/index.html` (use /api/trips list)
- Modify: `app/routes/pages.py` (index now reads via list_trips_v2)
- Modify: `app/routes/trips.py` (delete old `/api/new-trip`, `/api/save-gear`, `/api/rebuild`)

- [ ] **Step 1: trip_card.html — change link**

In `app/templates/partials/trip_card.html`, change:
```html
<a class="btn" href="/trips/{{ trip.name }}/trip.html" target="_blank">Open Trip</a>
```
to:
```html
<a class="btn" href="/trip/{{ trip.name }}">Open Trip</a>
```
(removed `target="_blank"` — same-tab nav since the new page has a back-button via nav band.)

- [ ] **Step 2: pages.py — use list_trips_v2**

In `app/routes/pages.py` `def index(request)`, replace the existing trip-discovery code with:
```python
entries = trips_svc.list_trips_v2()
upcoming = [e for e in entries if e["start"] >= _today()]
past = [e for e in entries if e["start"] < _today()]
# adapt to match what the template expects — fields: name, park_name,
# start_date, end_date, participant_count
def _shape(e):
    return {
        "name": e["slug"], "park_name": e["park_name"] or e["park"],
        "start_date": str(e["start"]), "end_date": str(e["end"]),
        "participant_count": e["participant_count"],
        "days_label": "",  # compute if needed
    }
return templates.TemplateResponse("index.html", {
    "request": request,
    "upcoming": [_shape(e) for e in upcoming],
    "past":     [_shape(e) for e in past],
    "broken":   [],  # JSON-load failures are silently dropped by list_trips_v2
    "park_options": _park_options(),
    "nav": {"home_href": "/", "show_user_pill": True},
})
```
Add helpers `def _today(): from datetime import date; return date.today()` and `def _park_options(): ...` (extract from existing code; load `parks.json` and return `[(slug, name), ...]`).

- [ ] **Step 3: index.js — call new endpoints**

In `app/static/js/index.js`, find `createTrip` and `rebuild` functions. Change:
- `createTrip`: POST `/api/trips` instead of `/api/new-trip`, parse `slug` from response (was `trip_dir`), redirect to `/trip/${slug}`.
- `rebuild`: REMOVE entirely (no more build step). Also remove the "Rebuild" button from `trip_card.html`:

```html
{# remove: <button class="btn secondary" onclick="rebuild(this, '{{ trip.name }}')">Rebuild</button> #}
```

Replace `createTrip(event)` body:
```javascript
async function createTrip(event) {
  event.preventDefault();
  const fd = new FormData(event.target);
  const r = await fetch('/api/trips', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      park: fd.get('park'),
      start: fd.get('start'),
      end: fd.get('end'),
      participants: (fd.get('participants') || '').split(',').map(s => s.trim()).filter(Boolean),
    }),
  });
  if (!r.ok) { alert('create failed: ' + await r.text()); return; }
  const {slug} = await r.json();
  window.location.href = `/trip/${slug}`;
}
```

- [ ] **Step 4: Remove deprecated server-side endpoints**

In `app/routes/trips.py`, delete the `@router.post("/new-trip", ...)`, `@router.post("/rebuild", ...)`, and `@router.post("/save-gear", ...)` handler functions. Their tests in `tests/test_routes.py` will fail — update those tests to point at the new endpoints, OR remove the now-obsolete tests if covered by `tests/test_routes_trips.py`.

- [ ] **Step 5: Run full test suite**

Run: `python3.11 -m pytest tests/ -v`
Expected: all pass. Fix any test that was hard-coded against the old endpoints (most likely `test_routes.py::test_new_trip_creates_directory` etc).

- [ ] **Step 6: Manual smoke**

```bash
python3.11 -m uvicorn app.main:app --reload --port 8000
# Visit http://localhost:8000/
# - Click "Open Trip" on the killarney card → should land on /trip/killarney-2026-05
# - Use nav band: home link, prev/next chevrons, dropdown
# - Open /overlay/ → click home → back at /
# - Visit /overlay/?trip=killarney-2026-05 → "Back to" link works
```

- [ ] **Step 7: Commit**

```bash
git add app/templates/partials/trip_card.html app/static/js/index.js \
        app/templates/index.html app/routes/pages.py app/routes/trips.py \
        tests/test_routes.py
git commit -m "refactor: cut over index + cards to /trip/<slug> and /api/trips/*"
```

---

## Phase 11 — Cleanup

### Task 21: Delete build_trip.py, weather.py, old MD files, old tests

**Files removed:**
- `build_trip.py`
- `weather.py` (only if no remaining importer; verify with grep)
- `tests/test_build_trip.py`
- `tests/test_md_table.py`
- `jeffs_osm_overlay.html` (replaced by `app/templates/overlay.html`)
- `trips/killarney-2026-05/_archive/` (archived MDs from Phase 2)
- `trips/killarney-2026-05/trip.html` (no longer served)
- `app/services/trips.py:replace_first_table` (MD-table editing — unused after cutover)

- [ ] **Step 1: Verify nothing imports build_trip outside route_provider**

```bash
grep -rn "import build_trip\|from build_trip" /Users/alex/Documents/camping-planner/ \
  --include="*.py" | grep -v ".claude/" | grep -v "_archive/"
```
Expected: only `app/services/route_provider.py` and `app/services/trips.py` (the latter uses `build_trip._load_park_info` — still needed unless moved).

If `trips.py` still needs `_load_park_info`, copy it into `app/services/parks.py` or inline it. Replace the `import build_trip` references.

- [ ] **Step 2: Verify nothing imports weather**

```bash
grep -rn "import weather\b\|from weather " /Users/alex/Documents/camping-planner/ \
  --include="*.py" | grep -v ".claude/"
```
Expected: only `app/services/weather_cache.py`. If so, you have two options: (a) keep `weather.py` as-is — it's the HTTP-call boundary; (b) move its contents into `weather_cache.py` and remove. Option (a) is safer — KEEP `weather.py`.

- [ ] **Step 3: Migrate park-info helper out of build_trip**

Create `app/services/parks.py`:
```python
"""Park metadata lookup. Reads parks.json."""

import json
from pathlib import Path

from app.config import PARKS_JSON


def load_park_info(park_slug: str) -> dict:
    if not park_slug or not PARKS_JSON.exists():
        return {}
    parks = json.loads(PARKS_JSON.read_text())
    if isinstance(parks, list):
        for p in parks:
            if p.get("slug") == park_slug:
                return p
        return {}
    return parks.get(park_slug, {}) if isinstance(parks, dict) else {}
```

Update `app/services/trips.py`: replace `build_trip._load_park_info(...)` calls with `parks_svc.load_park_info(...)`. Drop the `import build_trip` line.

- [ ] **Step 4: Replace route_provider import**

In `app/services/route_provider.py`, replace `import build_trip` and `build_trip._render_auto_route(route)` with a self-contained renderer. Easiest: copy the body of `build_trip._render_auto_route` into `route_provider.py` as a private function. Same for any other build_trip internals it uses (e.g., `_load_manual_routes`).

After this step, `grep -rn "import build_trip" app/` should return nothing.

- [ ] **Step 5: Run full test suite**

```bash
python3.11 -m pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 6: Delete files**

```bash
git rm build_trip.py jeffs_osm_overlay.html \
       tests/test_build_trip.py tests/test_md_table.py \
       trips/killarney-2026-05/trip.html
# Note: weather.py is KEPT (still imported by weather_cache).
# trips/killarney-2026-05/_archive/ is your judgment call — delete now or later.
```

Also remove the `replace_first_table` function and `_MD_TABLE_RE` from `app/services/trips.py` if nothing references them after cutover.

- [ ] **Step 7: Run tests one more time**

```bash
python3.11 -m pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 8: Manual final smoke**

```bash
python3.11 -m uvicorn app.main:app --reload --port 8000
# Click through every section's edit on /trip/killarney-2026-05
# /overlay/?trip=... — back link works; route edits in /overlay/ still save to manual_routes.json
# Sibling-trip nav: create a second trip via "+ New trip", confirm prev/next + dropdown work
```

- [ ] **Step 9: Final commit**

```bash
git add app/services/parks.py app/services/trips.py app/services/route_provider.py
git commit -m "chore: remove build_trip.py + old MD-driven pipeline"
```

If the working tree still has the deletion changes from `git rm`, they were already staged — `git status` should be clean.

- [ ] **Step 10: Archive cleanup (optional)**

```bash
# When confident: delete the .md backups
rm -rf trips/killarney-2026-05/_archive/
git rm -r trips/killarney-2026-05/_archive/  # if tracked
git commit -m "chore: drop _archive/ md backups for killarney-2026-05"
```

---

## Spec coverage self-check

| Spec section | Tasks covering it |
|---|---|
| trip.json schema (v1) | Task 1 |
| trip_store load/save with version guard | Task 2 |
| Migration script (md → json) | Tasks 3, 4 |
| Migrate existing killarney trip | Task 5 |
| `GET /api/trips` list with prev/next | Task 6 |
| `GET /api/trips/<slug>` | Task 7 |
| Server-rendered `GET /trip/<slug>` | Task 8 |
| All section read-only partials | Task 8 |
| Shared nav band + index integration | Task 9 |
| Overlay → template + nav band + `?trip=` support | Task 10 |
| Route cache service | Task 11 |
| Weather + route wired into trip page render | Task 12 |
| `refresh-weather` + `refresh-route` endpoints | Task 13 |
| `PATCH /api/trips/<slug>/meta` + `PUT .../section/<name>` + shared JS helper | Task 14 |
| Inline edit: gear, costs | Task 15 |
| Inline edit: packing, itinerary | Task 16 |
| Inline edit: food, trip meta | Task 17 |
| Lightweight route inline editing | Task 18 |
| `POST /api/trips` (create) + `DELETE /api/trips/<slug>` | Task 19 |
| Cutover: trip_card link, index.js, deprecated endpoints removed | Task 20 |
| Cleanup: delete build_trip.py + old MD + tests | Task 21 |

All spec sections accounted for.

## Notes for the executor

- **Never** `git add .` / `git add -A` — the branch has 26 unrelated dirty/untracked files. Always stage specific files.
- Tests must use `python3.11 -m pytest` (project rule).
- Tests must never hit Open-Meteo or Ontario Parks — mock at the service boundary.
- The branch is `local/water-polygon-union`. Do NOT merge `origin/main` — that's deferred per the spec.
- If a step fails: read carefully, fix root cause, don't `--no-verify` past hook failures, don't `git reset --hard`.
- Manual verification at end of Phase 10 and Phase 11 is required — both phases mention browser smoke tests.

## What's deliberately out of scope (do not implement)

- Linking `food[].items` to the `camping-planner-food/foods.yaml` library
- Multi-user concurrent editing / ETags
- Mobile responsive polish beyond what current layout already provides
- JS test framework / browser automation
- Merging `origin/main` into this branch
