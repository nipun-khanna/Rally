import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pytest

from app.config import Settings, build_service
from app.agent import GrokClient
from app.muse import MuseExtractor
from app.calendar import CalendarEvent, CalendarError
from app.models import Proposal


def test_browser_defaults_off_and_requires_private_owner():
    settings = Settings.from_env({})
    assert settings.browser_enabled is False
    assert settings.browser_owner_chat_id == ""
    assert settings.browser_owner_sender_id == ""

    with pytest.raises(ValueError):
        Settings.from_env({"RALLY_BROWSER_ENABLED": "1"})


@pytest.mark.parametrize("override", [
    {"RALLY_BROWSER_OWNER_CHAT_ID": "iMessage;+;group"},
    {"RALLY_BROWSER_OWNER_CHAT_ID": "iMessage;-;"},
    {"RALLY_BROWSER_OWNER_CHAT_ID": "any"},
    {"RALLY_BROWSER_OWNER_SENDER_ID": ""},
    {"RALLY_BROWSER_PROFILE_PATH": "data/other/profile"},
    {"RALLY_BROWSER_PROFILE_PATH": "data/browser/../other"},
    {"RALLY_BROWSER_DOWNLOAD_PATH": "data/other/downloads"},
    {"RALLY_BROWSER_MAX_ACTIONS": "0"},
    {"RALLY_BROWSER_MAX_ACTIONS": "13"},
    {"RALLY_BROWSER_MAX_TEXT_CHARS": "999"},
    {"RALLY_BROWSER_MAX_TEXT_CHARS": "12001"},
])
def test_browser_rejects_unsafe_enabled_configuration(override):
    env = {"RALLY_BROWSER_ENABLED": "1",
           "RALLY_BROWSER_OWNER_CHAT_ID": "iMessage;-;owner",
           "RALLY_BROWSER_OWNER_SENDER_ID": "+15555550123"}
    env.update(override)
    with pytest.raises(ValueError):
        Settings.from_env(env)


def test_browser_accepts_limits_and_paths_within_ignored_directory():
    settings = Settings.from_env({
        "RALLY_BROWSER_ENABLED": "1",
        "RALLY_BROWSER_OWNER_CHAT_ID": "iMessage;-;owner",
        "RALLY_BROWSER_OWNER_SENDER_ID": "+15555550123",
        "RALLY_BROWSER_ADMIN_TOKEN": "W6SWqB8dA_5f5SUS2ms-CNu0WhxFLBL34ff2A7vfVBQ",
        "RALLY_BROWSER_PROFILE_PATH": "data/browser/custom-profile",
        "RALLY_BROWSER_DOWNLOAD_PATH": "data/browser/custom-downloads",
        "RALLY_BROWSER_MAX_ACTIONS": "12",
        "RALLY_BROWSER_MAX_TEXT_CHARS": "12000",
    })
    assert settings.browser_enabled is True
    assert settings.browser_owner_chat_id == "iMessage;-;owner"
    assert settings.browser_owner_sender_id == "+15555550123"
    assert settings.browser_admin_token == "W6SWqB8dA_5f5SUS2ms-CNu0WhxFLBL34ff2A7vfVBQ"
    assert settings.browser_profile_path == Path("data/browser/custom-profile")
    assert settings.browser_download_path == Path("data/browser/custom-downloads")
    assert settings.browser_max_actions == 12
    assert settings.browser_max_text_chars == 12000


def test_browser_accepts_any_prefixed_private_owner_chat():
    settings = Settings.from_env({
        "RALLY_BROWSER_ENABLED": "1",
        "RALLY_BROWSER_OWNER_CHAT_ID": "any;-;+15555550100",
        "RALLY_BROWSER_OWNER_SENDER_ID": "local-imessage-account",
        "RALLY_BROWSER_ADMIN_TOKEN": "W6SWqB8dA_5f5SUS2ms-CNu0WhxFLBL34ff2A7vfVBQ",
    })
    assert settings.browser_owner_chat_id == "any;-;+15555550100"
    assert settings.browser_owner_sender_id == "local-imessage-account"


