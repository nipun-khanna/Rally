import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from app.agent import AgentDecision
from app.config import Settings, build_service
from app.models import ChatMessage, PlanFacts
from app.orchestrator import RallyService
from app.places import PlacesError, Venue, geocode_location, search_places
from app.store import Store


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


_MIDTOWN = {"lat": "40.7551169", "lon": "-73.9847800", "display_name": "Midtown, Manhattan"}
_OVERPASS = {
    "elements": [
        {
            "type": "node",
            "id": 101,
            "lat": 40.7463679,
            "lon": -73.9833563,
            "tags": {"name": "Moono", "amenity": "restaurant", "cuisine": "korean"},
        },
        {
            "type": "node",
            "id": 202,
            "lat": 40.7473845,
            "lon": -73.9771526,
            "tags": {
                "name": "Little Alley",
                "amenity": "restaurant",
                "addr:housenumber": "550",
                "addr:street": "3rd Avenue",
                "addr:city": "New York",
                "cuisine": "chinese;shanghai",
            },
        },
        {
            "type": "node",
            "id": 303,
            "lat": 40.756994,
            "lon": -73.9865512,
            "tags": {
                "name": "Hard Rock Cafe",
                "amenity": "restaurant",
                "addr:housenumber": "1501",
                "addr:street": "Broadway",
                "addr:city": "New York",
                "cuisine": "american",
            },
        },
        {"type": "node", "id": 404, "lat": 40.75, "lon": -73.98, "tags": {"amenity": "restaurant"}},
    ]
}


def _public_opener(calls):
    def opener(request, timeout):
        url = request.full_url
        calls.append((url, timeout, request.get_header("User-agent")))
        host = urlparse(url).hostname or ""
        if host == "nominatim.openstreetmap.org":
            return io.BytesIO(json.dumps([_MIDTOWN]).encode())
        if host == "overpass-api.de":
            return io.BytesIO(json.dumps(_OVERPASS).encode())
        raise AssertionError(url)

    return opener


class _ProposeAgent:
    def __init__(self, facts):
        self.facts = facts

    def extract(self, messages, previous):
        return self.facts

    def decide(self, facts, messages, previous_results=None):
        venue_id = None
        if previous_results:
            venue_id = previous_results[0]["venues"][0]["id"]
        return AgentDecision(action="PROPOSE", reason="venue missing", tool="search_places",
                             confidence=0.9, venue_id=venue_id)


