import io
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from app.places import PlacesError, geocode_location, search_places


class PlacesTests(unittest.TestCase):
    def test_geocodes_named_area_for_search(self):
        def opener(request, timeout):
            query = parse_qs(urlparse(request.full_url).query)
            self.assertEqual(query["text"], ["Midtown, New York"])
            return io.BytesIO(b'{"results":[{"lat":40.75,"lon":-73.98}]}')

        self.assertEqual(geocode_location("secret", "Midtown, New York", opener=opener),
                         (40.75, -73.98))

    def test_normalizes_results_and_caps_request(self):
        observed = {}
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "properties": {
                        "place_id": "venue-123",
                        "name": "Pasta House",
                        "formatted": "12 Main St, New York, NY",
                        "lat": 40.75,
                        "lon": -73.98,
                        "categories": [
                            "catering.restaurant",
                            "catering.restaurant.italian",
                            "catering.restaurant.pizza",
                        ],
                    }
                },
                {"properties": {"name": "No stable ID"}},
            ],
        }

        def opener(request, timeout):
            observed["query"] = parse_qs(urlparse(request.full_url).query)
            observed["timeout"] = timeout
            return io.BytesIO(json.dumps(payload).encode())

        venues = search_places("secret", 40.75, -73.98, limit=100, opener=opener)

        self.assertEqual(len(venues), 1)
        venue = venues[0]
        self.assertEqual((venue.id, venue.name, venue.address),
                         ("venue-123", "Pasta House", "12 Main St, New York, NY"))
        self.assertEqual((venue.lat, venue.lon, venue.source), (40.75, -73.98, "geoapify"))
        self.assertEqual(venue.cuisine_tags, ("italian", "pizza"))
        self.assertEqual(observed["query"]["limit"], ["20"])
        self.assertEqual(observed["query"]["filter"], ["circle:-73.98,40.75,3000"])
        self.assertEqual(observed["query"]["bias"], ["proximity:-73.98,40.75"])
        self.assertEqual(observed["timeout"], 10)

    def test_empty_results_are_empty(self):
        def opener(request, timeout):
            return io.BytesIO(b'{"type":"FeatureCollection","features":[]}')

        self.assertEqual(search_places("secret", 40.75, -73.98, opener=opener), [])

    def test_http_error_does_not_look_like_no_results(self):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)

        with self.assertRaisesRegex(PlacesError, "HTTP 429"):
            search_places("secret", 40.75, -73.98, opener=opener)

    def test_invalid_collection_is_an_error(self):
        def opener(request, timeout):
            return io.BytesIO(b'{"message":"invalid API key"}')

        with self.assertRaises(PlacesError):
            search_places("secret", 40.75, -73.98, opener=opener)

    def test_invalid_input_does_not_call_api(self):
        def opener(request, timeout):
            self.fail("API was called")

        with self.assertRaises(ValueError):
            search_places("", 40.75, -73.98, opener=opener)
        with self.assertRaises(ValueError):
            search_places("secret", 100, -73.98, opener=opener)
        with self.assertRaises(ValueError):
            search_places("secret", 40.75, -73.98, limit=0, opener=opener)


if __name__ == "__main__":
    unittest.main()
