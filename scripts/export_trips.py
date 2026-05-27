"""Dump Postgres trips back to filesystem JSON (backup / hydrate dev).

Usage: DATABASE_URL=... python3 -m scripts.export_trips [out_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

from app import config
from app.services.trip_repo import FilesystemTripRepo
from app.services.trip_repo_pg import PostgresTripRepo


def run(out_dir: Path) -> int:
    src = PostgresTripRepo()
    fs = FilesystemTripRepo(Path(out_dir))
    n = 0
    for slug in src.list_slugs():
        try:
            trip = src.get(slug)
        except Exception as exc:
            print(f"  skipped {slug}: {exc}")
            continue
        if trip is None:
            continue
        fs.save(slug, trip)
        routes = src.get_routes(slug)
        if routes is not None:
            fs.set_routes(slug, routes)
        n += 1
        print(f"  exported {slug}")
    print(f"done: {n} trips")
    return n


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.TRIPS_DIR
    run(out_dir)
