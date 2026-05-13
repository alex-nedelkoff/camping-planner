"""Parse food.md / gear.md markdown tables into DB rows. Idempotent.

Recognises the markdown structure produced by build_trip.py / the trip
template — `## Day N — <weekday>` for food, `## <category>` for gear.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from app.services import auth, db, food_repo, gear_repo


MEAL_NORM = {
    "breakfast": "breakfast", "lunch": "lunch",
    "dinner": "dinner", "snack": "snack",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_section_seeded(slug: str, section: str, path: Path | None) -> bool:
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT seeded_from_md_at FROM section_state "
            "WHERE trip_slug = ? AND section = ?",
            (slug, section),
        ).fetchone()
    return row is not None and row["seeded_from_md_at"] is not None


def _mark_seeded(slug: str, section: str, path: Path | None) -> None:
    with db.connect(path) as conn:
        conn.execute(
            "INSERT INTO section_state (trip_slug, section, seeded_from_md_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(trip_slug, section) DO UPDATE SET "
            "seeded_from_md_at = excluded.seeded_from_md_at",
            (slug, section, _iso_now()),
        )


_DAY_RE = re.compile(r"^##\s+Day\s+(\d+)\b", re.MULTILINE)
_GEAR_CAT_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*$", re.MULTILINE)


def _parse_table(block: str) -> list[list[str]]:
    """Returns rows of cells (excluding header + separator)."""
    rows = []
    seen_header = False
    skipped_sep = False
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not seen_header:
            seen_header = True
            continue
        if not skipped_sep:
            skipped_sep = True
            continue
        rows.append(cells)
    return rows


def _parse_food_md(text: str) -> list[dict]:
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)[1:]
    out: list[dict] = []
    for sec in sections:
        m = re.match(r"Day\s+(\d+)", sec)
        if not m:
            continue
        day = int(m.group(1))
        order = 1.0
        for cells in _parse_table(sec):
            if len(cells) < 2:
                continue
            meal = cells[0].lower().strip()
            meal = MEAL_NORM.get(meal, meal)
            item = cells[1].strip()
            who = cells[2].strip() if len(cells) > 2 else ""
            notes = cells[3].strip() if len(cells) > 3 else ""
            if not item:
                continue
            out.append({
                "day_index": day, "meal": meal, "item": item,
                "assigned_to": who, "notes": notes, "sort_order": order,
            })
            order += 1.0
    return out


def _parse_gear_md(text: str) -> list[dict]:
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)[1:]
    out: list[dict] = []
    for sec in sections:
        lines = sec.splitlines()
        cat = lines[0].strip().lower() if lines else ""
        if not cat:
            continue
        order = 1.0
        for cells in _parse_table(sec):
            if len(cells) < 1:
                continue
            item = cells[0].strip()
            qty = cells[1].strip() if len(cells) > 1 else ""
            who = cells[2].strip() if len(cells) > 2 else ""
            notes = cells[3].strip() if len(cells) > 3 else ""
            if not item:
                continue
            out.append({
                "category": cat, "item": item, "quantity": qty,
                "assigned_to": who, "notes": notes, "sort_order": order,
            })
            order += 1.0
    return out


def seed_trip(
    slug: str,
    trip_dir: Path,
    *,
    owner_email: str,
    path: Path | None = None,
) -> None:
    """Seed food + gear from markdown if not already seeded. Idempotent."""
    user_id = auth.upsert_user(owner_email, path=path)
    auth.add_trip_member(slug, owner_email, role="owner", path=path)

    food_md = trip_dir / "food.md"
    if food_md.exists() and not _is_section_seeded(slug, "food", path):
        for r in _parse_food_md(food_md.read_text()):
            food_repo.insert(trip_slug=slug, user_id=user_id, path=path, **r)
        _mark_seeded(slug, "food", path)

    gear_md = trip_dir / "gear.md"
    if gear_md.exists() and not _is_section_seeded(slug, "gear", path):
        for r in _parse_gear_md(gear_md.read_text()):
            gear_repo.insert(trip_slug=slug, user_id=user_id, path=path, **r)
        _mark_seeded(slug, "gear", path)
