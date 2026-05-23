"""Load/save the canonical trip.json file. Source-of-truth gateway."""

from __future__ import annotations

import json
from pathlib import Path

from app.models_trip import SCHEMA_VERSION, Trip


TRIP_JSON_NAME = "trip.json"


class SchemaVersionError(Exception):
    """Raised when trip.json has an unknown or unsupported schema_version."""


def load(trip_dir: Path) -> Trip:
    path = trip_dir / TRIP_JSON_NAME
    if not path.exists():
        raise FileNotFoundError(f"no trip.json in {trip_dir}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"trip.json schema_version={version!r}, expected {SCHEMA_VERSION}"
        )
    return Trip.model_validate(raw)


def save(trip_dir: Path, trip: Trip) -> None:
    path = trip_dir / TRIP_JSON_NAME
    trip_dir.mkdir(parents=True, exist_ok=True)
    payload = trip.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def exists(trip_dir: Path) -> bool:
    return (trip_dir / TRIP_JSON_NAME).exists()
