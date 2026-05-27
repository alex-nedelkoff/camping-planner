"""Slug-addressed trip repository. Source-of-truth gateway for trip content.

Two backends, selected by config.STORAGE_BACKEND:
- FilesystemTripRepo: trips/<slug>/trip.json (+ manual_routes.json). Default.
- PostgresTripRepo:  a `trips` table (added in a later task).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app import config
from app.models_trip import SCHEMA_VERSION, Trip

TRIP_JSON_NAME = "trip.json"
ROUTES_NAME = "manual_routes.json"


class SchemaVersionError(Exception):
    """Raised when stored trip data has an unsupported schema_version."""


def _validate(raw: dict) -> Trip:
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"trip schema_version={version!r}, expected {SCHEMA_VERSION}"
        )
    return Trip.model_validate(raw)


class FilesystemTripRepo:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)

    def _dir(self, slug: str) -> Path:
        return self.base / slug

    def get(self, slug: str) -> Optional[Trip]:
        p = self._dir(slug) / TRIP_JSON_NAME
        if not p.exists():
            return None
        return _validate(json.loads(p.read_text(encoding="utf-8")))

    def save(self, slug: str, trip: Trip) -> None:
        d = self._dir(slug)
        d.mkdir(parents=True, exist_ok=True)
        (d / TRIP_JSON_NAME).write_text(
            json.dumps(trip.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )

    def exists(self, slug: str) -> bool:
        return (self._dir(slug) / TRIP_JSON_NAME).exists()

    def list_slugs(self) -> list[str]:
        if not self.base.exists():
            return []
        return sorted(
            sub.name for sub in self.base.iterdir()
            if sub.is_dir() and (sub / TRIP_JSON_NAME).exists()
        )

    def delete(self, slug: str) -> None:
        import shutil
        d = self._dir(slug)
        if d.exists():
            shutil.rmtree(d)

    def get_routes(self, slug: str) -> Any:
        p = self._dir(slug) / ROUTES_NAME
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def set_routes(self, slug: str, data: Any) -> None:
        d = self._dir(slug)
        d.mkdir(parents=True, exist_ok=True)
        (d / ROUTES_NAME).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_repo():
    """Return the configured repo. Reads config live (test-friendly)."""
    if config.STORAGE_BACKEND == "postgres":
        from app.services.trip_repo_pg import PostgresTripRepo
        return PostgresTripRepo()
    return FilesystemTripRepo(config.TRIPS_DIR)
