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
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
PUBLIC_USER_AGENT = "RallyVenueLookup/1.0 (+https://rallyplans.vercel.app)"


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


def venue_attribution(source: str) -> str:
    """Credit the provider that actually supplied the venue. Demo stays labeled."""
    if source == "geoapify":
        return (" Venue data: Geoapify (https://www.geoapify.com/), "
                "© OpenStreetMap contributors (https://www.openstreetmap.org/copyright).")
    if source == "openstreetmap":
        return (" Venue data: © OpenStreetMap contributors "
                "(https://www.openstreetmap.org/copyright).")
    return " Demo venue data."


def discover_public_venues(location: str, *, limit: int = 10, opener=None) -> list[Venue]:
    """Find nearby restaurants from public OpenStreetMap data when Geoapify is unset.

    A venue is returned only when the element itself has a name and street.
    Missing tags are skipped. This does not report hours, a phone, or a booking.
    """
    if not location or not str(location).strip():
        raise ValueError("location is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    opener = opener or urlopen
    latitude, longitude = _geocode_nominatim(location, opener=opener)
    return _search_overpass(latitude, longitude, limit=min(limit, 20), opener=opener)


def _public_json(request: Request, *, opener, timeout: int, failure: str):
    try:
        with opener(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        raise PlacesError(f"{failure} returned HTTP {exc.code}") from None
    except (URLError, OSError, ValueError, UnicodeError):
        raise PlacesError(f"{failure} failed") from None


def _geocode_nominatim(location: str, *, opener) -> tuple[float, float]:
    query = urlencode({"q": location, "format": "jsonv2", "limit": 1})
    request = Request(
        f"{NOMINATIM_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": PUBLIC_USER_AGENT},
    )
    payload = _public_json(request, opener=opener, timeout=10, failure="Public geocoding")
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise PlacesError("Public search found no matching location")
    try:
        lat, lon = float(payload[0]["lat"]), float(payload[0]["lon"])
    except (KeyError, TypeError, ValueError):
        raise PlacesError("Public search returned invalid coordinates") from None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise PlacesError("Public search returned invalid coordinates")
    return lat, lon


def _search_overpass(latitude: float, longitude: float, *, limit: int, opener) -> list[Venue]:
    if not (math.isfinite(latitude) and -90 <= latitude <= 90):
        raise ValueError("latitude must be between -90 and 90")
    if not (math.isfinite(longitude) and -180 <= longitude <= 180):
        raise ValueError("longitude must be between -180 and 180")
    query = (
        f"[out:json][timeout:15];"
        f"(node[\"amenity\"=\"restaurant\"](around:3000,{latitude:.7f},{longitude:.7f});"
        f"way[\"amenity\"=\"restaurant\"](around:3000,{latitude:.7f},{longitude:.7f}););"
        f"out center 40;"
    )
    request = Request(
        OVERPASS_URL,
        data=urlencode({"data": query}).encode(),
        headers={"Accept": "application/json", "User-Agent": PUBLIC_USER_AGENT},
    )
    payload = _public_json(request, opener=opener, timeout=20, failure="Public venue search")
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise PlacesError("Public venue search returned an invalid place collection")

    venues = []
    for element in payload["elements"]:
        venue = _venue_from_osm(element)
        if venue is None:
            continue
        venues.append(venue)
    venues.sort(key=lambda venue: _meters(latitude, longitude, venue.lat, venue.lon))
    return venues[:limit]


def _venue_from_osm(element) -> Venue | None:
    if not isinstance(element, dict):
        return None
    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None
    name = tags.get("name")
    address = _osm_address(tags)
    if not isinstance(name, str) or not name.strip() or not address:
        return None
    point = element.get("center") if isinstance(element.get("center"), dict) else element
    try:
        lat = float(point["lat"])
        lon = float(point["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    kind = element.get("type")
    element_id = element.get("id")
    if kind not in ("node", "way") or isinstance(element_id, bool) or not isinstance(element_id, int):
        return None
    raw_cuisine = tags.get("cuisine")
    cuisine_tags = tuple(
        part.strip()
        for part in raw_cuisine.replace(",", ";").split(";")
        if part.strip()
    ) if isinstance(raw_cuisine, str) else ()
    return Venue(
        f"osm-{kind}-{element_id}",
        name.strip(),
        address,
        lat,
        lon,
        cuisine_tags,
        source="openstreetmap",
    )


def _osm_address(tags: dict) -> str:
    street = tags.get("addr:street")
    if not isinstance(street, str) or not street.strip():
        return ""
    number = tags.get("addr:housenumber")
    line = street.strip()
    if isinstance(number, str) and number.strip():
        line = f"{number.strip()} {line}"
    parts = [line]
    for key in ("addr:city", "addr:state"):
        extra = tags.get(key)
        if isinstance(extra, str) and extra.strip():
            parts.append(extra.strip())
    return ", ".join(parts)


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mean_lat = math.radians((lat1 + lat2) / 2)
    north = math.radians(lat2 - lat1) * 6371000
    east = math.radians(lon2 - lon1) * 6371000 * math.cos(mean_lat)
    return math.hypot(north, east)
