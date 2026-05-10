# camping-planner

Shared trip planning for canoe and camping trips with friends. Markdown is the
source of truth; a small Python script generates a self-contained HTML page
per trip.

## Quick start

```bash
git clone git@github.com:alex-nedelkoff/camping-planner.git
cd camping-planner
pip install -r requirements.txt
```

## Editing a trip

1. `cd trips/<trip-name>/`
2. Edit any of `trip.md`, `itinerary.md`, `gear.md`, `food.md`, `packing.md`,
   `costs.md` in your editor.
3. `git pull --rebase && git commit -am "..." && git push`.

GitHub renders `.md` files when you click them on github.com — no build step
needed for the markdown.

## Previewing the HTML

The repo is private, so `htmlpreview.github.io` doesn't work. Run a local
server instead:

```bash
python3 -m http.server
```

Then open `http://localhost:8000/trips/<trip-name>/trip.html`.

## Regenerating the HTML

After editing markdown, regenerate the trip page:

```bash
python3 build_trip.py trips/<trip-name>/
```

Commit both the markdown changes and the regenerated `trip.html`.

## Starting a new trip

```bash
cp -r templates/trip-template trips/<new-trip-name>/
$EDITOR trips/<new-trip-name>/trip.md  # fill in frontmatter
python3 build_trip.py trips/<new-trip-name>/
git add trips/<new-trip-name>/
git commit -m "feat: add <new-trip-name>"
```

## Sensitive content

Anything you don't want committed (phone numbers, emergency contacts,
satellite-messenger PINs) goes in:

- `private/` — gitignored top-level folder
- `*.local.md` — gitignored anywhere

Both you and your collaborator sync these out-of-band.

## Park availability checks

Use the existing tooling against the Ontario Parks API:

```bash
python3 ontario_parks.py check killarney --start 2026-05-15 --end 2026-05-18
```

See `CLAUDE.md` for the full API reference, including rate-limit warnings.

## Repo layout

- `build_trip.py` — markdown → HTML trip page generator
- `ontario_parks.py` — Ontario Parks availability checks
- `weather.py`, `route_map.py` — used by `build_trip.py`
- `parks.json`, `park_activities.json` — park metadata
- `templates/trip-template/` — copy this to start a new trip
- `trips/` — one folder per trip
- `legacy/` — older Sheet-driven flow, kept for reference

## Jeff's Maps vectorizer (optional)

If you have a Jeff's Maps KMZ for Killarney/French River (paid product),
you can extract its lake polygons and campsite locations into a cache
that augments the OSM data.

System dependency — Tesseract OCR binary:

- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr`

Run the extractor (one-shot, only when the map version changes):

```bash
python3 jeffs_extractor.py path/to/jeffs.kmz \
  --bbox 45.92,-81.60,46.12,-81.25 \
  --out jeffs_killarney_cache.json
```

The KMZ itself is gitignored; only the extracted JSON is committed.
