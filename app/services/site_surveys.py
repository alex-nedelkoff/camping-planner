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
