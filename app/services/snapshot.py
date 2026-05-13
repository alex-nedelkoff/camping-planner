"""Render food_items / gear_items rows back to deterministic markdown.

Output is byte-stable: same rows always produce the same string. Pipe
characters in user-entered text are escaped (`\\|`).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.services import db, food_repo, gear_repo

MEAL_LABEL = {
    "breakfast": "Breakfast", "lunch": "Lunch",
    "dinner": "Dinner", "snack": "Snack",
}
MEAL_ORDER = ["breakfast", "lunch", "dinner", "snack"]


def _esc(text: str | None) -> str:
    return (text or "").replace("|", r"\|")


def render_food_markdown(slug: str, path: Path | None = None) -> str:
    rows = food_repo.list_for_trip(slug, path=path)
    by_day: dict[int, dict[str, list[dict]]] = {}
    for r in rows:
        by_day.setdefault(r["day_index"], {}).setdefault(r["meal"], []).append(r)
    out: list[str] = ["# Food Plan", ""]
    for day in sorted(by_day):
        out.append(f"## Day {day}")
        out.append("")
        out.append("| Meal | Item | Who | Notes |")
        out.append("|---|---|---|---|")
        for meal in MEAL_ORDER:
            for r in by_day[day].get(meal, []):
                out.append(
                    f"| {MEAL_LABEL[meal]} | {_esc(r['item'])} "
                    f"| {_esc(r['assigned_to'])} | {_esc(r['notes'])} |"
                )
        # any meals not in MEAL_ORDER
        for meal, rs in by_day[day].items():
            if meal in MEAL_ORDER:
                continue
            for r in rs:
                out.append(
                    f"| {meal.title()} | {_esc(r['item'])} "
                    f"| {_esc(r['assigned_to'])} | {_esc(r['notes'])} |"
                )
        out.append("")
    return "\n".join(out)


def render_gear_markdown(slug: str, path: Path | None = None) -> str:
    rows = gear_repo.list_for_trip(slug, path=path)
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    out: list[str] = ["# Gear", ""]
    for cat in sorted(by_cat):
        out.append(f"## {cat}")
        out.append("")
        out.append("| Item | Qty | Who | Notes |")
        out.append("|---|---|---|---|")
        for r in by_cat[cat]:
            out.append(
                f"| {_esc(r['item'])} | {_esc(r['quantity'])} "
                f"| {_esc(r['assigned_to'])} | {_esc(r['notes'])} |"
            )
        out.append("")
    return "\n".join(out)


def _record_snapshotted(
    slug: str, section: str, path: Path | None = None,
) -> None:
    iso = datetime.now(timezone.utc).isoformat()
    with db.connect(path) as conn:
        conn.execute(
            "INSERT INTO section_state "
            "(trip_slug, section, last_snapshotted_at) VALUES (?, ?, ?) "
            "ON CONFLICT(trip_slug, section) DO UPDATE SET "
            "last_snapshotted_at = excluded.last_snapshotted_at",
            (slug, section, iso),
        )


def write_snapshot(
    slug: str,
    trip_dir: Path,
    *,
    run_build_trip: bool = True,
    path: Path | None = None,
) -> dict:
    """Render food.md + gear.md from DB rows, write to disk, stamp state.

    When `run_build_trip` is True, also shells out to `build_trip.py` to
    regenerate the static `trip.html`. The DB row state is the source of
    truth; markdown + HTML are derived artifacts.
    """
    trip_dir.mkdir(parents=True, exist_ok=True)
    food_path = trip_dir / "food.md"
    gear_path = trip_dir / "gear.md"
    food_path.write_text(render_food_markdown(slug, path=path))
    gear_path.write_text(render_gear_markdown(slug, path=path))
    _record_snapshotted(slug, "food", path=path)
    _record_snapshotted(slug, "gear", path=path)
    if run_build_trip:
        from app.config import REPO_ROOT
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "build_trip.py"), str(trip_dir)],
            check=True,
        )
    return {"food": str(food_path), "gear": str(gear_path)}
