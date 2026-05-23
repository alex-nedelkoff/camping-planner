"""Park metadata lookup. Reads parks.json."""

import json
from pathlib import Path

from app.config import PARKS_JSON


def load_park_info(park_slug: str) -> dict:
    """Look up park name + drive time from parks.json. Returns {} if not found."""
    if not park_slug or not PARKS_JSON.exists():
        return {}
    data = json.loads(PARKS_JSON.read_text(encoding="utf-8"))
    return data.get("parks", {}).get(park_slug, {})
