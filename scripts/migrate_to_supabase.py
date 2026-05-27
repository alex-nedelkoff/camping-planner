"""Push filesystem trips (trips/<slug>/trip.json + manual_routes.json) into Postgres.

Usage: DATABASE_URL=... python3 -m scripts.migrate_to_supabase [trips_dir]
Idempotent (upsert).
"""
from __future__ import annotations

import sys
from pathlib import Path

from app import config
from app.services.trip_repo import FilesystemTripRepo
from app.services.trip_repo_pg import PostgresTripRepo
from app.services import pg


def run(trips_dir: Path) -> int:
    pg.ensure_schema()
    fs = FilesystemTripRepo(Path(trips_dir))
    dst = PostgresTripRepo()
    n = 0
    for slug in fs.list_slugs():
        try:
            trip = fs.get(slug)
        except Exception as exc:
            print(f"  skipped {slug}: {exc}")
            continue
        if trip is None:
            continue
        dst.save(slug, trip)
        routes = fs.get_routes(slug)
        if routes is not None:
            dst.set_routes(slug, routes)
        n += 1
        print(f"  migrated {slug}")
    print(f"done: {n} trips")
    return n


if __name__ == "__main__":
    trips_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.TRIPS_DIR
    run(trips_dir)
