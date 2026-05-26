"""Server-rendered HTML trip detail page."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.services import trip_store, trips as trips_svc
from app.routes.sites import KEY_ATTRS

router = APIRouter()
from app.templating import templates


@router.get("/trip/{slug}", response_class=HTMLResponse)
def trip_page(slug: str, request: Request):
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        trip = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="trip not found")

    siblings = trips_svc.list_trips_v2()
    me = next((s for s in siblings if s["slug"] == slug), None)

    # Weather — best-effort, never 500 the page
    weather_payload = None
    weather_error = None
    try:
        from app.services import weather_cache
        weather_payload = weather_cache.get_weather(
            park_key=trip.park,
            start_date=str(trip.dates.start),
            end_date=str(trip.dates.end),
        )
    except Exception as exc:
        weather_error = str(exc)

    # Location section — branch on trip mode, both best-effort.
    route_render = {"html": "", "distance_km": 0, "empty": True}
    route_error = None
    getting_there = None
    if trip.mode == "car_camping":
        from app.services import getting_there as gt
        booked = trip.nights[0].site if trip.nights else ""
        try:
            getting_there = gt.build(trip.park, booked)
        except Exception as exc:  # never 500 the page
            getting_there = {"park_name": trip.park, "drive_label": None,
                             "directions_url": None, "map_url": None,
                             "booked_site": None, "error": str(exc)}
    else:
        from app.services import route_cache
        routes_path = trip_dir / "manual_routes.json"
        try:
            route_render = route_cache.get_route_render(routes_path, slug)
        except Exception as exc:
            route_error = str(exc)

    return templates.TemplateResponse(
        request,
        "trip.html",
        {
            "trip": trip,
            "slug": slug,
            "nav": {
                "home_href": "/",
                "trip_slug": slug,
                "trip_label": trip.name,
                "trip_dropdown": [{"slug": s["slug"], "name": s["name"]}
                                  for s in siblings],
                "prev_slug": me["prev_slug"] if me else None,
                "next_slug": me["next_slug"] if me else None,
                "show_user_pill": True,
            },
            "weather": weather_payload,
            "weather_error": weather_error,
            "route_render": route_render,
            "route_error": route_error,
            "getting_there": getting_there,
            "key_attrs": KEY_ATTRS,
        },
    )
