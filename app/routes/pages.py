"""SPA shell entry point — always serves the same shell; routing is client-side."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import JINJA_TEMPLATES_DIR
from app.services import trips as trips_svc

router = APIRouter()
templates = Jinja2Templates(directory=str(JINJA_TEMPLATES_DIR))


def _render_shell(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"park_options": trips_svc.load_park_options()},
    )


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _render_shell(request)


@router.get("/trips/{slug}", response_class=HTMLResponse)
def trip(request: Request, slug: str):  # noqa: ARG001 — slug parsed by SPA
    return _render_shell(request)


@router.get("/new", response_class=HTMLResponse)
def new(request: Request):
    return _render_shell(request)


@router.get("/availability", response_class=HTMLResponse)
def availability_page(request: Request):
    return _render_shell(request)


@router.get("/foods", response_class=HTMLResponse)
def foods_page(request: Request):
    return _render_shell(request)
