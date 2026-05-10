"""Trip discovery, creation, and editing services.

Pure functions over the filesystem and the build_trip render library.
Routes call into these; tests import them directly.
"""

import datetime
import json
import re
import shutil
from pathlib import Path

import yaml

import build_trip

from app.config import PARKS_JSON, TEMPLATE_DIR, TRIPS_DIR
from app.services import weather_cache as _weather_cache

# Route the trip renderer through the SQLite-cached weather lookup so repeated
# trip loads don't re-hit Open-Meteo.
build_trip.weather_provider = _weather_cache.get_weather


_MD_TABLE_RE = re.compile(
    r"(^\|.+\|[ \t]*\n\|[\s|:\-]+\|[ \t]*\n)((?:^\|.*\|[ \t]*\n)*)",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Markdown table editing (used by the gear save endpoint)
# ---------------------------------------------------------------------------


def _md_escape_cell(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\n", " ")
        .strip()
    )


def replace_first_table(md_text: str, new_rows: list) -> str:
    """Replace the data rows of the first markdown table; preserve the header."""
    match = _MD_TABLE_RE.search(md_text)
    if not match:
        raise ValueError("no markdown table found")
    header_block = match.group(1)
    header_line = header_block.splitlines()[0]
    ncols = len(header_line.strip().strip("|").split("|"))
    rendered = []
    for row in new_rows:
        cells = [_md_escape_cell(c) for c in (row or [])]
        cells = (cells + [""] * ncols)[:ncols]
        rendered.append("| " + " | ".join(cells) + " |")
    new_rows_md = ("\n".join(rendered) + "\n") if rendered else ""
    return md_text[: match.start()] + header_block + new_rows_md + md_text[match.end():]


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
            match = build_trip.FRONTMATTER_RE.match(text)
            if not match:
                trips.append({"name": trip_dir.name, "error": "missing frontmatter"})
                continue
            fm = yaml.safe_load(match.group(1)) or {}
            fm = build_trip._stringify_dates(fm)
            park_info = build_trip._load_park_info(fm.get("park", ""))
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


EDITABLE_SECTIONS = {"intro", "itinerary", "packing", "costs"}

# Sections whose primary content is a single markdown table — eligible for the
# in-place row editor in the trip pane.
TABLE_SECTIONS = {"costs"}


def load_section(
    slug: str,
    section: str,
    trips_dir: Path | None = None,
) -> str:
    """Return the raw markdown of a section (intro = trip.md body)."""
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    if section not in EDITABLE_SECTIONS:
        raise TripError(f"unknown section '{section}'", status=400)
    trip_dir = trips_dir / slug
    if not slug or not trip_dir.is_dir():
        raise TripError("trip not found", status=404)

    if section == "intro":
        trip_md = trip_dir / "trip.md"
        if not trip_md.exists():
            raise TripError("trip.md not found", status=404)
        existing = trip_md.read_text(encoding="utf-8")
        match = build_trip.FRONTMATTER_RE.match(existing)
        if not match:
            raise TripError("trip.md missing frontmatter", status=400)
        return match.group(2).lstrip("\n")

    target = trip_dir / f"{section}.md"
    return target.read_text(encoding="utf-8") if target.exists() else ""


def save_section(
    slug: str,
    section: str,
    markdown: str,
    trips_dir: Path | None = None,
) -> None:
    """Rewrite a single section's markdown.

    `intro` is special: it's the body of trip.md after the YAML frontmatter.
    All other sections map 1:1 to <section>.md. The trip is rendered on demand
    by /api/trip/<slug>, so there is no HTML artifact to refresh.
    """
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    if section not in EDITABLE_SECTIONS:
        raise TripError(f"unknown section '{section}'", status=400)
    trip_dir = trips_dir / slug
    if not slug or not trip_dir.is_dir():
        raise TripError("trip not found", status=404)

    body = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if not body.endswith("\n"):
        body += "\n"

    if section == "intro":
        trip_md = trip_dir / "trip.md"
        if not trip_md.exists():
            raise TripError("trip.md not found", status=404)
        existing = trip_md.read_text(encoding="utf-8")
        match = build_trip.FRONTMATTER_RE.match(existing)
        if not match:
            raise TripError("trip.md missing frontmatter", status=400)
        frontmatter_block = existing[: match.start(2)]
        trip_md.write_text(frontmatter_block + body, encoding="utf-8")
    else:
        target = trip_dir / f"{section}.md"
        target.write_text(body, encoding="utf-8")


def save_section_table(
    slug: str,
    section: str,
    rows: list[list[str]],
    trips_dir: Path | None = None,
) -> None:
    """Replace the first markdown table in <section>.md with `rows`."""
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    if section not in TABLE_SECTIONS:
        raise TripError(
            f"section '{section}' is not table-editable", status=400,
        )
    trip_dir = trips_dir / slug
    if not slug or not trip_dir.is_dir():
        raise TripError("trip not found", status=404)
    md_path = trip_dir / f"{section}.md"
    if not md_path.exists():
        raise TripError(f"{section}.md not found", status=404)
    if not isinstance(rows, list) or any(not isinstance(r, list) for r in rows):
        raise TripError("rows must be a list of lists", status=400)
    text = md_path.read_text(encoding="utf-8")
    try:
        new_text = replace_first_table(text, rows)
    except ValueError as exc:
        raise TripError(str(exc), status=400) from exc
    md_path.write_text(new_text, encoding="utf-8")


def save_gear_table(
    slug: str,
    rows: list[list[str]],
    trips_dir: Path | None = None,
) -> None:
    """Back-compat wrapper for older clients that POST /api/save-gear."""
    save_section_table(slug=slug, section="gear", rows=rows, trips_dir=trips_dir)


# ---------------------------------------------------------------------------
# Costs auto-summary
# ---------------------------------------------------------------------------


def _parse_amount(text: str) -> float | None:
    """Best-effort parse of a cost cell to a float. Strips $, commas, spaces."""
    cleaned = (text or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def costs_summary_html(costs_md: str, participant_count: int) -> str:
    """Compute total + per-person from the costs markdown table.

    Returns an HTML fragment to append after the rendered table. Returns "" if
    the table is empty or absent — the section just shows an unannotated table.
    """
    match = _MD_TABLE_RE.search(costs_md)
    if not match:
        return ""
    header_line = match.group(1).splitlines()[0]
    headers = [h.strip().lower() for h in header_line.strip().strip("|").split("|")]
    amount_idx = next(
        (i for i, h in enumerate(headers) if "amount" in h),
        None,
    )
    if amount_idx is None:
        return ""

    total = 0.0
    counted = 0
    for row_line in match.group(2).strip().splitlines():
        cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
        if amount_idx >= len(cells):
            continue
        amount = _parse_amount(cells[amount_idx])
        if amount is None:
            continue
        total += amount
        counted += 1
    if counted == 0:
        return ""

    if participant_count > 0:
        per_person = total / participant_count
        per_person_label = (
            f'<strong>Per person ({participant_count}):</strong> '
            f'${per_person:,.2f}'
        )
    else:
        per_person_label = (
            '<strong>Per person:</strong> '
            '<em>add participants to compute split</em>'
        )

    return (
        '<p class="costs-summary">'
        f'<strong>Total:</strong> ${total:,.2f} &middot; {per_person_label}'
        '</p>'
    )


# ---------------------------------------------------------------------------
# Trip rendering payload (consumed by /api/trip/<slug>)
# ---------------------------------------------------------------------------


def load_trip_payload(slug: str, trips_dir: Path | None = None) -> dict:
    """Build the SPA payload for a trip: header HTML + per-section rendered HTML.

    Returned shape:
        {
          "slug": str,
          "frontmatter": dict,
          "park_name": str,
          "header_html": str,
          "sections": [
            {"id": str, "title": str, "html": str, "editable": bool},
            ...
          ],
        }
    """
    if trips_dir is None:
        trips_dir = TRIPS_DIR
    trip_dir = trips_dir / slug
    if not slug or not trip_dir.is_dir():
        raise TripError("trip not found", status=404)

    trip = build_trip.load_trip(trip_dir)
    fm = trip["frontmatter"]
    park_info = build_trip._load_park_info(fm.get("park", ""))
    park_name = park_info.get("name") or fm.get("park", "Trip")

    from app.services import foods as foods_svc
    from app.services import gear as gear_svc
    from app.services import gear_plan as gp_svc
    from app.services import meal_plan as mp_svc

    sections: list[dict] = []
    sections.append({
        "id": "intro", "title": "Overview", "editable": True,
        "kind": "html", "payload": None,
        "html": build_trip.render_section(trip["intro"], "intro") if trip["intro"] else "",
    })
    sections.append({
        "id": "itinerary", "title": "Itinerary", "editable": True,
        "kind": "html", "payload": None,
        "html": build_trip.render_section(trip["itinerary"], "itinerary"),
    })

    route_html = build_trip.render_route_section(trip)
    if route_html:
        sections.append({
            "id": "route", "title": "Route", "editable": False,
            "kind": "html", "payload": None,
            "html": route_html,
        })

    weather_html = build_trip.render_weather_section(
        fm.get("park", ""), fm.get("start_date", ""), fm.get("end_date", ""),
    )
    if weather_html:
        sections.append({
            "id": "weather", "title": "Weather", "editable": False,
            "kind": "html", "payload": None,
            "html": weather_html,
        })

    participant_count = len(fm.get("participants", []) or [])
    for section_id in ("gear", "food", "packing", "costs"):
        if section_id == "food":
            try:
                plan = mp_svc.load(slug)
                catalog = foods_svc.load_catalog()
                totals = mp_svc.compute_totals(plan, catalog)
            except Exception:
                plan, totals = {}, {}
            sections.append({
                "id": "food",
                "title": "Food",
                "editable": False,
                "kind": "meal-plan",
                "html": "",
                "payload": {"plan": plan, "totals": totals},
            })
        elif section_id == "gear":
            try:
                plan = gp_svc.load(slug)
                catalog = gear_svc.load_catalog()
                totals = gp_svc.compute_totals(plan, catalog)
            except Exception:
                plan, totals = {}, {}
            sections.append({
                "id": "gear",
                "title": "Shared gear",
                "editable": False,
                "kind": "gear-plan",
                "html": "",
                "payload": {"plan": plan, "totals": totals},
            })
        else:
            section_html = build_trip.render_section(trip[section_id], section_id)
            if section_id == "costs":
                section_html += costs_summary_html(trip["costs"], participant_count)
            sections.append({
                "id": section_id,
                "title": section_id.capitalize(),
                "editable": True,
                "kind": "html",
                "payload": None,
                "html": section_html,
            })

    return {
        "slug": slug,
        "frontmatter": fm,
        "park_name": park_name,
        "header_html": build_trip.render_header(fm),
        "sections": sections,
    }
