# Car-Camping Trip Page — Maps & Visuals — Design

**Date:** 2026-05-26
**Branch:** local/water-polygon-union
**Status:** Approved

## Problem

The car-camping trip page (`/trip/{slug}` with `mode == "car_camping"`) currently
shows a plain "Getting There & Your Site" section: a drive label, the booked-site
card, and a single "Open official park map" PDF link. It uses the global Killarney
hero photo as its background and carries a canoe-themed "FIELD JOURNAL · EXPEDITION
LOG" stamp in the trip header. For a Balsam Lake car-camping trip we want richer,
park-specific visuals: a real driving route from home, zoomable campground/park
maps, and a Balsam Lake background — built so future drive-in parks get the same
treatment with no code changes.

## Goal

Enhance the car-camping trip experience with:
1. Per-park background photo (data-driven), Balsam gets a user-supplied photo.
2. Remove the "FIELD JOURNAL · EXPEDITION LOG" header stamp from all trips.
3. An OpenStreetMap map showing the real driving route from Ajax to the park.
4. Two zoomable map images (campground + park) featured in the section, plus the
   existing official-PDF link.
All park-specific assets are discovered by a slug-based convention so adding a new
park is drop-in.

## Non-goals

- No offline map tiles — the OSM route map requires internet.
- No turn-by-turn directions list — just the drawn route + distance/time.
- The route map and zoomable maps are car-camping-only; paddle trips keep their
  existing paddle Route section unchanged.
- No server-side routing — routing is client-side via the public OSRM demo.

## Design

### 1. Per-park asset convention (backbone)

Directory convention:
```
app/static/img/parks/<slug>/
    hero.jpg            page background photo
    campground-map.png  zoomable campground map
    park-map.png        zoomable park map
```
New service `app/services/park_assets.py` (pure, filesystem-read, never raises):
- `hero_image(slug) -> str`: returns `/static/img/parks/<slug>/hero.<ext>` if a
  `hero.*` file exists, else the default `/static/img/killarney-hero.jpg`.
- `park_maps(slug) -> list[dict]`: returns `{title, url}` for whichever of
  `campground-map.*` / `park-map.*` exist, titled "Campground map" / "Park map",
  campground first. Empty list when none.

Adding a future park = drop files in `static/img/parks/<slug>/`; no code change.
Balsam's two attached PNGs are copied to `app/static/img/parks/balsam-lake/`
during implementation; the user-supplied scenic photo becomes
`app/static/img/parks/balsam-lake/hero.jpg`.

### 2. Per-park background photo

`trip.css` currently hardcodes `url("/static/img/killarney-hero.jpg")` in the
fixed page-background layer. Change it to `var(--hero-image)`. `trip.html` sets
`--hero-image` via an inline style on the body (or a small `<style>`) from
`park_assets.hero_image(trip.park)`. Killarney trips keep their photo; Balsam gets
its photo; parks with no `hero.*` fall back to the default. Applies to all trips.

### 3. Remove the journal stamp

Delete the `.trip-hero::before { content: "FIELD JOURNAL …" }` rule
(`trip.css` ~lines 92-93). Removes it from every trip header.

### 4. Drive block → real OSM driving route from Ajax

In the car-camping "Drive from home" block, add a Leaflet + OpenStreetMap map that
draws the actual road route from Ajax to the park using Leaflet Routing Machine
(client-side, public OSRM `router.project-osrm.org`), showing routed distance and
drive time. Start = `HOME_COORDS`/`HOME_LABEL` (Ajax, `43.851, -79.020`) added to
`app/config.py`; end = the park's coordinates from `weather.PARK_COORDS`. The
existing "Get directions ↗" link stays. If routing fails, the map still renders
both pins and a straight connecting line (graceful fallback). Leaflet + LRM load
from CDN only on car-camping pages.

### 5. Maps block → two zoomable images + PDF link

Below the booked-site card, a "Maps" block renders each available park map
(`park_assets.park_maps`) as a true zoom/pan viewer. Reusing the already-loaded
Leaflet, each image is an `L.map` with `CRS.Simple` + `L.imageOverlay`; JS reads
the image's natural dimensions on load to set correct bounds/aspect. Each viewer
has a caption. A small "Download official PDF ↗" link uses the existing
`parks.json` `campgroundMapUrl`.

### 6. Coordinates & context

`getting_there.build()` is extended to also return `home_coords` (from config) and
`park_coords` (from `weather.PARK_COORDS`) so the template/JS can build the route
map. `trip_pages.py` passes `hero_image` and `park_maps` into the template context
for the page (hero for all trips; maps only used by the car-camping section).

## Components & files

- **New:** `app/services/park_assets.py` (+ `tests/test_park_assets.py`);
  `app/static/js/car_maps.js` (route map + zoomable viewers);
  `app/static/img/parks/balsam-lake/{campground-map.png, park-map.png, hero.jpg}`.
- **Modify:** `app/static/css/trip.css` (drop stamp; `var(--hero-image)`; maps &
  route layout); `app/templates/trip.html` (set `--hero-image`; load Leaflet + LRM
  + `car_maps.js` for car mode); `app/templates/partials/section_getting_there.html`
  (route-map container in drive block; maps block); `app/routes/trip_pages.py`
  (pass `hero_image`, `park_maps`); `app/services/getting_there.py` (`home_coords`,
  `park_coords`); `app/config.py` (`HOME_COORDS`, `HOME_LABEL`).

## Data flow

```
trip.json (park, mode)
  │
  ▼
trip_pages.py
  • park_assets.hero_image(park)  → --hero-image on <body>   (all trips)
  • if car_camping:
       getting_there.build(park, site) → drive label, directions_url,
           booked_site, map_url(PDF), home_coords, park_coords
       park_assets.park_maps(park)  → [{title,url}, ...]
  ▼
section_getting_there.html
  • gt-drive: label + directions link + #gt-route-map (data-home, data-park)
  • gt-site:  booked-site card (unchanged)
  • gt-maps:  one zoomable viewer per park_map + PDF link
  ▼
car_maps.js
  • initRouteMap(#gt-route-map): Leaflet + LRM(OSRM) Ajax→park; fallback line on error
  • initZoomableMaps(.zoom-map): Leaflet CRS.Simple + imageOverlay per image
```

## Testing

- `park_assets.hero_image`: returns per-park path when `hero.*` present (use a tmp
  static dir / monkeypatched base), else the default.
- `park_assets.park_maps`: returns the maps that exist (campground first), empty
  when none.
- `getting_there.build`: includes `home_coords` (from config) and `park_coords`
  (from PARK_COORDS), still degrades when data missing.
- Route render: a car-camping trip page renders the `#gt-route-map` container with
  home/park data attributes and a `.zoom-map` container per available map plus the
  PDF link; a paddle trip page renders neither and uses the default hero.
- Camis/survey remain mocked; no live API calls. (CSS-only changes — the journal
  stamp removal — are verified visually, not unit-tested.)
