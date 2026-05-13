#!/usr/bin/env python3
"""Walk TRIPS_DIR and seed every trip's food+gear into the DB."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import TRIPS_DIR  # noqa: E402
from app.services import seed  # noqa: E402


def main() -> None:
    owner = os.environ.get("BOOTSTRAP_OWNER_EMAIL")
    if not owner:
        raise SystemExit("BOOTSTRAP_OWNER_EMAIL env var is required")
    for trip_dir in sorted(TRIPS_DIR.glob("*/")):
        slug = trip_dir.name
        print(f"seeding {slug}…", flush=True)
        seed.seed_trip(slug, trip_dir, owner_email=owner)


if __name__ == "__main__":
    main()
