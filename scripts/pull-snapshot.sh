#!/usr/bin/env bash
# Pull a trip's snapshot files from the Fly machine back to the local repo.
# Usage: scripts/pull-snapshot.sh <slug>
set -euo pipefail

slug="${1:?usage: pull-snapshot.sh <slug>}"
app="${FLY_APP:-camping-planner}"

echo "Pulling /data/trips/${slug}/ from app=${app}…"
fly ssh sftp get -a "${app}" "/data/trips/${slug}/food.md" "trips/${slug}/food.md"
fly ssh sftp get -a "${app}" "/data/trips/${slug}/gear.md" "trips/${slug}/gear.md"
fly ssh sftp get -a "${app}" "/data/trips/${slug}/trip.html" "trips/${slug}/trip.html"
echo "Done. Review with: git diff trips/${slug}/"
