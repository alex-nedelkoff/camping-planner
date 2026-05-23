"""Server-rendered HTML trip detail page."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import markdown as _md

from app.config import JINJA_TEMPLATES_DIR
from app.services import trip_store, trips as trips_svc

router = APIRouter()
templates = Jinja2Templates(directory=str(JINJA_TEMPLATES_DIR))


def _md_filter(text: str) -> str:
    return _md.markdown(text or "", extensions=["extra", "sane_lists"])


templates.env.filters["md"] = _md_filter


@router.get("/trip/{slug}", response_class=HTMLResponse)
def trip_page(slug: str, request: Request):
    trip_dir = trips_svc.TRIPS_DIR / slug
    try:
        trip = trip_store.load(trip_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="trip not found")
    siblings = trips_svc.list_trips_v2()
    me = next((s for s in siblings if s["slug"] == slug), None)
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
                "trip_dropdown": [{"slug": s["slug"], "name": s["name"]} for s in siblings],
                "prev_slug": me["prev_slug"] if me else None,
                "next_slug": me["next_slug"] if me else None,
                "show_user_pill": True,
            },
        },
    )