def test_browser_accepts_service_dash_private_owner_chat():
    settings = Settings.from_env({
        "RALLY_BROWSER_ENABLED": "1",
        "RALLY_BROWSER_OWNER_CHAT_ID": "SMS;-;+15555550100",
        "RALLY_BROWSER_OWNER_SENDER_ID": "local-imessage-account",
        "RALLY_BROWSER_ADMIN_TOKEN": "W6SWqB8dA_5f5SUS2ms-CNu0WhxFLBL34ff2A7vfVBQ",
    })
    assert settings.browser_owner_chat_id == "SMS;-;+15555550100"
    assert settings.browser_owner_sender_id == "local-imessage-account"


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
            self.assertEqual((settings.grok_reply_model, settings.grok_reply_effort),
                             ("grok-4.3", "none"))
            self.assertEqual(Settings.from_env({"RALLY_GROK_EXTRACTION_EFFORT":"MEDIUM"}).grok_extraction_effort,
                             "medium")
            with self.assertRaises(ValueError):
                Settings.from_env({"RALLY_GROK_EXTRACTION_EFFORT":"none"})
            with self.assertRaises(ValueError):
                Settings.from_env({"RALLY_GROK_REPLY_MODEL": "grok-4.7"})
            with self.assertRaises(ValueError):
                Settings.from_env({"RALLY_GROK_REPLY_MODEL": "other-model"})
            custom = Settings.from_env({"RALLY_GROK_REPLY_MODEL": "grok-4.7",
                                        "RALLY_GROK_REPLY_REASONING_EFFORT": "low",
                                        "RALLY_GROK_REPLY_TIMEOUT": "12"})
            self.assertEqual((custom.grok_reply_model, custom.grok_reply_effort,
                              custom.grok_reply_timeout), ("grok-4.7", "low", 12))
            chosen = Settings.from_env({"RALLY_ALLOWED_CHAT_GUIDS": "any;+;chat1, any;+;chat2"})
            self.assertEqual(chosen.allowed_chat_ids, frozenset({"any;+;chat1", "any;+;chat2"}))
            with self.assertRaises(ValueError):
                Settings.from_env({"RALLY_STALL_MINUTES": "0"})

    def test_fixture_venue_is_labeled_and_no_provider_key_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({"RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                                          "RALLY_DEMO_MODE": "1", "RALLY_DEMO_VENUES": "1"})
            service = build_service(settings)
            self.assertEqual(service.agent.model, "grok-4.7")
            self.assertEqual(service.reply_agent.model, "grok-4.3")
            self.assertEqual(service.reply_agent.direct_reasoning_effort, "none")
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
            self.assertTrue(service.defer_heavy_work)
            self.assertIsNotNone(service.typing_fn)

    def test_live_react_and_typing_do_not_block_on_helper_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({
                "RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                "RALLY_BLUEBUBBLES_URL": "http://127.0.0.1:1234",
                "RALLY_BLUEBUBBLES_PASSWORD": "secret",
            })
            with patch("app.config.send_reaction") as react, patch("app.config.set_typing") as typing:
                service = build_service(settings)
                service.react_fn("any;+;chat1", "msg", "like")
                service.typing_fn("any;+;chat1", True)
            self.assertIs(react.call_args.kwargs.get("wait_for_helper"), False)
            self.assertIs(typing.call_args.kwargs.get("wait_for_helper"), False)

    def test_calendar_is_opt_in_and_capped_before_provider_call(self):
        with self.assertRaises(ValueError):
            Settings.from_env({"RALLY_CALENDAR_ENABLED": "1"})
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({"RALLY_DATABASE_PATH": str(Path(tmp) / "r.sqlite3"),
                "RALLY_CALENDAR_ENABLED": "1", "RALLY_GOOGLE_CLIENT_ID": "client",
                "RALLY_GOOGLE_CLIENT_SECRET": "secret", "RALLY_GOOGLE_REFRESH_TOKEN": "refresh",
                "RALLY_GOOGLE_CALENDAR_ID": "primary", "RALLY_MAX_CALENDAR_REQUESTS": "2"})
            service = build_service(settings)
            self.assertIsNotNone(service.calendar_fn)
            self.assertIsNotNone(service.availability_fn)
            with patch("app.config.get_calendar_busy", return_value=[]) as freebusy:
                self.assertEqual(service.availability_fn("2026-10-02", "America/New_York"), [])
                freebusy.assert_called_once()
            proposal = Proposal("p1", "plan", 1, "v", "Venue", "Address", "2026-10-02", "20:00", 4)
            with patch("app.config.create_calendar_event",
                       return_value=CalendarEvent("p1", "event", None)) as create:
                self.assertEqual(service.calendar_fn(proposal, "approval", "RLY-1").event_id, "event")
                with self.assertRaises(CalendarError):
                    service.calendar_fn(proposal, "approval", "RLY-1")
                create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