class PublicVenueSearchTests(unittest.TestCase):
    def test_missing_geoapify_key_search_returns_addressed_public_venues(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp, patch("app.places.urlopen", _public_opener(calls)):
            settings = Settings.from_env({
                "RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                "RALLY_DEMO_MODE": "0",
                "RALLY_DEMO_VENUES": "0",
            })
            service = build_service(settings)
            facts = PlanFacts(activity="dinner", location="Midtown, New York")
            venues = service.search_fn(facts)
            reply = service._recommend_restaurant(facts, [], "")

        self.assertEqual([venue.name for venue in venues], ["Hard Rock Cafe", "Little Alley"])
        self.assertEqual(venues[0].address, "1501 Broadway, New York")
        self.assertEqual(venues[0].source, "openstreetmap")
        self.assertEqual(venues[0].cuisine_tags, ("american",))
        self.assertEqual(venues[1].address, "550 3rd Avenue, New York")
        self.assertEqual(venues[1].cuisine_tags, ("chinese", "shanghai"))
        self.assertNotIn("Moono", reply)
        self.assertIn("Hard Rock Cafe", reply)
        self.assertNotIn("An Italian Table", reply)
        self.assertIn("not a booking", reply)
        hosts = [urlparse(url).hostname for url, _timeout, _agent in calls]
        self.assertEqual(hosts, [
            "nominatim.openstreetmap.org", "overpass-api.de",
            "nominatim.openstreetmap.org", "overpass-api.de",
        ])
        self.assertTrue(all(agent and "RallyVenueLookup" in agent for _url, _timeout, agent in calls))
        self.assertTrue(all("geoapify.com" not in url for url, _timeout, _agent in calls))

    def test_public_search_skips_network_when_location_or_budget_blocks_it(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp, patch("app.places.urlopen", _public_opener(calls)):
            missing = build_service(Settings.from_env({
                "RALLY_DATABASE_PATH": str(Path(tmp) / "missing.sqlite3"),
            }))
            with self.assertRaisesRegex(PlacesError, "Plan location is missing"):
                missing.search_fn(PlanFacts(activity="dinner"))
            unclear = build_service(Settings.from_env({
                "RALLY_DATABASE_PATH": str(Path(tmp) / "unclear.sqlite3"),
            }))
            with self.assertRaisesRegex(PlacesError, "The city is unclear"):
                unclear.search_fn(PlanFacts(location="Midtown"))
            capped = build_service(Settings.from_env({
                "RALLY_DATABASE_PATH": str(Path(tmp) / "capped.sqlite3"),
                "RALLY_MAX_PLACE_REQUESTS": "1",
            }))
            with self.assertRaisesRegex(PlacesError, "Free place-search budget reached"):
                capped.search_fn(PlanFacts(location="Midtown, New York"))
        self.assertEqual(calls, [])

    def test_public_http_error_is_not_an_empty_or_demo_result(self):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)

        with tempfile.TemporaryDirectory() as tmp, patch("app.places.urlopen", opener):
            service = build_service(Settings.from_env({
                "RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
            }))
            with self.assertRaisesRegex(PlacesError, "HTTP 429"):
                service.search_fn(PlanFacts(location="Midtown, New York"))

    def test_proposal_credits_openstreetmap_and_does_not_call_it_a_demo_venue(self):
        calls = []
        now = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)
        facts = PlanFacts(goal="Friday dinner", activity="dinner",
                          participants=["nick", "sarah"], date="2026-10-02",
                          earliest_time="19:00", location="Midtown, New York",
                          excluded_cuisines=["sushi"], blockers=["venue missing"],
                          confidence=0.9)
        sent = []
        with tempfile.TemporaryDirectory() as tmp, patch("app.places.urlopen", _public_opener(calls)):
            wired = build_service(Settings.from_env({
                "RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
            }))
            wired.store.save_plan("chat1", facts, now - timedelta(minutes=31))
            planner = RallyService(wired.store, _ProposeAgent(facts), wired.search_fn,
                                   lambda chat_id, text: sent.append(text), stall_minutes=30)
            planner.tick(now)
        self.assertTrue(sent)
        text = sent[-1]
        self.assertIn("Hard Rock Cafe", text)
        self.assertIn("1501 Broadway, New York", text)
        self.assertIn("https://www.openstreetmap.org/copyright", text)
        self.assertNotIn("Demo venue data", text)
        self.assertNotIn("geoapify.com", text)


def _reply_service(search):
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "r.sqlite3")
    service = RallyService(store, None, search, lambda *_args, **_kwargs: None)
    return tmp, service


