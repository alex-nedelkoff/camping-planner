"""Assemble the car-camping 'Getting There & Your Site' section context.

Pure read-only: combines parks.json, weather.PARK_COORDS, and the site survey.
Never raises for missing data — every field degrades to None so the template
can hide blocks individually.
"""
from __future__ import annotations

import weather
from app.services import parks as parks_svc
from app.services import site_surveys


def _directions_url(park_slug: str) -> str | None:
    coords = getattr(weather, "PARK_COORDS", {}).get(park_slug)
    try:
        lat, lon = coords
    except (TypeError, ValueError):
        return None
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"


def build(park_slug: str, booked_site: str) -> dict:
    """Return template context for the getting-there section.

    Keys: park_name, drive_label, directions_url, map_url, booked_site.
    """
    info = parks_svc.load_park_info(park_slug) or {}
    survey = site_surveys.load_survey(park_slug)
    return {
        "park_name": info.get("name") or park_slug,
        "drive_label": info.get("driveFromAjax") or None,
        "directions_url": _directions_url(park_slug),
        "map_url": info.get("campgroundMapUrl") or None,
        "booked_site": site_surveys.find_site(survey, booked_site),
    }
