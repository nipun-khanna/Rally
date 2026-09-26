import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import httpx

from app.models import ChatMessage, PlanFacts
from app.muse import MuseExtractor


class MuseExtractorTests(unittest.TestCase):
    def setUp(self):
        self.message = ChatMessage("m1", "group", "alex", "Dinner next Friday after 7, no sushi",
                                   datetime(2026, 9, 25, 14, tzinfo=timezone.utc))
        self.facts = {
            "goal": "Friday dinner", "activity": "dinner", "participants": ["alex"],
            "date": "2026-10-02", "time": None, "earliest_time": "19:00",
            "location": None, "excluded_cuisines": ["sushi"], "objections": [],
            "blockers": ["venue missing"],
            "evidence": {"activity": ["m1"], "date": ["m1"], "earliest_time": ["m1"],
                         "excluded_cuisines": ["m1"]},
            "confidence": 0.9, "abandoned": False,
        }

    def test_extract_uses_meta_model_with_group_context_and_existing_contract(self):
        calls = []
        extractor = MuseExtractor(
            "meta-key", transport=lambda payload: calls.append(payload) or self.facts,
            default_city="New York", time_zone="America/New_York")
        result = extractor.extract([self.message], PlanFacts(activity="dinner"))
        self.assertIsInstance(result, PlanFacts)
        self.assertEqual(result.excluded_cuisines, ["sushi"])
        self.assertEqual(calls[0]["model"], "muse-spark-1.3")
        self.assertEqual(calls[0]["response_format"]["type"], "json_schema")
        self.assertNotIn("tools", calls[0])
        self.assertIn("New York", calls[0]["messages"][1]["content"])

    def test_rejects_unsupported_participant_or_evidence(self):
        for change in ({"participants": ["ghost"]},
                       {"evidence": {"activity": ["fabricated"]}}):
            with self.subTest(change=change):
                extractor = MuseExtractor("key", transport=lambda payload: self.facts | change)
                with self.assertRaises(ValueError):
                    extractor.extract([self.message], None)

    def test_rejects_unresolved_date(self):
        extractor = MuseExtractor("key", transport=lambda payload: self.facts | {"date": "next Friday"})
        with self.assertRaises(ValueError):
            extractor.extract([self.message], None)

    def test_missing_key_fails_before_network_call(self):
        extractor = MuseExtractor("")
        with patch("app.muse.httpx.post") as post:
            with self.assertRaisesRegex(RuntimeError, "Meta Model API key"):
                extractor.extract([self.message], None)
            post.assert_not_called()

    def test_http_request_uses_meta_chat_endpoint_and_bearer_key(self):
        response = httpx.Response(200, json={"choices": [{"message": {
            "content": __import__("json").dumps(self.facts)}}]}, request=httpx.Request("POST", "https://api.meta.ai/v1/chat/completions"))
        with patch("app.muse.httpx.post", return_value=response) as post:
            result = MuseExtractor("secret").extract([self.message], None)
        self.assertEqual(result.activity, "dinner")
        self.assertEqual(post.call_args.args[0], "https://api.meta.ai/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer secret")

    def test_http_errors_are_sanitized(self):
        with patch("app.muse.httpx.post", side_effect=httpx.TimeoutException("private details")):
            with self.assertRaisesRegex(RuntimeError, "Meta Model API request failed") as raised:
                MuseExtractor("secret").extract([self.message], None)
        self.assertNotIn("private details", str(raised.exception))

    def test_decision_method_is_not_exposed(self):
        self.assertFalse(hasattr(MuseExtractor("key"), "decide"))

    def test_contributor_tier_cannot_receive_group_messages(self):
        with self.assertRaisesRegex(ValueError, "standard tier"):
            MuseExtractor("key", model="muse-spark-1.3-contributor")


if __name__ == "__main__":
    unittest.main()
