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
    SCHEMA_VERSION, Trip,
)

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[(?P<mark>[ xX])\]\s+(?P<label>.+)$",
                          re.MULTILINE)


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


def _gear_from_md(text: str) -> list:
    """Produce unified TripItem list from a gear.md (shared table + personal sections)."""
    out = []
    for heading, body in _split_sections(text):
        if heading.lower().startswith("shared"):
            for row in _parse_md_table(body):
                row = (row + ["", "", ""])[:3]
                who = (row[1] or "").strip()
                bringers = [who] if who and who.lower() != "tbd" else []
                out.append({"item": row[0], "category": "Shared gear",
                            "notes": row[2], "bringers": bringers, "shared": True})
        elif heading.lower().startswith("personal"):
            person_parts = re.split(r"^### (.+)$", body, flags=re.MULTILINE)
            for i in range(1, len(person_parts), 2):
                person = person_parts[i].strip()
                items_block = person_parts[i + 1] if i + 1 < len(person_parts) else ""
                for ln in items_block.splitlines():
                    m = re.match(r"^\s*[-*+]\s+(.+)$", ln)
                    if m:
                        out.append({"item": m.group(1).strip(), "category": "Personal",
                                    "notes": "", "bringers": [person], "shared": False})
    return out


def _packing_to_gear_items(text: str) -> list:
    """Merge packing.md categories into the unified gear list."""
    SHARED_CATS = {"shelter & sleep", "kitchen", "paddling"}
    out = []
    for heading, body in _split_sections(text):
        is_shared = heading.lower() in SHARED_CATS
        for m in CHECKBOX_RE.finditer(body):
            out.append({
                "item": m.group("label").strip(),
                "category": heading,
                "notes": "",
                "bringers": [],
                "shared": is_shared,
            })
    return out


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


# (packing parser merged into _packing_to_gear_items above)


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
        "gear": _gear_from_md(_read("gear.md")) + _packing_to_gear_items(_read("packing.md")),
        "food": _food_from_md(_read("food.md")),
        "costs": _costs_from_md(_read("costs.md")),
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
