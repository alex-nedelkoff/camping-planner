"""Server-rendered HTML pages."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import JINJA_TEMPLATES_DIR
from app.services import trips as trips_svc

router = APIRouter()
templates = Jinja2Templates(directory=str(JINJA_TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    all_trips = trips_svc.scan_trips()
    upcoming, past, broken = trips_svc.split_trips(all_trips)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "upcoming": [trips_svc.trip_card_meta(t) for t in upcoming],
            "past": [trips_svc.trip_card_meta(t) for t in past],
            "broken": broken,
            "park_options": trips_svc.load_park_options(),
        },
    )
