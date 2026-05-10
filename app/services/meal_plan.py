"""Per-trip meal-plan I/O.

The plan lives as YAML frontmatter in `trips/<slug>/food.md`. The body below
the frontmatter is regenerated on every save (see Task 7). When a trip's
food.md has no frontmatter (legacy / fresh trip), `load()` returns an empty
plan scaffolded from the trip dates and exposes the legacy prose under
`legacy_body` so the UI can warn before it overwrites.
"""

from __future__ import annotations

import datetime
import os
import re
import tempfile
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


def compute_totals(plan: dict, catalog: dict) -> dict:
    """Compute per-meal / per-day / trip kcal + target + delta.

    Returns a parallel structure: {days: [{...meals: [{...items: [{kcal,
    unknown_food}], kcal}], kcal}], trip_kcal, target_kcal, delta_kcal}.
    """
    by_id = {f["id"]: f for f in catalog.get("foods", [])}
    out_days = []
    trip_kcal = 0
    for day in plan.get("days", []):
        out_meals = []
        day_kcal = 0
        for meal in day.get("meals", []):
            out_items = []
            meal_kcal = 0
            for item in meal.get("items", []):
                food = by_id.get(item.get("food_id"))
                if food is None:
                    out_items.append({**item, "kcal": None, "unknown_food": True})
                    continue
                servings = int(item.get("servings") or 0)
                kcal = servings * int(food["kcal_per_serving"])
                meal_kcal += kcal
                out_items.append({**item, "kcal": kcal, "unknown_food": False})
            out_meals.append({**meal, "items": out_items, "kcal": meal_kcal})
            day_kcal += meal_kcal
        out_days.append({**day, "meals": out_meals, "kcal": day_kcal})
        trip_kcal += day_kcal
    target_kcal = (
        len(plan.get("days", []))
        * len(plan.get("participants") or [])
        * int(plan.get("calorie_target", {}).get("kcal_per_person_per_day") or 0)
    )
    return {
        "days": out_days,
        "trip_kcal": trip_kcal,
        "target_kcal": target_kcal,
        "delta_kcal": trip_kcal - target_kcal,
    }


_MEAL_TITLE_CASE = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snack": "Snack",
}


def _name_for(food_id: str, by_id: dict) -> str:
    food = by_id.get(food_id)
    return food["name"] if food else f"Unknown ({food_id})"


def render_markdown_body(plan: dict, catalog: dict) -> str:
    """Build the human-readable markdown body from a plan + catalog."""
    by_id = {f["id"]: f for f in catalog.get("foods", [])}
    totals = compute_totals(plan, catalog)
    days = len(plan.get("days") or [])
    people = len(plan.get("participants") or [])
    kcd = int(plan.get("calorie_target", {}).get("kcal_per_person_per_day") or 0)
    target = kcd * people * days

    lines: list[str] = ["# Food plan", ""]
    lines.append(
        f"Calorie target: **{kcd} kcal/person/day × {people} people × "
        f"{days} days = {target:,} kcal**"
    )
    lines.append("")
    for day, day_totals in zip(plan.get("days") or [], totals["days"]):
        lines.append(
            f"## {day.get('label', '')} ({day.get('date', '')}) — "
            f"{day_totals['kcal']} kcal"
        )
        for meal in day_totals["meals"]:
            meal_name = _MEAL_TITLE_CASE.get(meal.get("meal", ""), meal.get("meal", "").title())
            for item in meal["items"]:
                kcal_str = "?" if item.get("kcal") is None else str(item["kcal"])
                who = item.get("who") or "shared"
                note = item.get("note") or ""
                note_suffix = f" — {note}" if note else ""
                lines.append(
                    f"- **{meal_name}** — {_name_for(item['food_id'], by_id)} × "
                    f"{item.get('servings', 0)} ({kcal_str} kcal) — {who}{note_suffix}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix="food-", suffix=".md", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(slug: str, plan: dict, catalog: dict) -> None:
    """Rewrite trips/<slug>/food.md with YAML frontmatter + regenerated body."""
    trip_dir = _trip_dir(slug)
    fm_dump = yaml.safe_dump(
        {
            "calorie_target": plan.get("calorie_target") or {
                "activity_level": "backcountry",
                "kcal_per_person_per_day": ACTIVITY_DEFAULTS["backcountry"],
            },
            "days": plan.get("days") or [],
        },
        sort_keys=False,
        allow_unicode=True,
    )
    body = render_markdown_body(plan, catalog)
    text = (
        "---\n"
        f"{fm_dump}"
        "---\n\n"
        "<!-- generated from frontmatter on save; edit via UI -->\n"
        f"{body}"
    )
    _atomic_write(trip_dir / "food.md", text)
