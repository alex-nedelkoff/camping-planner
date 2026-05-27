"""Cached weather lookup. Wraps weather.get_weather, key=(park, start, end)."""

import weather

from app.config import WEATHER_CACHE_TTL
from app.services import cache


CACHE_TABLE = "weather_cache"


def get_weather(park_key: str, start_date: str, end_date: str) -> dict:
    key = (park_key or "", start_date, end_date)
    cached = cache.get(CACHE_TABLE, key, WEATHER_CACHE_TTL)
    if cached is not None:
        return cached
    payload = weather.get_weather(
        park_key=park_key, start_date=start_date, end_date=end_date,
    )
    cache.set(CACHE_TABLE, key, payload)
    return payload
