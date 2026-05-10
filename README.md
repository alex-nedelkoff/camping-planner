# Camping Trip Planner

Plan group camping trips to Ontario Provincial Parks. Collect preferences from friends, check campsite availability, and generate shareable trip pages.

## How It Works

```
1. Survey friends (optional)    →  Google Form collects dates, park preferences, gear
2. Plan the trip                →  Google Sheet template = collaborative source of truth
3. Generate trip page           →  Self-contained HTML with everything you need
4. Share via Google Drive       →  Everyone gets the itinerary + interactive checklists
```

The Google Sheet is where all the planning happens — you and your friends edit it together. When you're ready, generate an HTML trip page from it that works offline at the campsite.

## Quick Start

### Option A: Ask Claude

Just open Claude Code in this project and say:

> "Let's plan a camping trip to Killarney for July 10-12 with Alex, Jordan, Sam, and Riley"

Claude will:
- Create a Google Sheet with all the tabs pre-filled
- Check Ontario Parks for site availability
- Suggest hikes and activities
- Ask you questions to fill in the details
- Generate the HTML trip page and upload it to Drive

### Option B: Do It Yourself

**1. Create a trip planning sheet:**

```bash
python3 trip_planner.py new-trip \
  --park killarney \
  --start 2026-07-10 \
  --end 2026-07-12 \
  --participants "Alex,Jordan,Sam,Riley"
```

This creates a Google Sheet with 8 tabs and gives you the URL. Share it with your group.

**2. Fill in the sheet collaboratively:**

| Tab | What goes here | Who fills it |
|---|---|---|
| Trip Info | Park, dates, meeting point, check-in/out | Trip organizer |
| Participants | Names, who's driving, dietary restrictions, phone numbers | Everyone |
| Route | Multi-day route stops (for canoe/portage trips) | Trip organizer |
| Gear | Shared gear assignments (tent, stove, cooler, etc.) | Everyone claims items |
| Shared Food | Who's bringing what food for which meal | Everyone |
| Itinerary | Day-by-day schedule — departure, activities, meals | Trip organizer |
| Costs | Shared expenses and who paid | Anyone who pays for something |
| Packing Checklist | Personal packing items | Pre-filled, for personal use |

**3. Generate the trip page:**

```bash
python3 trip_planner.py generate --sheet-id YOUR_SHEET_ID --output trip.html
```

Add a canoe/hiking route map:
```bash
python3 trip_planner.py generate --sheet-id YOUR_SHEET_ID --route-file route.gpx --output trip.html
```

**4. Upload to Google Drive:**

```bash
python3 trip_planner.py upload --file trip.html --share
```

Share the link with everyone.

## The HTML Trip Page

The generated HTML file is a single self-contained page with:

- **Trip overview** — park, dates, campsite, group size
- **Who's coming** — participants, dietary restrictions, drivers
- **Getting there** — meeting point, departure time, Google Maps link
- **Weather** — historical averages or real forecast (auto-detected)
- **Route** — multi-site stops for canoe/portage trips
- **Route map** — interactive Leaflet map (online) + SVG diagram (offline)
- **Day-by-day itinerary** — times, activities, meal schedule
- **Activities** — suggested hikes with difficulty/distance, swimming, paddling
- **Gear assignments** — who's bringing what
- **Shared food plan** — meals and dietary notes
- **Cost summary** — expenses with per-person split
- **Packing checklist** — checkboxes saved to your device (localStorage)

**Works offline** — critical for camping with no cell service. Print a copy as backup.

## Checking Campsite Availability

```bash
# Check a specific park
python3 ontario_parks.py check killarney --start 2026-07-10 --end 2026-07-12

# List all configured parks
python3 ontario_parks.py list

# List every park in the Ontario Parks system
python3 ontario_parks.py list-all
```

Or ask Claude: "Check if Killarney has availability for July 10-12"

## Weather

```bash
python3 weather.py --park killarney --start 2026-07-10 --end 2026-07-12
```

- More than 16 days out: shows historical averages (typical conditions)
- Within 16 days: shows real forecast with rain probability
- Automatically included in the HTML trip page

## Survey (Optional)

If you want to poll your friends before planning:

1. See `GOOGLE_FORM_SETUP.md` for form structure, or use `form_builder_import.csv` with the Form Builder add-on, or run `create_form.gs` in Google Apps Script
2. The form collects: available days/weekends, park preferences (filtered by driving willingness), gear, dietary restrictions
3. Responses go to a Google Sheet that Claude can read to pre-fill the trip planning sheet

## File Overview

| File | What it does |
|---|---|
| `trip_planner.py` | Main tool — create sheets, generate HTML, upload to Drive |
| `ontario_parks.py` | Check campsite availability via Ontario Parks API |
| `weather.py` | Fetch weather data (historical + forecast) from Open-Meteo |
| `route_map.py` | Parse KML/GPX files, generate interactive + offline maps |
| `parks.json` | Park database — IDs, names, drive times from Ajax |
| `park_activities.json` | Curated hikes, swimming, paddling for 7 popular parks |
| `CLAUDE.md` | Technical reference for Claude (API details, endpoints, gws usage) |
| `GOOGLE_FORM_SETUP.md` | Instructions for creating the preference survey form |
| `form_builder_import.csv` | CSV template for the Form Builder add-on |
| `create_form.gs` | Google Apps Script to auto-create the form |

## Requirements

- Python 3.9+
- `requests` and `playwright` (`pip install -r requirements.txt`)
- `gws` CLI (Google Workspace CLI — for Sheets/Drive operations)
- Claude Code (for the interactive planning workflow)

## Adding New Parks

Park configs are in `parks.json`. Each park needs a `resourceLocationId` (from the API) and a `mapId` (from browsing the reservation site). To find a park's mapId:

1. Go to `reservations.ontarioparks.com`
2. Navigate to the park's campground map
3. Grab the `mapId` from the URL

To add activities for a park, edit `park_activities.json`.

To add GPS coordinates for weather, edit `weather.py:PARK_COORDS`.
