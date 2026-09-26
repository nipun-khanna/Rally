"""Small Geoapify Places adapter for nearby venue discovery.

Place search supplies venue identity and location, never table availability.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PLACES_URL = "https://api.geoapify.com/v2/places"
GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"


class PlacesError(Exception):
    """A Places request failed or returned an unusable response."""


@dataclass(frozen=True)
class Venue:
    id: str
    name: str
    address: str
    lat: float
    lon: float
    cuisine_tags: tuple[str, ...]
    source: str = "geoapify"


def geocode_location(api_key: str, location: str, *, opener=urlopen) -> tuple[float, float]:
    """Resolve a named area to coordinates using Geoapify's free geocoder."""
    if not api_key or not location or not location.strip():
        raise ValueError("Geoapify API key and location are required")
    query = urlencode({"text": location, "format": "json", "limit": 1, "apiKey": api_key})
    request = Request(f"{GEOCODE_URL}?{query}", headers={"Accept": "application/json"})
    try:
        with opener(request, timeout=10) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise PlacesError(f"Geoapify geocoding returned HTTP {exc.code}") from None
    except (URLError, OSError, ValueError, UnicodeError):
        raise PlacesError("Geoapify geocoding failed") from None
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise PlacesError("Geoapify found no matching location")
    try:
        lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        raise PlacesError("Geoapify returned invalid coordinates") from None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise PlacesError("Geoapify returned invalid coordinates")
    return lat, lon


def search_places(
    api_key: str,
    latitude: float,
    longitude: float,
    categories: str = "catering.restaurant",
    limit: int = 10,
    *,
    opener=urlopen,
) -> list[Venue]:
    """Find nearby venues, ordered by Geoapify's proximity bias.

    A 3 km circle keeps results local. The result cap limits API credit use.
    An empty feature collection returns an empty list; transport and malformed
    response failures raise PlacesError so callers can report them honestly.
    """
    if not api_key or not api_key.strip():
        raise ValueError("Geoapify API key is required")
    if not categories or not categories.strip():
        raise ValueError("At least one place category is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if not (math.isfinite(latitude) and -90 <= latitude <= 90):
        raise ValueError("latitude must be between -90 and 90")
    if not (math.isfinite(longitude) and -180 <= longitude <= 180):
        raise ValueError("longitude must be between -180 and 180")

    coordinates = f"{longitude},{latitude}"
    query = urlencode(
        {
            "apiKey": api_key,
            "categories": categories,
            "filter": f"circle:{coordinates},3000",
            "bias": f"proximity:{coordinates}",
            "limit": min(limit, 20),
        }
    )
    request = Request(f"{PLACES_URL}?{query}", headers={"Accept": "application/json"})
    try:
        with opener(request, timeout=10) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise PlacesError(f"Geoapify returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise PlacesError("Geoapify request failed") from exc
    except (ValueError, UnicodeError) as exc:
        raise PlacesError("Geoapify returned invalid JSON") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise PlacesError("Geoapify returned an invalid place collection")

    venues = []
    for feature in payload["features"]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        place_id = properties.get("place_id")
        name = properties.get("name")
        address = properties.get("formatted")
        if not all(isinstance(value, str) and value.strip() for value in (place_id, name, address)):
            continue
        try:
            lat = float(properties["lat"])
            lon = float(properties["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(lat) and math.isfinite(lon)):
            continue
        raw_categories = properties.get("categories", [])
        cuisine_tags = tuple(
            category.removeprefix("catering.restaurant.")
            for category in raw_categories
            if isinstance(category, str) and category.startswith("catering.restaurant.")
        ) if isinstance(raw_categories, list) else ()
        venues.append(Venue(place_id, name, address, lat, lon, cuisine_tags))
    return venues
