"""Centralised paths and settings for the FastAPI app."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIPS_DIR = REPO_ROOT / "trips"
TEMPLATE_DIR = REPO_ROOT / "templates" / "trip-template"
PARKS_JSON = REPO_ROOT / "parks.json"
DATABASE_PATH = REPO_ROOT / "camping.sqlite3"

APP_DIR = Path(__file__).resolve().parent
JINJA_TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

# Cache TTLs (seconds)
AVAILABILITY_CACHE_TTL = 15 * 60   # 15 min — Camis WAF risk dominates correctness
WEATHER_CACHE_TTL = 60 * 60        # 1 hour — Open-Meteo forecast cadence
