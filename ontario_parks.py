"""
Ontario Parks campsite availability checker.

Uses the undocumented Camis/Aspira API powering reservations.ontarioparks.com.
Falls back to Playwright browser automation if the API is blocked.

Availability codes from the API:
  0 = Available
  1 = Available (alternate type)
  2 = Available (walk-in / first-come)
  3 = Reserved (not available)
  5 = Reserved
  6 = Not operating / closed
"""

import json
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Union

import requests

BASE_URL = "https://reservations.ontarioparks.com"
PARKS_FILE = Path(__file__).parent / "parks.json"

AVAILABLE_CODES = {0, 1, 2}

MAP_NAMES_CACHE = Path(__file__).parent / "map_names_cache.json"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}


def load_parks() -> dict:
    with open(PARKS_FILE, encoding="utf-8") as f:
        return json.load(f)["parks"]


def get_map_names() -> dict[str, str]:
    """
    Get a mapping of mapId -> human-readable name.
    Fetches from API and caches locally. Returns cached version on failure.
    """
    # Try cache first
    if MAP_NAMES_CACHE.exists():
        with open(MAP_NAMES_CACHE, encoding="utf-8") as f:
            return json.load(f)

    try:
        resp = requests.get(f"{BASE_URL}/api/maps", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        maps = resp.json()
    except Exception:
        return {}

    names = {}
    for m in maps:
        mid = m.get("mapId")
        if mid is not None:
            # Try to get name from localizedValues
            lv = m.get("localizedValues", [])
            if lv:
                names[str(mid)] = lv[0].get("title", f"Map {mid}")

        # Also extract names from map links (parent -> child relationships)
        for link in m.get("mapLinks", []):
            child_id = link.get("childMapId")
            loc = link.get("localizations", [])
            if child_id is not None and loc:
                title = loc[0].get("title", f"Map {child_id}")
                names[str(child_id)] = title

    # Cache it
    with open(MAP_NAMES_CACHE, "w", encoding="utf-8") as f:
        json.dump(names, f, indent=2, ensure_ascii=False)

    return names


def resolve_map_name(map_id: Union[int, str]) -> str:
    """Look up a human-readable name for a map ID."""
    key = str(map_id)
    # Check parks.json campgroundNames first
    try:
        with open(PARKS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        cg_names = data.get("campgroundNames", {})
        if key in cg_names:
            return cg_names[key]
    except Exception:
        pass
    # Fall back to cached API map names
    names = get_map_names()
    return names.get(key, f"Campground {map_id}")


def get_resource_locations() -> list[dict]:
    """Fetch all parks/resource locations from the API."""
    resp = requests.get(
        f"{BASE_URL}/api/resourceLocation", headers=HEADERS, timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def get_availability(
    map_id: int,
    start_date: str,
    end_date: str,
    party_size: int = 4,
    booking_category_id: int = 0,
) -> dict:
    """
    Check availability for a campground map via GET /api/availability/map.

    Returns the raw API response with resourceAvailabilities and mapLinkAvailabilities.
    """
    params = {
        "mapId": map_id,
        "bookingCategoryId": booking_category_id,
        "startDate": start_date,
        "endDate": end_date,
        "isReserving": True,
        "getDailyAvailability": True,
        "partySize": party_size,
    }
    resp = requests.get(
        f"{BASE_URL}/api/availability/map",
        params=params,
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def count_available_sites(availability_data: dict) -> dict:
    """
    Parse the availability response and count available vs total sites.

    Returns dict with:
      - available_count: number of fully available sites
      - total_count: total sites
      - available_site_ids: list of resource IDs that are available
      - child_maps: dict of child mapId -> aggregated availability code
    """
    resource_avail = availability_data.get("resourceAvailabilities", {})
    map_link_avail = availability_data.get("mapLinkAvailabilities", {})

    available_ids = []
    total = len(resource_avail)

    for resource_id, days in resource_avail.items():
        # A site is "available" if ALL requested days have an available code
        if all(
            day.get("availability") in AVAILABLE_CODES
            for day in days
        ):
            available_ids.append(resource_id)

    return {
        "available_count": len(available_ids),
        "total_count": total,
        "available_site_ids": available_ids,
        "child_maps": {
            mid: codes for mid, codes in map_link_avail.items()
        },
    }


def check_park(
    park_key: str,
    start_date: str,
    end_date: str,
    party_size: int = 4,
    drill_down: bool = True,
) -> dict:
    """
    Check campsite availability for a named park.

    If the park's root map contains child map links (sub-campgrounds),
    drills down into each to get per-campground availability.

    Returns dict with availability summary.
    """
    parks = load_parks()
    if park_key not in parks:
        raise ValueError(
            f"Unknown park '{park_key}'. Available: {', '.join(parks.keys())}"
        )

    park = parks[park_key]
    if park.get("mapId") is None:
        print(f"  {park['name']}: mapId not configured yet.")
        print(f"  Browse reservations.ontarioparks.com to this park and grab the mapId from the URL.")
        return {"park_key": park_key, "park_name": park["name"], "error": "mapId not set", "total_available": 0}

    print(f"Checking {park['name']} ({start_date} to {end_date})...")

    try:
        data = get_availability(
            map_id=park["mapId"],
            start_date=start_date,
            end_date=end_date,
            party_size=party_size,
        )
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print("  API returned 403 — trying Playwright fallback...")
            return check_park_playwright(park, start_date, end_date, party_size)
        raise

    result = count_available_sites(data)
    result["park_key"] = park_key
    result["park_name"] = park["name"]

    # If there are child maps and drill_down is enabled, check each
    if drill_down and result["child_maps"]:
        result["campgrounds"] = {}
        for child_map_id in result["child_maps"]:
            time.sleep(0.5 + random.uniform(0, 0.5))
            try:
                child_data = get_availability(
                    map_id=int(child_map_id),
                    start_date=start_date,
                    end_date=end_date,
                    party_size=party_size,
                )
                child_result = count_available_sites(child_data)
                result["campgrounds"][child_map_id] = child_result
            except Exception as e:
                result["campgrounds"][child_map_id] = {"error": str(e)}

    total_available = result["available_count"]
    if result.get("campgrounds"):
        total_available = sum(
            cg.get("available_count", 0)
            for cg in result["campgrounds"].values()
            if isinstance(cg, dict) and "error" not in cg
        )

    print(f"  {total_available} site(s) available")
    result["total_available"] = total_available
    return result


def check_park_playwright(
    park: dict,
    start_date: str,
    end_date: str,
    party_size: int,
) -> dict:
    """Fallback: use Playwright to scrape availability when API is blocked."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright not installed. Run: pip install playwright && playwright install chromium")
        return {"error": "playwright_not_installed", "total_available": 0}

    resource_location_id = park.get("resourceLocationId", "")
    map_id = park["mapId"]
    booking_category_id = park.get("bookingCategoryId", 0)

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    nights = (end - start).days

    url = (
        f"{BASE_URL}/create-booking/results"
        f"?resourceLocationId={resource_location_id}"
        f"&mapId={map_id}"
        f"&searchTabGroupId=0"
        f"&bookingCategoryId={booking_category_id}"
        f"&startDate={start_date}"
        f"&endDate={end_date}"
        f"&nights={nights}"
        f"&isReserving=true"
        f"&partySize={party_size}"
    )

    available_sites = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Intercept API calls the page makes
        api_responses = []

        def handle_response(response):
            if "/api/availability/" in response.url:
                try:
                    api_responses.append(response.json())
                except Exception:
                    pass

        page.on("response", handle_response)
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)

        # Use intercepted API data if available
        for api_data in api_responses:
            if "resourceAvailabilities" in api_data:
                result = count_available_sites(api_data)
                browser.close()
                result["source"] = "playwright"
                result["total_available"] = result["available_count"]
                print(f"  {result['available_count']} site(s) available (via Playwright)")
                return result

        # Fallback: try to parse DOM
        site_elements = page.query_selector_all(
            "[class*='available'], [data-available='true']"
        )
        for el in site_elements:
            name = el.get_attribute("aria-label") or el.inner_text().strip()
            if name:
                available_sites.append(name[:50])

        browser.close()

    total = len(available_sites)
    print(f"  {total} site(s) available (via Playwright)")
    return {
        "source": "playwright",
        "total_available": total,
        "available_site_names": available_sites,
        "manual_url": url,
    }


def check_multiple_parks(
    park_keys: list[str],
    start_date: str,
    end_date: str,
    party_size: int = 4,
    delay: float = 1.5,
) -> dict[str, dict]:
    """Check availability across multiple parks with rate limiting."""
    results = {}
    for i, park_key in enumerate(park_keys):
        results[park_key] = check_park(park_key, start_date, end_date, party_size)
        if i < len(park_keys) - 1:
            time.sleep(delay + random.uniform(0, 1))
    return results


def print_results(results: dict[str, dict]) -> None:
    """Pretty-print availability results."""
    print("\n" + "=" * 60)
    print("CAMPSITE AVAILABILITY RESULTS")
    print("=" * 60)

    for park_key, info in results.items():
        park_name = info.get("park_name", park_key)
        total = info.get("total_available", 0)
        print(f"\n{park_name}: {total} site(s) available")

        campgrounds = info.get("campgrounds", {})
        if campgrounds:
            for cg_id, cg_info in campgrounds.items():
                cg_name = resolve_map_name(cg_id)
                if "error" in cg_info:
                    print(f"  {cg_name}: error — {cg_info['error']}")
                else:
                    avail = cg_info.get("available_count", 0)
                    tot = cg_info.get("total_count", 0)
                    print(f"  {cg_name}: {avail}/{tot} sites available")

        if info.get("manual_url"):
            print(f"  Check manually: {info['manual_url']}")

    print()


def list_parks() -> None:
    """Print all configured parks."""
    parks = load_parks()
    print("Configured parks:")
    for key, info in parks.items():
        print(f"  {key:30s} {info['name']}")


# --- CLI ---
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Check Ontario Parks campsite availability"
    )
    sub = parser.add_subparsers(dest="command")

    # check command
    check_parser = sub.add_parser("check", help="Check availability")
    check_parser.add_argument(
        "parks", nargs="+",
        help="Park keys (e.g., killarney algonquin-canisbay). Use 'list' to see all.",
    )
    check_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    check_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    check_parser.add_argument("--party-size", type=int, default=4)
    check_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # list command
    sub.add_parser("list", help="List configured parks")

    # list-all command (from API)
    sub.add_parser("list-all", help="List all parks from Ontario Parks API")

    # refresh-maps command
    sub.add_parser("refresh-maps", help="Refresh cached campground map names")

    args = parser.parse_args()

    if args.command == "list":
        list_parks()
    elif args.command == "list-all":
        locations = get_resource_locations()
        for loc in locations:
            name = loc["localizedValues"][0].get("shortName", "?")
            rid = loc["resourceLocationId"]
            print(f"  {rid:15d}  {name}")
    elif args.command == "refresh-maps":
        if MAP_NAMES_CACHE.exists():
            MAP_NAMES_CACHE.unlink()
        names = get_map_names()
        print(f"Cached {len(names)} map names")
    elif args.command == "check":
        results = check_multiple_parks(
            args.parks, args.start, args.end, args.party_size
        )
        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            print_results(results)
    else:
        parser.print_help()
