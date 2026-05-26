# Car-Camping Trip Mode — Design

**Date:** 2026-05-25
**Branch:** local/water-polygon-union
**Status:** Approved

## Problem

The trip page (`/trip/{slug}`) is built around a canoe-tripping model. Its
**Route** section auto-routes paddle + portage legs on Killarney lake data and
lets the user draw a route in an overlay. For a car-camping trip (e.g. a
one-night overnight at Balsam Lake) there is no paddle route — you drive in and
park at a booked site. We want car camping to be a first-class trip type so the
page adapts per trip, reusable for future drive-in parks.

The Campsite Search feature already imported 532 Balsam Lake site surveys
(photos + attributes), which is exactly the "where am I staying" data a
car-camping trip page wants.

## Goal

Add a first-class `car_camping` trip mode. The `/trip/{slug}` page adapts its
location section per trip mode; everything else (Weather, Itinerary, Gear &
Packing, Food, Costs) is shared between modes. Backward-compatible: existing
canoe trips are unaffected.

## Non-goals

- **Site-pinned campground map** — deferred. Neither the survey nor the raw
  Camis resources carry per-site coordinates (sites only have a `mapIds` link).
  A pinned map would need another rate-limited Camis `/api/maps` pull plus
  map-image rendering. Out of scope until we have real coordinate data.
- **Changes to the paddle rendering path** — the existing Route/overlay/
  route_engine flow is untouched.
- **Trip-planning integration of survey data beyond read-only reference** — the
  booked-site card is browse-only, consistent with how Campsite Search was
  scoped.

## Design

### 1. Trip mode (core mechanic)

Add one field to the `Trip` model (`app/models_trip.py`):

```python
mode: Literal["paddle", "car_camping"] = "paddle"
```

- Default `"paddle"` → all existing trips load and render exactly as today.
  No migration needed (Pydantic supplies the default for trip.json files that
  predate the field).
- `trip.json` is the source of truth (the page loads via `trip_store.load`).
- `app/routes/trip_pages.py` branches on `trip.mode` to decide which location
  section context to build and which partial to render.

### 2. Canoe **Route** → car-camping **"Getting There & Your Site"**

A new partial `app/templates/partials/section_getting_there.html` renders in
place of `section_route.html` when `mode == "car_camping"`. Three blocks, all
from existing data:

- **Drive from home** — `driveFromAjax` from `parks.json` (Balsam = "1.25 hrs")
  plus a "Get directions" link to Google Maps built from the park GPS in
  `weather.py:PARK_COORDS`.
- **Your booked site** — a card built by matching `Night.site` (the reserved
  site number) against the park survey via `site_surveys.load_survey(<park>)`.
  Shows photos (reusing the existing lightbox), privacy, dimensions, shade,
  ground cover, equipment type, amenities, and a "See full details →" link to
  `/sites/<park>#<site>`. Degrades gracefully when `Night.site` is blank or the
  site isn't found ("No site selected yet — browse Campsite Search").
- **Campground map** — embed/link to the official Ontario Parks campground map
  via a new optional `campgroundMapUrl` field per park in `parks.json`. Sourced
  for Balsam during implementation. Block hidden when absent.

### 3. Component reuse

Factor the site-card markup into a shared partial
`app/templates/partials/site_card.html`, used by both the `/sites/{slug}` grid
and the trip page. The trip page includes the relevant slice of `sites.css`
plus the `window.siteLightbox` helper from `site_search.js`.

Site-matching logic lives in `site_surveys.py` as `find_site(survey, name)`:
normalizes `"Site 123"` / `"123"` / case + whitespace variants to a survey
entry; returns `None` cleanly when absent. Unit-tested.

### 4. Sidenav + section ordering

`trip_sidenav.html` and `trip.html` switch the first nav item / section between
**"Route"** (paddle) and **"Getting There"** (car_camping) by mode. Weather /
Itinerary / Gear & Packing / Food / Costs unchanged for both modes.

### 5. New-trip form (first-class)

Add a mode selector (Paddle trip / Car camping) to the "+ New Trip" form,
written into `trip.json` via `create_trip_v2`. Default Paddle.

### 6. Create the Balsam trip

As the final step, create the Balsam Lake car_camping trip with the booked site
number so it is usable immediately.

## Data flow

```
trip.json (mode, nights[].site, park)
   │
   ▼
trip_pages.py ── mode == "paddle" ──► route_cache.get_route_render ──► section_route.html
   │
   └──────────── mode == "car_camping" ──► build getting-there context:
                     • parks.json  → driveFromAjax, campgroundMapUrl
                     • weather.PARK_COORDS → directions link
                     • site_surveys.load_survey(park) + find_site(Night.site)
                                          ──► section_getting_there.html
                                                  └── partials/site_card.html
```

## Testing

- `mode` defaults to `"paddle"`; existing trips still render the Route section
  (regression).
- A `car_camping` trip renders "Getting There" (drive + site card + map link),
  not the paddle map.
- `find_site` matches `"123"`, `"Site 123"`, and case/whitespace variants;
  returns `None` when absent.
- Booked-site block degrades when `Night.site` is blank or unmatched.
- Survey / Camis API remain mocked — no live calls from the suite.
