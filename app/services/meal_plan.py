"""Per-trip meal-plan I/O.

The plan lives as YAML frontmatter in `trips/<slug>/food.md`. The body below
the frontmatter is regenerated on every save (see Task 7). When a trip's
food.md has no frontmatter (legacy / fresh trip), `load()` returns an empty
plan scaffolded from the trip dates and exposes the legacy prose under
`legacy_body` so the UI can warn before it overwrites.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import yaml

from app.config import TRIPS_DIR

ACTIVITY_DEFAULTS = {
    "backcountry": 4000,
    "bikepacking": 4500,
    "boat-camping": 3500,
    "car-camping": 2500,
}

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL,
)


def _trip_dir(slug: str) -> Path:
    d = TRIPS_DIR / slug
    if not d.is_dir():
        raise FileNotFoundError(f"trip not found: {slug}")
    return d


def _read_trip_frontmatter(trip_dir: Path) -> dict:
    """Read the YAML frontmatter from trip.md (start_date, end_date, participants)."""
    text = (trip_dir / "trip.md").read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def _scaffold_days(start: str, end: str) -> list[dict]:
    """Return [{date, label, meals: []}, ...] for every day in the range, inclusive."""
    if not start or not end:
        return []
    s = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    days: list[dict] = []
    cur = s
    while cur <= e:
        days.append({
            "date": cur.isoformat(),
            "label": cur.strftime("%A"),
            "meals": [],
        })
        cur += datetime.timedelta(days=1)
    return days


def _empty_plan(trip_fm: dict) -> dict:
    return {
        "calorie_target": {
            "activity_level": "backcountry",
            "kcal_per_person_per_day": ACTIVITY_DEFAULTS["backcountry"],
        },
        "participants": list(trip_fm.get("participants") or []),
        "days": _scaffold_days(
            str(trip_fm.get("start_date") or ""),
            str(trip_fm.get("end_date") or ""),
        ),
    }


def load(slug: str) -> dict:
    """Return the meal plan for a trip.

    Shape:
        {
          "calorie_target": {"activity_level": str, "kcal_per_person_per_day": int},
          "participants": [str, ...],
          "days": [{"date": "YYYY-MM-DD", "label": str, "meals": [{...}]}, ...],
          "legacy_body": str   # populated only when food.md had no frontmatter
        }
    """
    trip_dir = _trip_dir(slug)
    trip_fm = _read_trip_frontmatter(trip_dir)
    food_md = trip_dir / "food.md"
    raw = food_md.read_text(encoding="utf-8") if food_md.exists() else ""
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        plan = _empty_plan(trip_fm)
        plan["legacy_body"] = raw.strip()
        return plan
    plan_fm = yaml.safe_load(m.group(1)) or {}
    plan = {
        "calorie_target": plan_fm.get("calorie_target") or {
            "activity_level": "backcountry",
            "kcal_per_person_per_day": ACTIVITY_DEFAULTS["backcountry"],
        },
        "participants": list(trip_fm.get("participants") or []),
        "days": plan_fm.get("days") or _scaffold_days(
            str(trip_fm.get("start_date") or ""),
            str(trip_fm.get("end_date") or ""),
        ),
        "legacy_body": "",
    }
    return plan
