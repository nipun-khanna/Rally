import unittest
from unittest.mock import patch
import httpx
from datetime import datetime, timezone

from app.agent import DirectAnswer, Extracted, GrokClient
from app.models import ChatMessage, PlanFacts


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.messages = [ChatMessage("m1", "chat", "nick", "Dinner Friday?", datetime(2026, 9, 22, 18, tzinfo=timezone.utc))]

    def test_provider_timeout_is_identifiable_without_leaking_request(self):
        with patch('app.agent.httpx.post', side_effect=httpx.ReadTimeout('secret request text')) as post:
            with self.assertRaises(RuntimeError) as failure:
                GrokClient('secret-key').extract(self.messages, None)
        self.assertEqual(failure.exception.kind, 'timeout')
        self.assertEqual(failure.exception.stage, 'extracted')
        self.assertIsNone(failure.exception.status_code)
        self.assertNotIn('secret', str(failure.exception))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs['timeout'], 60)

    def test_provider_http_failure_exposes_only_status(self):
        response = httpx.Response(429, text='secret response', request=httpx.Request('POST', 'https://api.x.ai/v1/chat/completions'))
        with patch('app.agent.httpx.post', return_value=response):
            with self.assertRaises(RuntimeError) as failure:
                GrokClient('secret-key').extract(self.messages, None)
        self.assertEqual(failure.exception.kind, 'http')
        self.assertEqual(failure.exception.status_code, 429)
        self.assertNotIn('secret', str(failure.exception))

    def test_provider_malformed_response_has_separate_failure_kind(self):
        response = httpx.Response(200, json={'choices': []}, request=httpx.Request('POST', 'https://api.x.ai/v1/chat/completions'))
        with patch('app.agent.httpx.post', return_value=response):
            with self.assertRaises(RuntimeError) as failure:
                GrokClient('key').extract(self.messages, None)
        self.assertEqual(failure.exception.kind, 'response')

    def test_direct_reply_keeps_short_timeout_when_extraction_budget_changes(self):
        response = httpx.Response(200, json={'choices': [{'message': {'content': '{"message":"Hello"}'}}]}, request=httpx.Request('POST', 'https://api.x.ai/v1/chat/completions'))
        with patch('app.agent.httpx.post', return_value=response) as post:
            self.assertEqual(GrokClient('key', extraction_timeout=90).answer_direct('Rally hello', None, self.messages), 'Hello')
        self.assertEqual(post.call_args.kwargs['timeout'], 25)

    def test_extraction_timeout_configuration_is_bounded(self):
        for timeout in (0, 121, float('nan')):
            with self.assertRaises(ValueError):
                GrokClient('key', extraction_timeout=timeout)

    def test_extraction_uses_low_reasoning_only_on_supported_models(self):
        captured = []
        client = GrokClient('key', transport=lambda payload: captured.append(payload) or {},
                            extraction_reasoning_effort='low')
        client._call(Extracted, 'extract', {})
        client._call(DirectAnswer, 'answer', {})
        self.assertEqual(captured[0]['reasoning_effort'], 'low')
        self.assertNotIn('reasoning_effort', captured[1])
        unsupported = GrokClient('key', model='grok-4', transport=lambda payload: captured.append(payload) or {})
        unsupported._call(Extracted, 'extract', {})
        self.assertNotIn('reasoning_effort', captured[2])
        for effort in ('none', 'xhigh', ''):
            with self.assertRaises(ValueError):
                GrokClient('key', extraction_reasoning_effort=effort)

    def test_direct_answer_uses_group_context_and_validates_text(self):
        calls = []
        def transport(payload):
            calls.append(payload)
            return {"message": "Friday dinner is planned; the venue is still open."}
        client = GrokClient("key", transport=transport)
        facts = PlanFacts(activity="dinner", goal="Friday dinner")
        reply = client.answer_direct("Hey Rally, what's the plan?", facts, self.messages)
        self.assertIn("venue is still open", reply)
        self.assertEqual(calls[0]["response_format"]["type"], "json_schema")
        self.assertIn("Friday dinner", calls[0]["messages"][1]["content"])
        with self.assertRaises(ValueError):
            GrokClient("key", transport=lambda _: {"message": ""}).answer_direct(
                "Rally, update?", facts, self.messages)
        with self.assertRaises(ValueError):
            GrokClient("key", transport=lambda _: {"message": "   "}).answer_direct(
                "Rally, update?", facts, self.messages)

    def test_extracts_evidence_backed_facts(self):
        calls = []
        messages = self.messages + [
            ChatMessage("m2", "chat", "nick", "After 7, anything but sushi. Midtown, New York? Italian sounds good.",
                        self.messages[0].sent_at)]
        def transport(payload):
            calls.append(payload)
            return {"goal": "Friday dinner", "activity": "dinner", "participants": ["nick"],
                    "date": "2026-09-25", "time": None, "earliest_time": "19:00",
                    "location": "Midtown, New York", "excluded_cuisines": ["sushi"],
                    "preferred_cuisines": ["italian"],
                    "objections": [], "blockers": ["venue missing"],
                    "evidence": {"activity": ["m1"], "date": ["m1"],
                                 "earliest_time": ["m2"], "location": ["m2"],
                                 "excluded_cuisines": ["m2"],
                                 "preferred_cuisines": ["m2"]},
                    "confidence": 0.9, "abandoned": False}
        facts = GrokClient("key", transport=transport).extract(messages, None)
        self.assertEqual(facts.earliest_time, "19:00")
        self.assertEqual(facts.preferred_cuisines, ["italian"])
        self.assertEqual(facts.evidence["activity"], ["m1"])
        self.assertEqual(calls[0]["response_format"]["type"], "json_schema")

    def test_rejects_fabricated_participant(self):
        def transport(payload):
            return {"goal": "Dinner", "activity": "dinner", "participants": ["ghost"],
                    "date": None, "time": None, "earliest_time": None, "location": None,
                    "excluded_cuisines": [], "objections": [], "blockers": [],
                    "evidence": {}, "confidence": 0.8, "abandoned": False}
        with self.assertRaises(ValueError):
            GrokClient("key", transport=transport).extract(self.messages, None)

    def test_rejects_uncited_date(self):
        def transport(payload):
            return {"goal": "Friday dinner", "activity": "dinner", "participants": ["nick"],
                    "date": "2026-09-25", "time": None, "earliest_time": None,
                    "location": None, "excluded_cuisines": [], "objections": [],
                    "blockers": ["venue missing"], "evidence": {"activity": ["m1"]},
                    "confidence": 0.9, "abandoned": False}
        with self.assertRaisesRegex(ValueError, "date evidence"):
            GrokClient("key", transport=transport).extract(self.messages, None)

    def test_rejects_uncited_restriction(self):
        def transport(payload):
            return {"goal": "Dinner", "activity": "dinner", "participants": ["nick"],
                    "date": None, "time": None, "earliest_time": None,
                    "location": None, "excluded_cuisines": ["sushi"], "objections": [],
                    "blockers": ["venue missing"], "evidence": {"activity": ["m1"]},
                    "confidence": 0.9, "abandoned": False}
        with self.assertRaisesRegex(ValueError, "excluded_cuisines evidence"):
            GrokClient("key", transport=transport).extract(self.messages, None)

    def test_decision_must_be_known_action(self):
        def transport(payload):
            return {"action": "BUY", "reason": "venue", "tool": "search_places", "confidence": 0.9}
        with self.assertRaises(ValueError):
            GrokClient("key", transport=transport).decide(PlanFacts(activity="dinner"), self.messages)

    def test_rejects_unresolved_relative_date_as_confirmed_date(self):
        def transport(payload):
            return {"goal": "Dinner", "activity": "dinner", "participants": ["nick"],
                    "date": "next Friday", "time": None, "earliest_time": None,
                    "location": "Midtown", "excluded_cuisines": [], "objections": [],
                    "blockers": ["date unclear"], "evidence": {"date": ["m1"]},
                    "confidence": 0.8, "abandoned": False}
        with self.assertRaises(ValueError):
            GrokClient("key", transport=transport).extract(self.messages, None)

    def test_resolves_friday_against_message_time_and_chat_zone(self):
        message = ChatMessage("m-friday", "chat", "nick", "Dinner Friday?",
                              datetime(2026, 9, 24, 2, 0, tzinfo=timezone.utc))
        def response(date):
            return {"goal": "Friday dinner", "activity": "dinner", "participants": ["nick"],
                    "date": date, "time": None, "earliest_time": None, "location": None,
                    "excluded_cuisines": [], "objections": [], "blockers": ["venue missing"],
                    "evidence": {"date": ["m-friday"]}, "confidence": 0.9, "abandoned": False}
        client = GrokClient("key", transport=lambda payload: response("2026-09-25"),
                            time_zone="America/New_York")
        self.assertEqual(client.extract([message], None).date, "2026-09-25")
        wrong = GrokClient("key", transport=lambda payload: response("2026-10-02"),
                           time_zone="America/New_York")
        with self.assertRaisesRegex(ValueError, "relative date"):
            wrong.extract([message], None)

    def test_rejects_wrong_tomorrow_resolution(self):
        message = ChatMessage("m-tomorrow", "chat", "nick", "Dinner tomorrow?",
                              datetime(2026, 9, 24, 2, 0, tzinfo=timezone.utc))
        def transport(payload):
            return {"goal": "Dinner", "activity": "dinner", "participants": ["nick"],
                    "date": "2026-09-25", "time": None, "earliest_time": None, "location": None,
                    "excluded_cuisines": [], "objections": [], "blockers": ["venue missing"],
                    "evidence": {"date": ["m-tomorrow"]}, "confidence": 0.9, "abandoned": False}
        with self.assertRaisesRegex(ValueError, "relative date"):
            GrokClient("key", transport=transport,
                       time_zone="America/New_York").extract([message], None)

    def test_extraction_keeps_unspecified_party_size_unknown(self):
        def transport(payload):
            return {"goal": "Dinner", "activity": "dinner", "participants": ["nick"],
                    "date": None, "time": None, "earliest_time": None, "location": None,
                    "excluded_cuisines": [], "objections": [], "blockers": ["party size unclear"],
                    "evidence": {}, "confidence": 0.7, "abandoned": False}
        facts = GrokClient("key", transport=transport).extract(self.messages, None)
        self.assertIsNone(facts.party_size)


if __name__ == "__main__":
    unittest.main()


def test_direct_answer_prompt_matches_group_tone():
    from app.models import ChatMessage
    at=datetime.now(timezone.utc)
    seen=[]
    client=GrokClient('key',transport=lambda payload: seen.append(payload) or {'message':'Sure'})
    messages=[ChatMessage('c1','chat','friend','yo bro wanna eat lol',at)]
    assert client.answer_direct('Rally, what do you think?',None,messages)=='Sure'
    assert 'casual' in seen[0]['messages'][0]['content'].lower()
    assert 'slang' in seen[0]['messages'][0]['content'].lower()
