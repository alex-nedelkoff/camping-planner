"""
Weather data for camping trips via Open-Meteo API (free, no API key).

Provides:
- Historical climate averages for any dates/location
- Real forecast when within 16 days of the trip
"""

import json
from datetime import datetime, timedelta

import requests

# WMO weather codes → descriptions and emoji
WMO_CODES = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫"),
    48: ("Rime fog", "🌫"),
    51: ("Light drizzle", "🌦"),
    53: ("Moderate drizzle", "🌦"),
    55: ("Dense drizzle", "🌧"),
    61: ("Slight rain", "🌦"),
    63: ("Moderate rain", "🌧"),
    65: ("Heavy rain", "🌧"),
    71: ("Slight snow", "🌨"),
    73: ("Moderate snow", "🌨"),
    75: ("Heavy snow", "❄️"),
    80: ("Slight showers", "🌦"),
    81: ("Moderate showers", "🌧"),
    82: ("Violent showers", "⛈"),
    95: ("Thunderstorm", "⛈"),
    96: ("Thunderstorm + hail", "⛈"),
    99: ("Thunderstorm + heavy hail", "⛈"),
}

# GPS coordinates for parks (approximate)
PARK_COORDS = {
    "killarney": (46.01, -81.40),
    "algonquin-canisbay": (45.55, -78.73),
    "algonquin-pog": (45.53, -78.75),
    "algonquin-rock-lake": (45.49, -78.62),
    "algonquin-mew-lake": (45.55, -78.65),
    "algonquin-two-rivers": (45.55, -78.69),
    "algonquin-backcountry": (45.55, -78.73),
    "bon-echo": (44.89, -77.19),
    "sandbanks": (43.90, -77.24),
    "killbear": (45.35, -80.21),
    "arrowhead": (45.39, -79.24),
    "grundy-lake": (45.52, -80.60),
    "pinery": (43.26, -81.84),
    "frontenac": (44.50, -76.55),
    "silent-lake": (44.86, -78.07),
    "kawartha-highlands": (44.75, -78.10),
    "presquile": (43.99, -77.72),
    "awenda": (44.85, -79.96),
    "sibbald-point": (44.34, -79.34),
    "balsam-lake": (44.58, -78.85),
    "long-point": (42.58, -80.40),
    "rondeau": (42.27, -81.86),
    "french-river": (46.04, -80.44),
    "macgregor-point": (44.38, -81.44),
    "massasauga": (45.21, -80.07),
    "pancake-bay": (47.00, -84.65),
    "lake-superior": (47.75, -85.89),
    "sleeping-giant": (48.40, -88.80),
    "wasaga-beach": (44.52, -80.01),
    "darlington": (43.87, -78.80),
}


def get_coords(park_key: str = None, lat: float = None, lon: float = None):
    """Get coordinates for a park or use provided lat/lon."""
    if lat is not None and lon is not None:
        return (lat, lon)
    if park_key and park_key in PARK_COORDS:
        return PARK_COORDS[park_key]
    return None


def get_forecast(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """
    Get weather forecast (only works within ~16 days).
    Returns None if dates are too far out.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    now = datetime.now()
    if (start - now).days > 16:
        return None

    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weathercode",
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "America/Toronto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_historical_climate(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """
    Get historical climate averages for the given dates.
    Uses EC-Earth3P-HR climate model.
    """
    resp = requests.get(
        "https://climate-api.open-meteo.com/v1/climate",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "start_date": start_date,
            "end_date": end_date,
            "models": "EC_Earth3P_HR",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_weather(park_key: str = None, lat: float = None, lon: float = None,
                start_date: str = "", end_date: str = "") -> dict:
    """
    Get weather data for a trip. Tries forecast first, falls back to historical.

    Returns dict with:
      - source: "forecast" or "historical"
      - days: list of {date, high, low, precip, precip_chance, code, description, icon}
    """
    coords = get_coords(park_key, lat, lon)
    if not coords:
        return {"source": "unavailable", "days": []}

    lat, lon = coords
    days = []

    # Try forecast first
    forecast = None
    try:
        forecast = get_forecast(lat, lon, start_date, end_date)
    except Exception:
        pass

    if forecast and forecast.get("daily"):
        daily = forecast["daily"]
        for i, date in enumerate(daily["time"]):
            code = daily.get("weathercode", [None])[i]
            desc, icon = WMO_CODES.get(code, ("Unknown", "❓"))
            days.append({
                "date": date,
                "high": round(daily["temperature_2m_max"][i], 1),
                "low": round(daily["temperature_2m_min"][i], 1),
                "precip_mm": round(daily["precipitation_sum"][i], 1),
                "precip_chance": daily.get("precipitation_probability_max", [None])[i],
                "code": code,
                "description": desc,
                "icon": icon,
            })
        return {"source": "forecast", "days": days}

    # Fall back to historical climate
    try:
        climate = get_historical_climate(lat, lon, start_date, end_date)
    except Exception:
        return {"source": "unavailable", "days": []}

    if climate and climate.get("daily"):
        daily = climate["daily"]
        for i, date in enumerate(daily["time"]):
            days.append({
                "date": date,
                "high": round(daily["temperature_2m_max"][i], 1),
                "low": round(daily["temperature_2m_min"][i], 1),
                "precip_mm": round(daily["precipitation_sum"][i], 1),
                "precip_chance": None,
                "code": None,
                "description": "Historical average",
                "icon": "",
            })
        return {"source": "historical", "days": days}

    return {"source": "unavailable", "days": []}


def format_weather_summary(weather: dict) -> str:
    """Format weather data as a readable summary."""
    if not weather.get("days"):
        return "Weather data unavailable."

    source = weather["source"]
    lines = []
    if source == "forecast":
        lines.append("Forecast:")
    else:
        lines.append("Historical averages (typical conditions):")

    for day in weather["days"]:
        date_str = day["date"]
        high = day["high"]
        low = day["low"]
        precip = day["precip_mm"]
        icon = day.get("icon", "")
        desc = day.get("description", "")
        chance = day.get("precip_chance")

        line = f"  {date_str}: {icon} {desc}, {high}°C / {low}°C"
        if chance is not None:
            line += f", {chance}% chance of rain"
        elif precip > 0:
            line += f", ~{precip}mm precip"
        lines.append(line)

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Get weather for a camping trip")
    parser.add_argument("--park", help="Park key from parks.json")
    parser.add_argument("--lat", type=float, help="Latitude")
    parser.add_argument("--lon", type=float, help="Longitude")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    weather = get_weather(args.park, args.lat, args.lon, args.start, args.end)

    if args.json:
        print(json.dumps(weather, indent=2))
    else:
        print(format_weather_summary(weather))
