"""Trip discovery and creation logic.

Routes call into these; tests import them directly.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
from pathlib import Path

import yaml

from app.config import PARKS_JSON, TEMPLATE_DIR, TRIPS_DIR
from app.services import parks as parks_svc


# YAML frontmatter pattern for parsing trip.md
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)


def _stringify_dates(obj):
    """Recursively convert date/datetime values to ISO strings in parsed YAML."""
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Trip discovery
# ---------------------------------------------------------------------------


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def scan_trips(trips_dir: Path | None = None) -> list[dict]:
    """Return a list of trip metadata dicts from <trips_dir>/*/trip.md."""
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    if not trips_dir.exists():
        return []
    trips = []
    for trip_dir in sorted(trips_dir.iterdir()):
        if not trip_dir.is_dir():
            continue
        trip_md = trip_dir / "trip.md"
        if not trip_md.exists():
            continue
        try:
            text = trip_md.read_text(encoding="utf-8")
            match = _FRONTMATTER_RE.match(text)
            if not match:
                trips.append({"name": trip_dir.name, "error": "missing frontmatter"})
                continue
            fm = yaml.safe_load(match.group(1)) or {}
            fm = _stringify_dates(fm)
            park_info = parks_svc.load_park_info(fm.get("park", ""))
            trips.append({
                "name": trip_dir.name,
                "park": fm.get("park", ""),
                "park_name": park_info.get("name") or fm.get("park", "Trip"),
                "start_date": fm.get("start_date", ""),
                "end_date": fm.get("end_date", ""),
                "participants": fm.get("participants", []) or [],
                "has_html": (trip_dir / "trip.html").exists(),
            })
        except Exception as exc:
            trips.append({"name": trip_dir.name, "error": str(exc)})
    return trips


def split_trips(trips: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Sort trips into (upcoming, past, broken) buckets."""
    today = datetime.date.today()
    upcoming, past, broken = [], [], []
    for trip in trips:
        if "error" in trip:
            broken.append(trip)
            continue
        end = _parse_date(trip.get("end_date"))
        if end is None or end >= today:
            upcoming.append(trip)
        else:
            past.append(trip)
    upcoming.sort(key=lambda t: _parse_date(t.get("start_date")) or datetime.date.min)
    past.sort(
        key=lambda t: _parse_date(t.get("start_date")) or datetime.date.min,
        reverse=True,
    )
    return upcoming, past, broken


def trip_card_meta(trip: dict) -> dict:
    """Compute display-only fields for a trip (days_label, participant_count)."""
    if "error" in trip:
        return trip
    enriched = dict(trip)
    enriched["participant_count"] = len(trip.get("participants", []))
    days_label = ""
    start = _parse_date(trip.get("start_date"))
    if start:
        delta = (start - datetime.date.today()).days
        if delta > 0:
            days_label = f"{delta} day{'s' if delta != 1 else ''} away"
        elif delta == 0:
            days_label = "starting today"
        else:
            days_label = f"{abs(delta)} day{'s' if abs(delta) != 1 else ''} ago"
    enriched["days_label"] = days_label
    return enriched


def load_park_options(parks_json: Path | None = None) -> list[tuple[str, str]]:
    """Return [(slug, name), ...] from parks.json, sorted by name."""
    if parks_json is None:
        parks_json = PARKS_JSON
    try:
        data = json.loads(parks_json.read_text(encoding="utf-8"))
    except Exception:
        return []
    parks = data.get("parks", {})
    return sorted(
        ((slug, info.get("name", slug)) for slug, info in parks.items()),
        key=lambda x: x[1],
    )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


class TripError(Exception):
    """Raised by service mutations; carries an HTTP-friendly status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def create_trip(
    park: str,
    start: datetime.date,
    end: datetime.date,
    participants: list[str],
    trips_dir: Path | None = None,
    template_dir: Path | None = None,
) -> str:
    """Create a new trip directory from the template. Returns the slug."""
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    if template_dir is None:
        template_dir = TEMPLATE_DIR
    park = (park or "").strip()
    if not park:
        raise TripError("park is required", status=400)
    slug = f"{park}-{start.strftime('%Y-%m')}"
    target = trips_dir / slug
    if target.exists():
        raise TripError(f"trip directory '{slug}' already exists", status=409)
    if not template_dir.is_dir():
        raise TripError(f"template dir missing: {template_dir}", status=500)

    try:
        shutil.copytree(template_dir, target)
        participants_yaml = (
            "\n".join(f"  - {p}" for p in participants)
            if participants else "  - "
        )
        trip_md = (
            "---\n"
            f"park: {park}\n"
            f"start_date: {start.isoformat()}\n"
            f"end_date: {end.isoformat()}\n"
            f"participants:\n{participants_yaml}\n"
            "---\n\n"
            f"# {slug}\n\n"
            "New trip — fill in details.\n"
        )
        (target / "trip.md").write_text(trip_md, encoding="utf-8")
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise

    return slug


def list_trips_v2() -> list[dict]:
    """List trips via the storage repo. Sorted by start date."""
    from app.services import trip_repo
    repo = trip_repo.get_repo()
    entries = []
    for slug in repo.list_slugs():
        try:
            t = repo.get(slug)
        except Exception:
            continue
        if t is None:
            continue
        park_info = parks_svc.load_park_info(t.park) if t.park else {}
        entries.append({
            "slug": slug, "name": t.name, "park": t.park,
            "park_name": park_info.get("name"),
            "start": t.dates.start, "end": t.dates.end,
            "participant_count": len(t.participants),
        })
    entries.sort(key=lambda e: e["start"])
    for i, e in enumerate(entries):
        e["prev_slug"] = entries[i - 1]["slug"] if i > 0 else None
        e["next_slug"] = entries[i + 1]["slug"] if i < len(entries) - 1 else None
    return entries


def create_trip_v2(park: str, start_date, end_date, participants: list[str], mode: str = "paddle") -> str:
    """Create a new trip via the storage repo. Returns the slug."""
    from datetime import date as _date
    from app.services import trip_repo
    from app.models_trip import Trip, TripDates
    if not park:
        raise ValueError("park required")
    sd = _date.fromisoformat(str(start_date))
    ed = _date.fromisoformat(str(end_date))
    if ed < sd:
        raise ValueError("end date before start")
    slug = f"{park}-{sd.year:04d}-{sd.month:02d}"
    repo = trip_repo.get_repo()
    if repo.exists(slug):
        raise FileExistsError(slug)
    trip = Trip(schema_version=1, name=slug, park=park, mode=mode,
                dates=TripDates(start=sd, end=ed),
                participants=participants or [], access_point="")
    repo.save(slug, trip)
    return slug