class RestaurantReplyTests(unittest.TestCase):
    def test_provider_error_reports_lookup_unavailable(self):
        def search(_facts):
            raise PlacesError("Public venue search returned HTTP 429")

        tmp, service = _reply_service(search)
        with tmp:
            reply = service._recommend_restaurant(
                PlanFacts(activity="dinner", location="Midtown, New York"), [], "")
        self.assertNotIn("An Italian Table", reply)
        self.assertNotIn("Green Table", reply)
        self.assertIn("unavailable", reply.lower())

    def test_empty_results_ask_for_a_narrower_preference(self):
        tmp, service = _reply_service(lambda _facts: [])
        with tmp:
            reply = service._recommend_restaurant(
                PlanFacts(activity="dinner", location="Midtown, New York"), [], "")
        self.assertNotIn("An Italian Table", reply)
        self.assertNotIn("Green Table", reply)
        self.assertIn("cuisine", reply.lower())

    def test_missing_area_asks_for_an_area_without_searching(self):
        calls = []

        def search(facts):
            calls.append(facts)
            return []

        tmp, service = _reply_service(search)
        with tmp:
            reply = service._recommend_restaurant(PlanFacts(activity="dinner"), [], "")
        self.assertEqual(calls, [])
        self.assertIn("area", reply.lower())
        self.assertNotIn("An Italian Table", reply)
        self.assertNotIn("Green Table", reply)

    def test_returned_demo_fixture_is_named_and_labeled(self):
        fixture = Venue("demo-italian", "An Italian Table", "123 Main St, Midtown, New York",
                        40.75, -73.98, ("italian",), source="demo")
        tmp, service = _reply_service(lambda _facts: [fixture])
        with tmp:
            reply = service._recommend_restaurant(
                PlanFacts(activity="dinner", location="Midtown, New York"), [], "")
        self.assertIn("An Italian Table", reply)
        self.assertIn("demo", reply.lower())
        self.assertIn("not a booking", reply)

    def test_successful_public_recommendation_stays(self):
        found = Venue("osm-node-202", "Little Alley", "550 3rd Avenue, New York",
                      40.75, -73.98, ("chinese", "shanghai"), source="openstreetmap")
        tmp, service = _reply_service(lambda _facts: [found])
        with tmp:
            reply = service._recommend_restaurant(
                PlanFacts(activity="dinner", location="Midtown, New York"), [], "")
        self.assertIn("Little Alley", reply)
        self.assertIn("not a booking", reply)
        self.assertNotIn("demo", reply.lower())
        self.assertNotIn("An Italian Table", reply)

    def test_known_diet_conflicts_are_not_recommended(self):
        steak = Venue("steak-1", "Blood & Bone Steakhouse", "1 Meat St",
                      40.75, -73.98, ("steak",))
        tmp, service = _reply_service(lambda _facts: [steak])
        messages = [ChatMessage(
            "m1", "chat", "jake", "Dinner near Midtown. Jake is vegetarian.",
            datetime(2026, 9, 27, tzinfo=timezone.utc))]
        with tmp:
            reply = service._recommend_restaurant(
                PlanFacts(activity="dinner", location="Midtown, New York"), messages, "")
        lowered = reply.lower()
        self.assertNotIn("blood", lowered)
        self.assertNotIn("steak", lowered)
        self.assertNotIn("green table", lowered)
        self.assertNotIn("an italian table", lowered)
        self.assertIn("cuisine", lowered)

    def test_excluded_cuisine_is_not_suggested(self):
        sushi = Venue("s1", "Sushi Nakazawa", "23 Commerce St",
                      40.75, -73.98, ("sushi",))
        tmp, service = _reply_service(lambda _facts: [sushi])
        with tmp:
            reply = service._recommend_restaurant(
                PlanFacts(activity="dinner", location="Midtown, New York",
                          excluded_cuisines=["sushi"]), [], "")
        self.assertNotIn("Nakazawa", reply)
        self.assertNotIn("sushi", reply.lower())
        self.assertIn("cuisine", reply.lower())

    def test_untagged_venue_is_not_described_as_fitting_a_diet(self):
        pasta = Venue("p1", "Pasta House", "12 Main St", 40.75, -73.98, ("italian",))
        tmp, service = _reply_service(lambda _facts: [pasta])
        messages = [ChatMessage(
            "m1", "chat", "jake", "Jake is vegetarian.",
            datetime(2026, 9, 27, tzinfo=timezone.utc))]
        with tmp:
            reply = service._recommend_restaurant(
                PlanFacts(activity="dinner", location="Midtown, New York"), messages, "")
        self.assertIn("Pasta House", reply)
        self.assertNotIn("vegetarian", reply.lower())
        self.assertIn("not a booking", reply)


if __name__ == "__main__":
    unittest.main()
