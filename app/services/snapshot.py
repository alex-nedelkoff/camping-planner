"""Render food_items / gear_items rows back to deterministic markdown.

Output is byte-stable: same rows always produce the same string. Pipe
characters in user-entered text are escaped (`\\|`).
"""

from __future__ import annotations

from pathlib import Path

from app.services import food_repo, gear_repo

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
