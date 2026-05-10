"""FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, TRIPS_DIR
from app.routes import checklist, identity, pages, parks, trips
from app.services import db

app = FastAPI(title="Camping Planner")

db.init_schema()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
TRIPS_DIR.mkdir(exist_ok=True)
app.mount("/trips", StaticFiles(directory=str(TRIPS_DIR)), name="trips")

app.include_router(pages.router)
app.include_router(trips.router)
app.include_router(parks.router)
app.include_router(checklist.router)
app.include_router(identity.router)


@app.exception_handler(Exception)
async def _unhandled_exception(_request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": str(exc)},
    )
