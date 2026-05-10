"""Per-trip gear-plan I/O.

The plan lives as YAML frontmatter in `trips/<slug>/gear.md`. The body below
the frontmatter is regenerated on every save. When a trip's gear.md has no
frontmatter (legacy / fresh trip), `load()` returns an empty plan and exposes
the prose under `legacy_body` so the UI can warn before it overwrites.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.config import TRIPS_DIR

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL,
)


def _trip_dir(slug: str) -> Path:
    d = TRIPS_DIR / slug
    if not d.is_dir():
        raise FileNotFoundError(f"trip not found: {slug}")
    return d


def _read_trip_frontmatter(trip_dir: Path) -> dict:
    text = (trip_dir / "trip.md").read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def load(slug: str) -> dict:
    """Return the gear plan for a trip.

    Shape:
        {
          "items": [{"item_id", "qty", "who", "notes", "override_weight_g"}, ...],
          "participants": [str, ...],
          "legacy_body": str   # populated only when gear.md had no frontmatter
        }
    """
    trip_dir = _trip_dir(slug)
    trip_fm = _read_trip_frontmatter(trip_dir)
    gear_md = trip_dir / "gear.md"
    raw = gear_md.read_text(encoding="utf-8") if gear_md.exists() else ""
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {
            "items": [],
            "participants": list(trip_fm.get("participants") or []),
            "legacy_body": raw.strip(),
        }
    plan_fm = yaml.safe_load(m.group(1)) or {}
    return {
        "items": list(plan_fm.get("items") or []),
        "participants": list(trip_fm.get("participants") or []),
        "legacy_body": "",
    }
