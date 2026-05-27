"""Centralised paths and settings for the FastAPI app."""

from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIPS_DIR = REPO_ROOT / "trips"
TEMPLATE_DIR = REPO_ROOT / "templates" / "trip-template"
PARKS_JSON = REPO_ROOT / "parks.json"
DATABASE_PATH = REPO_ROOT / "camping.sqlite3"

APP_DIR = Path(__file__).resolve().parent
JINJA_TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
SITE_SURVEYS_DIR = APP_DIR / "data" / "site_surveys"

# Cache TTLs (seconds)
AVAILABILITY_CACHE_TTL = 15 * 60   # 15 min — Camis WAF risk dominates correctness
WEATHER_CACHE_TTL = 60 * 60        # 1 hour — Open-Meteo forecast cadence

# Drive origin for car-camping route maps (Ajax, ON).
HOME_COORDS = (43.851, -79.020)
HOME_LABEL = "Ajax"

# Storage backend: "filesystem" (default, local/dev/tests) or "postgres".
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "filesystem")
# Postgres connection string (Supabase pooled URL or a local Postgres).
DATABASE_URL = os.environ.get("DATABASE_URL") or None

# --- Auth (Phase 2) ---
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
SUPABASE_URL = os.environ.get("SUPABASE_URL") or None
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or None
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET") or None
