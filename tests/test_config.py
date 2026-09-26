import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings, build_service
from app.agent import GrokClient
from app.muse import MuseExtractor
from app.calendar import CalendarEvent, CalendarError
from app.models import Proposal


class ConfigTests(unittest.TestCase):
    def test_reads_settings_and_rejects_invalid_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({"RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                                          "RALLY_STALL_MINUTES": "2", "RALLY_DEMO_MODE": "1",
                                          "RALLY_DEMO_VENUES": "1"})
            self.assertEqual(settings.stall_minutes, 2)
            self.assertTrue(settings.demo_mode)
            self.assertTrue(settings.demo_venues)
            self.assertEqual(settings.allowed_chat_ids, frozenset())
            self.assertEqual(settings.grok_extraction_effort, "low")
            self.assertEqual(Settings.from_env({"RALLY_GROK_EXTRACTION_EFFORT":"MEDIUM"}).grok_extraction_effort,
                             "medium")
            with self.assertRaises(ValueError):
                Settings.from_env({"RALLY_GROK_EXTRACTION_EFFORT":"none"})
            chosen = Settings.from_env({"RALLY_ALLOWED_CHAT_GUIDS": "any;+;chat1, any;+;chat2"})
            self.assertEqual(chosen.allowed_chat_ids, frozenset({"any;+;chat1", "any;+;chat2"}))
            with self.assertRaises(ValueError):
                Settings.from_env({"RALLY_STALL_MINUTES": "0"})

    def test_fixture_venue_is_labeled_and_no_provider_key_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({"RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                                          "RALLY_DEMO_MODE": "1", "RALLY_DEMO_VENUES": "1"})
            service = build_service(settings)
            places = service.search_fn(None)
            self.assertEqual(len(places), 1)
            self.assertEqual(places[0].source, "demo")

    def test_fixture_venue_cannot_be_used_for_another_city(self):
        from app.models import PlanFacts
        from app.places import PlacesError
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({"RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                                          "RALLY_DEMO_MODE": "1", "RALLY_DEMO_VENUES": "1"})
            service = build_service(settings)
            for location in ("Atlanta, GA", "Midtown, Atlanta, GA"):
                with self.subTest(location=location), self.assertRaises(PlacesError):
                    service.search_fn(PlanFacts(location=location))

    def test_muse_is_optional_extractor_and_grok_keeps_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({"RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                                          "RALLY_META_MODEL_API_KEY": "meta-test-key",
                                          "RALLY_EXTRACTION_PROVIDER": "muse"})
            service = build_service(settings)
            self.assertIsInstance(service.extractor, MuseExtractor)
            self.assertIsInstance(service.agent, GrokClient)
            self.assertEqual(service.extractor.api_key, "meta-test-key")

    def test_calendar_is_opt_in_and_capped_before_provider_call(self):
        with self.assertRaises(ValueError):
            Settings.from_env({"RALLY_CALENDAR_ENABLED": "1"})
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({"RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                "RALLY_CALENDAR_ENABLED": "1", "RALLY_GOOGLE_CLIENT_ID": "client",
                "RALLY_GOOGLE_CLIENT_SECRET": "secret", "RALLY_GOOGLE_REFRESH_TOKEN": "refresh",
                "RALLY_GOOGLE_CALENDAR_ID": "primary", "RALLY_MAX_CALENDAR_REQUESTS": "1"})
            service = build_service(settings)
            self.assertIsNotNone(service.calendar_fn)
            proposal = Proposal("p1", "plan", 1, "v", "Venue", "Address", "2026-10-02", "20:00", 4)
            with patch("app.config.create_calendar_event",
                       return_value=CalendarEvent("p1", "event", None)) as create:
                self.assertEqual(service.calendar_fn(proposal, "approval", "RLY-1").event_id, "event")
                with self.assertRaises(CalendarError):
                    service.calendar_fn(proposal, "approval", "RLY-1")
                create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
