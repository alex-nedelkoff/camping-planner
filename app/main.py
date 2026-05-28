"""FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import STATIC_DIR, TRIPS_DIR
from app.routes import auth, checklist, feedback, pages, parks, sites, trip_pages, trips
from app import config

app = FastAPI(title="Camping Planner")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def init_storage() -> None:
    if config.STORAGE_BACKEND == "postgres":
        from app.services import pg
        pg.ensure_schema()  # raises RuntimeError if DATABASE_URL missing
    else:
        from app.services import db
        db.init_schema()


init_storage()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# Ensure the trips dir exists for the /trips static mount below (it is the
# trip-content source only in filesystem mode; in postgres mode it is an empty
# mount point — but StaticFiles still needs the directory to exist).
TRIPS_DIR.mkdir(exist_ok=True)
app.mount("/trips", StaticFiles(directory=str(TRIPS_DIR)), name="trips")

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(trip_pages.router)
app.include_router(trips.router)
app.include_router(parks.router)
app.include_router(sites.router)
app.include_router(checklist.router)
app.include_router(feedback.router)


@app.exception_handler(StarletteHTTPException)
async def _auth_redirect(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401 and not request.url.path.startswith("/api/") and request.method == "GET":
        return RedirectResponse("/login", status_code=303)
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def _unhandled_exception(_request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": str(exc)},
    )
