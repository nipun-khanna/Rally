import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent import AgentDecision, GrokProviderError
from app.bluebubbles import DeliveryUncertainError
from app.calendar import CalendarEvent
from app.models import ChatMessage, PlanFacts
from app.orchestrator import RallyService
from app.places import Venue
from app.places import PlacesError
from app.store import Store


NOW = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)
VENUE = Venue("v1", "An Italian Table", "123 Main St", 40.75, -73.98, ("italian",))


class FakeAgent:
    def __init__(self, facts):
        self.facts = facts
        self.previous_results = []
        self.direct_calls = []

    def extract(self, messages, previous):
        return self.facts

    def decide(self, facts, messages, previous_results=None):
        self.previous_results.append(previous_results or [])
        venue_id = previous_results[0]["venues"][0]["id"] if previous_results else None
        return AgentDecision(action="PROPOSE", reason="venue missing", tool="search_places",
                             confidence=0.9, venue_id=venue_id)

    def answer_direct(self, request, facts, messages):
        self.direct_calls.append((request, facts, messages))
        return "Friday dinner is planned after 7 in Midtown; we still need a venue."


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "rally.sqlite3")
        self.facts = PlanFacts(goal="Friday dinner", activity="dinner",
                               participants=["nick", "sarah", "alex", "maya"],
                               date="2026-10-02", earliest_time="19:00",
                               location="Midtown, New York", excluded_cuisines=["sushi"],
                               blockers=["venue missing"], confidence=0.9)
        self.agent = FakeAgent(self.facts)
        self.sent = []
        self.service = RallyService(self.store, self.agent, lambda facts: [VENUE],
                                    lambda chat_id, text: self.sent.append((chat_id, text)),
                                    stall_minutes=30)
        self.store.save_plan("chat1", self.facts, NOW - timedelta(minutes=31))

    def tearDown(self):
        self.tmp.cleanup()

    def test_direct_address_replies_once_in_same_chat_with_plan_context(self):
        message = ChatMessage("direct-1", "chat1", "nick", "Hey Rally, what's the vibe?", NOW)
        self.assertTrue(self.service.receive(message))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], "chat1")
        self.assertIn("Friday dinner", self.sent[0][1])
        self.assertEqual(self.agent.direct_calls[0][0], message.text)
        self.assertEqual(self.agent.direct_calls[0][1].date, "2026-10-02")
        self.assertFalse(self.service.receive(message))
        self.assertEqual(len(self.sent), 1)

    def test_direct_reply_uses_latest_twenty_human_messages_from_its_chat(self):
        for number in range(25):
            self.store.add_message(ChatMessage(f"history-{number}", "chat1", "nick",
                                              f"Message {number}", NOW + timedelta(seconds=number)))
        self.store.add_message(ChatMessage("other-group", "chat2", "outsider", "Private", NOW))
        self.store.add_message(ChatMessage("bot-message", "chat1", "rally", "Bot", NOW, True))
        message = ChatMessage("direct-window", "chat1", "nick", "Hey Rally, what's the vibe?",
                              NOW + timedelta(seconds=26))
        self.service.receive(message)
        direct_messages = self.agent.direct_calls[-1][2]
        self.assertEqual(len(direct_messages), 20)
        self.assertEqual(direct_messages[0].message_id, "history-6")
        self.assertEqual(direct_messages[-1].message_id, "direct-window")
        self.assertTrue(all(item.chat_id == "chat1" and not item.is_from_rally
                            for item in direct_messages))

    def test_direct_reply_latency_logs_exclude_message_text(self):
        message = ChatMessage("timed", "chat1", "nick", "Rally, secret phrase?", NOW)
        with self.assertLogs('rally.latency', level='INFO') as logs:
            self.service.receive(message)
        output = '\n'.join(logs.output)
        for phase in ('chat_lock_wait', 'direct_model', 'bluebubbles_delivery',
                      'extraction', 'receive_total'):
            self.assertIn(f'phase={phase}', output)
        self.assertNotIn('secret phrase', output)

    def test_direct_call_reacts_with_eyes_then_like_after_reply(self):
        reactions = []
        self.service.react_fn = lambda chat_id, message_id, reaction: reactions.append(
            (chat_id, message_id, reaction))
        seen_before_reply = []

        def slow_answer(request, facts, messages):
            seen_before_reply.append(list(reactions))
            return "working on it"

        self.agent.answer_direct = slow_answer
        message = ChatMessage("react-direct", "chat1", "nick", "Rally, what's the vibe?", NOW)
        self.assertTrue(self.service.receive(message))
        self.assertEqual(seen_before_reply[0], [("chat1", "react-direct", "👀")])
        self.assertEqual(reactions, [
            ("chat1", "react-direct", "👀"),
            ("chat1", "react-direct", "like"),
        ])
        self.assertEqual(len(self.sent), 1)

    def test_ordinary_chat_does_not_react(self):
        reactions = []
        self.service.react_fn = lambda chat_id, message_id, reaction: reactions.append(reaction)
        self.assertTrue(self.service.receive(ChatMessage("ordinary", "chat1", "nick", "Dinner Friday?", NOW)))
        self.assertEqual(reactions, [])
        self.assertEqual(self.sent, [])

    def test_failed_delivery_keeps_eyes_without_completion_reaction(self):
        reactions = []
        self.service.react_fn = lambda chat_id, message_id, reaction: reactions.append(reaction)
        self.service.send_fn = lambda chat_id, text: (_ for _ in ()).throw(RuntimeError("offline"))
        self.assertTrue(self.service.receive(ChatMessage("react-fail", "chat1", "nick", "Rally, recap?", NOW)))
        self.assertEqual(reactions, ["👀"])

    def test_direct_reply_sends_in_the_inbound_message_thread(self):
        sent = []

        def send(chat_id, text, selected_message_guid=None):
            sent.append((chat_id, text, selected_message_guid))

        self.service.send_fn = send
        message = ChatMessage("inbound-guid", "chat1", "nick", "Hey Rally, recap?", NOW)
        self.assertTrue(self.service.receive(message))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "chat1")
        self.assertTrue(sent[0][1])
        self.assertEqual(sent[0][2], "inbound-guid")

    def test_eyes_attempted_when_invalid_guid_does_not_crash_receive(self):
        reactions = []

        def react(chat_id, message_id, reaction):
            reactions.append((chat_id, message_id, reaction))
            raise ValueError("A target message GUID is required")

        sent = []

        def send(chat_id, text, selected_message_guid=None):
            sent.append((chat_id, text, selected_message_guid))

        self.service.react_fn = react
        self.service.send_fn = send
        message = ChatMessage("bad guid", "chat1", "nick", "Rally, recap?", NOW)
        self.assertTrue(self.service.receive(message))
        self.assertEqual(reactions[0], ("chat1", "bad guid", "👀"))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2], "bad guid")

    def test_seen_message_warms_helper_without_blocking_reply(self):
        warmed = []
        self.service.helper_warm_fn = lambda: warmed.append("warm")
        self.assertTrue(self.service.receive(
            ChatMessage("warm-1", "chat1", "nick", "Rally, recap?", NOW)))
        self.assertEqual(warmed, ["warm"])
        self.assertEqual(len(self.sent), 1)

    def test_short_question_after_direct_reply_carries_one_followup_turn(self):
        first = ChatMessage("direct-followup-1", "chat1", "nick",
                            "Rally, what can you help with?", NOW)
        followup = ChatMessage("direct-followup-2", "chat1", "sarah",
                               "What can you do?", NOW + timedelta(minutes=1))

        self.assertTrue(self.service.receive(first))
        self.assertTrue(self.service.receive(followup))

        self.assertEqual([call[0] for call in self.agent.direct_calls],
                         [first.text, followup.text])
        self.assertEqual(len(self.sent), 2)

    def test_followup_turn_does_not_carry_past_unrelated_or_expire(self):
        first = ChatMessage("direct-boundary-1", "chat1", "nick", "Rally, hello", NOW)
        self.service.receive(first)
        unrelated = ChatMessage("direct-boundary-2", "chat1", "sarah",
                                "Dinner is at seven", NOW + timedelta(minutes=1))
        self.service.receive(unrelated)
        later = ChatMessage("direct-boundary-3", "chat1", "sarah",
                            "What can you do?", NOW + timedelta(minutes=2))
        self.service.receive(later)
        stale = ChatMessage("direct-boundary-4", "chat1", "sarah",
                            "What can you do?", NOW + timedelta(minutes=6))
        self.service.receive(stale)

        self.assertEqual([call[0] for call in self.agent.direct_calls], [first.text])
        self.assertEqual(len(self.sent), 1)

    def test_direct_reply_is_not_signed_with_rally_name(self):
        message = ChatMessage("direct-unsigned", "chat1", "nick", "Hey Rally, what's up?", NOW)
        self.service.receive(message)
        self.assertFalse(self.sent[0][1].startswith("Rally:"))

    def test_legacy_queued_reply_is_unsigned_before_delivery(self):
        self.store.queue_message("chat1", "Rally: legacy reply", "direct_reply", "old-message")
        self.service.deliver_pending("chat1")
        self.assertEqual(self.sent, [("chat1", "legacy reply")])

    def test_incidental_name_and_ordinary_chat_do_not_prompt_reply(self):
        for number, text in enumerate(("I saw a rally today", "We should ask Rally", "Dinner Friday?")):
            self.assertTrue(self.service.receive(ChatMessage(f"other-{number}", "chat1", "nick", text, NOW)))
        self.assertEqual(self.agent.direct_calls, [])
        self.assertEqual(self.sent, [])

    def test_addressed_booking_request_does_not_count_as_approval(self):
        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.assertTrue(self.service.receive(ChatMessage(
            "direct-book", "chat1", "nick", "Rally, book it", NOW)))
        self.assertIsNone(self.store.reservation(proposal_id))
        self.assertEqual(len(self.agent.direct_calls), 1)

    def test_direct_reply_survives_extraction_failure_without_duplicate(self):
        class FailingExtractor:
            def extract(self, messages, previous):
                raise RuntimeError("extractor unavailable")
        message = ChatMessage("direct-retry", "chat1", "nick", "Rally, recap?", NOW)
        self.service.extractor = FailingExtractor()
        self.assertTrue(self.service.receive(message))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.store.is_processed(message.message_id))
        self.service.extractor = self.agent
        self.assertFalse(self.service.receive(message))
        self.assertEqual(len(self.sent), 1)

    def test_stalled_plan_proposes_once_and_books_only_after_approval(self):
        self.assertEqual(self.service.tick(NOW), 1)
        self.assertEqual(self.service.tick(NOW + timedelta(minutes=1)), 0)
        pending = self.store.get_plan("chat1").pending_proposal_id
        self.assertIsNotNone(pending)
        self.assertIsNone(self.store.reservation(pending))
        self.assertIn("8:00 PM", self.sent[0][1])
        self.assertIn("Reply 'Book it'", self.sent[0][1])
        self.assertTrue(self.service.receive(ChatMessage("m6", "chat1", "nick", "Book it.", NOW)))
        confirmation = self.store.reservation(pending)
        self.assertEqual(confirmation.status, "confirmed")
        self.assertEqual(self.store.get_plan("chat1").state, "DONE")
        self.assertIn("Demo reservation", self.sent[-1][1])
        self.assertFalse(self.service.receive(ChatMessage("m6", "chat1", "nick", "Book it.", NOW)))
        self.assertEqual(self.store.reservation(pending), confirmation)
        self.assertEqual(self.agent.previous_results[-1][0]["venues"][0]["id"], "v1")

    def test_reported_group_availability_combines_with_owner_calendar(self):
        facts = PlanFacts(goal="Friday dinner", activity="dinner", participants=["A", "B"],
                          date="2026-10-02", location="Midtown, New York",
                          blockers=["time and venue"], confidence=0.9)
        self.agent.facts = facts
        plan = self.store.save_plan("chat1", facts, NOW - timedelta(minutes=31))
        service = RallyService(self.store, self.agent, lambda _: [VENUE],
            lambda chat_id, text: self.sent.append((chat_id, text)), stall_minutes=30,
            availability_fn=lambda day, zone: [], time_zone="America/New_York")

        service.tick(NOW)
        self.assertIn("When are you generally free", self.sent[-1][1])
        self.assertIn("self-reported availability", self.sent[-1][1])
        service.receive(ChatMessage("availability-1", "chat1", "sarah",
                                    "I'm free all day Friday", NOW + timedelta(minutes=1)))
        service.receive(ChatMessage("availability-2", "chat1", "alex",
                                    "I'm free all day Friday", NOW + timedelta(minutes=1)))
        rows = self.store.availability_reports(plan.id, plan.version, facts.date)
        self.assertEqual(len(rows), 2)
        service.tick(NOW + timedelta(minutes=2))
        proposal = self.store.get_proposal(self.store.get_plan("chat1").pending_proposal_id)
        self.assertEqual(proposal.time, "09:00")
        self.assertIn("availability members reported", self.sent[-1][1])
        self.assertIn("other calendars weren’t checked", self.sent[-1][1])

    def test_reported_slot_is_rejected_when_owner_calendar_is_busy(self):
        facts = PlanFacts(goal="Friday dinner", activity="dinner", participants=["A", "B"],
                          date="2026-10-02", location="Midtown, New York",
                          blockers=["time and venue"], confidence=0.9)
        self.agent.facts = facts
        plan = self.store.save_plan("chat1", facts, NOW - timedelta(minutes=31))
        service = RallyService(self.store, self.agent, lambda _: [VENUE],
            lambda chat_id, text: self.sent.append((chat_id, text)), stall_minutes=30,
            availability_fn=lambda day, zone: [
                (datetime(2026, 10, 2, 9, tzinfo=timezone.utc),
                 datetime(2026, 10, 2, 21, tzinfo=timezone.utc))], time_zone="UTC")
        service.tick(NOW)
        service.receive(ChatMessage("availability-busy", "chat1", "sarah",
                                    "I'm free all day Friday", NOW + timedelta(minutes=1)))
        service.receive(ChatMessage("availability-busy-2", "chat1", "alex",
                                    "I'm free all day Friday", NOW + timedelta(minutes=1)))
        service.tick(NOW + timedelta(minutes=2))
        self.assertIsNone(self.store.get_plan("chat1").pending_proposal_id)
        self.assertIn("couldn’t find a two-hour slot", self.sent[-1][1])

    def test_restricted_service_ignores_other_chats_and_their_queued_work(self):
        restricted = RallyService(self.store, self.agent, lambda facts: [VENUE],
                                  lambda chat_id, text: self.sent.append((chat_id, text)),
                                  stall_minutes=30, allowed_chat_ids={"chosen-chat"})
        self.store.queue_message("chat1", "Old queued message", "ask", "old-plan")
        self.assertFalse(restricted.receive(ChatMessage("outside", "chat1", "nick",
                                                        "Dinner Friday?", NOW)))
        self.assertFalse(any(m.message_id == "outside" for m in self.store.recent_messages("chat1")))
        self.assertEqual(restricted.tick(NOW), 0)
        self.assertFalse(restricted.evaluate("chat1", NOW))
        self.assertEqual(self.sent, [])

    def test_agent_selects_from_actual_search_results(self):
        second = Venue("v2", "Another Italian Table", "2 Main St", 40.75, -73.98, ("italian",))
        self.service.search_fn = lambda facts: [VENUE, second]
        original = self.agent.decide
        def select_second(facts, messages, previous_results=None):
            result = original(facts, messages, previous_results)
            if previous_results:
                result.venue_id = "v2"
            return result
        self.agent.decide = select_second
        self.service.tick(NOW)
        proposal = self.store.get_proposal(self.store.get_plan("chat1").pending_proposal_id)
        self.assertEqual(proposal.venue_id, "v2")

    def test_preferred_cuisine_is_ranked_ahead_of_other_viable_venues(self):
        other = Venue("v2", "Generic Table", "2 Main St", 40.75, -73.98, ("american",))
        self.service.search_fn = lambda facts: [other, VENUE]
        preferred = PlanFacts(**{**self.facts.__dict__, "preferred_cuisines": ["italian"]})
        self.store.save_plan("chat1", preferred, NOW - timedelta(minutes=31))
        self.service.tick(NOW)
        proposal = self.store.get_proposal(self.store.get_plan("chat1").pending_proposal_id)
        self.assertEqual(proposal.venue_id, "v1")
        self.assertEqual(self.agent.previous_results[-1][0]["venues"][0]["id"], "v1")

    def test_explicit_party_size_is_preserved_in_proposal(self):
        self.store.save_plan("chat1", PlanFacts(**{**self.facts.__dict__, "party_size": 6}),
                             NOW - timedelta(minutes=31))
        self.service.tick(NOW)
        proposal = self.store.get_proposal(self.store.get_plan("chat1").pending_proposal_id)
        self.assertEqual(proposal.party_size, 6)

    def test_calendar_requires_specific_approval_and_reports_separately(self):
        calls = []
        self.service.calendar_fn = lambda proposal, message_id, confirmation_id: (
            calls.append((proposal.id, message_id, confirmation_id)) or
            CalendarEvent(proposal.id, "calendar-event-1", "https://calendar.example/event"))
        self.service.tick(NOW)
        self.assertIn("add a calendar event", self.sent[0][1])
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.service.receive(ChatMessage("calendar-approval", "chat1", "nick",
                                         "Book it and add a calendar event.", NOW))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], (proposal_id, "calendar-approval"))
        self.assertEqual(self.store.calendar_result(proposal_id)["status"], "confirmed")
        self.assertIn("Calendar event created", self.sent[-1][1])
        self.assertIn("Demo reservation confirmed", self.sent[-1][1])
        self.service.tick(NOW + timedelta(minutes=1))
        self.assertEqual(len(calls), 1)

    def test_plain_booking_approval_does_not_create_calendar_event(self):
        calls = []
        self.service.calendar_fn = lambda *args: calls.append(args)
        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.service.receive(ChatMessage("booking-only", "chat1", "nick", "Book it.", NOW))
        self.assertEqual(calls, [])
        self.assertIsNone(self.store.calendar_result(proposal_id))
        self.assertIn("Demo reservation confirmed", self.sent[-1][1])

    def test_calendar_failure_does_not_undo_or_repeat_reservation(self):
        self.service.calendar_fn = lambda *args: (_ for _ in ()).throw(RuntimeError("Calendar offline"))
        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.service.receive(ChatMessage("calendar-failed", "chat1", "nick",
                                         "Book it and add a calendar event.", NOW))
        self.assertIsNotNone(self.store.reservation(proposal_id))
        self.assertEqual(self.store.calendar_result(proposal_id)["status"], "unconfirmed")
        self.assertIn("Calendar event was not confirmed", self.sent[-1][1])
        sent_count = len(self.sent)
        self.service.tick(NOW + timedelta(minutes=1))
        self.assertEqual(len(self.sent), sent_count)

    def test_owner_calendar_is_rechecked_before_event_write(self):
        exact = PlanFacts(**{**self.facts.__dict__, "time": "20:00"})
        self.store.save_plan("chat1", exact, NOW - timedelta(minutes=31))
        checks = []
        def owner_busy(day, zone):
            checks.append(day)
            return ([] if len(checks) == 1 else
                    [(datetime(2026, 10, 3, 0, tzinfo=timezone.utc),
                      datetime(2026, 10, 3, 2, tzinfo=timezone.utc))])
        self.service.availability_fn = owner_busy
        writes = []
        self.service.calendar_fn = lambda *args: writes.append(args)
        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.service.receive(ChatMessage("late-calendar-approval", "chat1", "nick",
                                         "Book it and add a calendar event.", NOW))
        self.assertEqual(len(checks), 2)
        self.assertEqual(writes, [])
        self.assertEqual(self.store.calendar_result(proposal_id)["status"], "unconfirmed")
        self.assertIn("Calendar event was not confirmed", self.sent[-1][1])

    def test_interest_and_cross_chat_approval_do_not_book(self):
        self.service.tick(NOW)
        pending = self.store.get_plan("chat1").pending_proposal_id
        self.service.receive(ChatMessage("m7", "chat1", "alex", "I'm down", NOW))
        self.service.receive(ChatMessage("m8", "chat2", "nick", "Book it", NOW))
        self.assertIsNone(self.store.reservation(pending))

    def test_changed_terms_invalidate_proposal(self):
        self.service.tick(NOW)
        pending = self.store.get_plan("chat1").pending_proposal_id
        self.agent.facts = PlanFacts(**{**self.facts.__dict__, "time": "21:00"})
        self.service.receive(ChatMessage("m9", "chat1", "sarah", "Make it 9 instead", NOW))
        self.assertIsNone(self.store.get_plan("chat1").pending_proposal_id)
        self.service.receive(ChatMessage("m10", "chat1", "nick", "Book it", NOW))
        self.assertIsNone(self.store.reservation(pending))

    def test_send_failure_keeps_final_report_pending_without_rebooking(self):
        self.service.tick(NOW)
        pending = self.store.get_plan("chat1").pending_proposal_id
        self.service.send_fn = lambda chat_id, text: (_ for _ in ()).throw(RuntimeError("offline"))
        self.service.receive(ChatMessage("m11", "chat1", "nick", "Book it", NOW))
        self.assertEqual(self.store.get_plan("chat1").state, "EXECUTING")
        reservation = self.store.reservation(pending)
        self.service.send_fn = lambda chat_id, text: self.sent.append((chat_id, text))
        self.service.deliver_pending()
        self.assertEqual(self.store.get_plan("chat1").state, "DONE")
        self.assertEqual(self.store.reservation(pending), reservation)

    def test_reservation_failure_never_reports_confirmation(self):
        from unittest.mock import patch

        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        with patch("app.orchestrator.create_reservation", side_effect=RuntimeError("store unavailable")):
            self.service.receive(ChatMessage("failed-reservation", "chat1", "nick", "Book it", NOW))
        self.assertIsNone(self.store.reservation(proposal_id))
        self.assertEqual(self.store.get_plan("chat1").state, "EXECUTING")
        self.assertIn("Nothing is confirmed", self.sent[-1][1])
        self.assertNotIn("Demo reservation confirmed", self.sent[-1][1])
        sent_count = len(self.sent)
        self.service.tick(NOW + timedelta(minutes=1))
        self.assertEqual(len(self.sent), sent_count)
        self.assertIsNone(self.store.reservation(proposal_id))

    def test_expired_undelivered_proposal_is_not_sent_on_later_tick(self):
        self.service.send_fn = lambda chat, text: (_ for _ in ()).throw(RuntimeError("offline"))
        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.sent.clear()
        self.service.send_fn = lambda chat, text: self.sent.append((chat, text))
        self.service.tick(NOW + timedelta(hours=25))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.get_proposal(proposal_id).status, "stale")

    def test_ambiguous_bluebubbles_send_is_held_for_inspection(self):
        calls = []
        def uncertain(chat, text):
            calls.append((chat, text))
            raise DeliveryUncertainError("BlueBubbles outcome is uncertain")
        self.service.send_fn = uncertain
        self.service.tick(NOW)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.pending_messages(), [])
        self.service.tick(NOW + timedelta(minutes=1))
        self.assertEqual(len(calls), 1)

    def test_failed_extraction_can_be_retried_from_same_webhook(self):
        original = self.agent.extract
        attempts = [0]
        def flaky(messages, previous):
            attempts[0] += 1
            if attempts[0] == 1:
                raise RuntimeError("model offline")
            return original(messages, previous)
        self.agent.extract = flaky
        message = ChatMessage("m12", "chat2", "nick", "Dinner Friday?", NOW)
        with self.assertRaises(RuntimeError):
            self.service.receive(message)
        self.assertTrue(self.service.receive(message))
        self.assertEqual(attempts[0], 2)

    def test_concurrent_scheduler_ticks_make_one_proposal(self):
        original = self.agent.decide
        calls = [0]
        def slow(*args, **kwargs):
            calls[0] += 1
            time.sleep(0.02)
            return original(*args, **kwargs)
        self.agent.decide = slow
        threads = [threading.Thread(target=self.service.tick, args=(NOW,)) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(calls[0], 2)  # one tool decision and one result-based choice
        self.assertEqual(len(self.sent), 1)

    def test_slow_extraction_in_one_chat_does_not_block_another_chat(self):
        entered = threading.Event()
        release = threading.Event()
        original = self.agent.extract

        def slow_for_first_chat(messages, previous):
            if any(message.message_id == "slow-chat-one" for message in messages):
                entered.set()
                release.wait(timeout=2)
            return original(messages, previous)

        self.agent.extract = slow_for_first_chat
        first = threading.Thread(target=self.service.receive, args=(
            ChatMessage("slow-chat-one", "chat1", "nick", "Rally is this still happening?", NOW),))
        second = threading.Thread(target=self.service.receive, args=(
            ChatMessage("fast-chat-two", "chat2", "maya", "Dinner Friday?", NOW),))
        first.start()
        self.assertTrue(entered.wait(timeout=1), "first chat never reached the blocked extraction")
        second.start()
        try:
            second.join(timeout=0.5)
            self.assertFalse(second.is_alive(), "another chat waited behind unrelated extraction")
        finally:
            release.set()
            first.join(timeout=2)
            second.join(timeout=2)

    def test_demo_trigger_uses_normal_stall_rule(self):
        self.assertFalse(self.service.evaluate("chat1", NOW - timedelta(minutes=2)))
        self.assertTrue(self.service.evaluate("chat1", NOW))
        self.assertFalse(self.service.evaluate("chat1", NOW))

    def test_search_failure_does_not_invent_a_venue(self):
        self.service.search_fn = lambda facts: (_ for _ in ()).throw(RuntimeError("offline"))
        self.service.tick(NOW)
        self.assertIsNone(self.store.get_plan("chat1").pending_proposal_id)
        self.assertIn("couldn't search", self.sent[-1][1])

    def test_unclear_city_asks_for_city(self):
        self.service.search_fn = lambda facts: (_ for _ in ()).throw(PlacesError("The city is unclear"))
        self.service.tick(NOW)
        self.assertIsNone(self.store.get_plan("chat1").pending_proposal_id)
        self.assertIn("Which city", self.sent[-1][1])

    def test_invalid_model_selected_venue_is_not_proposed(self):
        original = self.agent.decide
        def invalid(facts, messages, previous_results=None):
            result = original(facts, messages, previous_results)
            if previous_results:
                result.venue_id = "made-up"
            return result
        self.agent.decide = invalid
        self.service.tick(NOW)
        self.assertIsNone(self.store.get_plan("chat1").pending_proposal_id)
        self.assertIn("another preference", self.sent[-1][1])

    def test_followup_after_completed_plan_does_not_reopen_it(self):
        self.service.tick(NOW)
        self.service.receive(ChatMessage("m20", "chat1", "nick", "Book it", NOW))
        completed_id = self.store.get_plan("chat1").id
        self.service.receive(ChatMessage("m21", "chat1", "sarah", "Thanks!", NOW))
        self.assertEqual(self.store.get_plan("chat1").id, completed_id)
        self.assertEqual(self.store.get_plan("chat1").state, "DONE")

    def test_untagged_venue_is_usable_when_there_is_no_cuisine_restriction(self):
        unrestricted = PlanFacts(**{**self.facts.__dict__, "excluded_cuisines": []})
        self.store.save_plan("chat1", unrestricted, NOW - timedelta(minutes=31))
        self.service.search_fn = lambda facts: [Venue("v1", "Neighborhood Table", "3 Main St",
                                                     40.75, -73.98, ())]
        self.service.tick(NOW)
        self.assertIsNotNone(self.store.get_plan("chat1").pending_proposal_id)

    def test_changed_terms_cancel_failed_old_proposal_delivery(self):
        self.service.send_fn = lambda chat, text: (_ for _ in ()).throw(RuntimeError("offline"))
        self.service.tick(NOW)
        old_id = self.store.get_plan("chat1").pending_proposal_id
        self.agent.facts = PlanFacts(**{**self.facts.__dict__, "time": "21:00"})
        self.service.receive(ChatMessage("change-queued", "chat1", "sarah", "Make it 9", NOW))
        self.sent.clear()
        self.service.send_fn = lambda chat, text: self.sent.append((chat, text))
        self.service.deliver_pending()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.get_proposal(old_id).status, "stale")

    def test_delayed_old_approval_cannot_approve_new_proposal(self):
        self.service.tick(NOW)
        self.service.receive(ChatMessage("old-approval", "chat1", "nick", "Book it",
                                         NOW - timedelta(days=7)))
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.assertIsNone(self.store.reservation(proposal_id))

    def test_unprocessed_change_blocks_approval(self):
        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        original = self.agent.extract
        self.agent.extract = lambda messages, previous: (_ for _ in ()).throw(RuntimeError("offline"))
        with self.assertRaises(RuntimeError):
            self.service.receive(ChatMessage("change-before-approval", "chat1", "sarah",
                                             "Make it Saturday instead", NOW + timedelta(minutes=1)))
        self.agent.extract = original
        self.service.receive(ChatMessage("approval-after-change", "chat1", "nick",
                                         "Book it", NOW + timedelta(minutes=2)))
        self.assertIsNone(self.store.reservation(proposal_id))

    def test_scheduler_recovers_approved_action_after_restart_boundary(self):
        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.store.approve(proposal_id, "nick", "approval-stored-before-crash")
        self.service.tick(NOW + timedelta(minutes=1))
        self.assertIsNotNone(self.store.reservation(proposal_id))
        self.assertEqual(self.store.get_plan("chat1").state, "DONE")
        self.assertEqual(len(self.sent), 2)

    def test_failed_venue_selection_can_retry_next_tick(self):
        original = self.agent.decide
        attempts = [0]
        def flaky(facts, messages, previous_results=None):
            if previous_results and attempts[0] == 0:
                attempts[0] += 1
                raise RuntimeError("Grok temporarily unavailable")
            return original(facts, messages, previous_results)
        self.agent.decide = flaky
        self.assertEqual(self.service.tick(NOW), 0)
        self.service.tick(NOW + timedelta(minutes=1))
        self.assertIsNotNone(self.store.get_plan("chat1").pending_proposal_id)

    def test_scheduler_provider_failure_does_not_starve_second_plan(self):
        second_facts = PlanFacts(**{**self.facts.__dict__, 'goal': 'Other dinner'})
        self.store.save_plan('chat2', second_facts, NOW - timedelta(minutes=31))
        original = self.agent.decide
        def selective(facts, messages, previous_results=None):
            if facts.goal == self.facts.goal:
                raise GrokProviderError('timeout', 'agentdecision')
            return original(facts, messages, previous_results)
        self.agent.decide = selective
        with self.assertLogs('app.orchestrator', level='WARNING') as logs:
            self.assertEqual(self.service.tick(NOW), 1)
        self.assertIsNone(self.store.get_plan('chat1').pending_proposal_id)
        self.assertIsNotNone(self.store.get_plan('chat2').pending_proposal_id)
        self.assertEqual([chat for chat, _ in self.sent], ['chat2'])
        self.assertIn('timeout', logs.output[0])
        self.assertNotIn('chat1', logs.output[0])
        self.assertNotIn(self.facts.goal, logs.output[0])

    def test_scheduler_approval_recovery_failure_does_not_starve_second_plan(self):
        self.service.tick(NOW)
        proposal_id = self.store.get_plan('chat1').pending_proposal_id
        self.store.approve(proposal_id, 'nick', 'stored-approval')
        self.store.save_plan('chat2', self.facts, NOW - timedelta(minutes=31))
        def unavailable_book(*args):
            raise RuntimeError('secret conversation and key')
        self.service._book = unavailable_book
        with self.assertLogs('app.orchestrator', level='WARNING') as logs:
            self.assertEqual(self.service.tick(NOW + timedelta(minutes=1)), 1)
        self.assertIsNotNone(self.store.get_plan('chat2').pending_proposal_id)
        self.assertNotIn('secret', ''.join(logs.output))
        self.assertIsNone(self.store.reservation(proposal_id))

    def test_ask_names_actual_conflict_when_date_and_city_are_known(self):
        conflicted = PlanFacts(**{**self.facts.__dict__, "blockers": ["conflicting availability"]})
        self.store.save_plan("chat1", conflicted, NOW - timedelta(minutes=31))
        self.agent.decide = lambda facts, messages, previous_results=None: AgentDecision(
            action="ASK", reason="conflicting availability", tool=None, confidence=0.9)
        self.service.tick(NOW)
        self.assertIn("availability", self.sent[-1][1].lower())
        self.assertNotIn("what the date", self.sent[-1][1].lower())

    def test_explicit_time_must_respect_after_constraint(self):
        early = PlanFacts(**{**self.facts.__dict__, "time": "19:00"})
        self.store.save_plan("chat1", early, NOW - timedelta(minutes=31))
        self.service.tick(NOW)
        self.assertIsNone(self.store.get_plan("chat1").pending_proposal_id)
        self.assertIn("time", self.sent[-1][1].lower())

    def test_proposal_expires_without_deleting_plan_history(self):
        self.service.tick(NOW)
        proposal_id = self.store.get_plan("chat1").pending_proposal_id
        self.service.receive(ChatMessage("late-approval", "chat1", "nick", "Book it",
                                         NOW + timedelta(hours=25)))
        self.assertIsNone(self.store.reservation(proposal_id))
        self.assertEqual(self.store.get_proposal(proposal_id).status, "stale")
        self.assertIsNone(self.store.get_plan("chat1").pending_proposal_id)

    def test_explicit_plan_cancel_updates_state_and_publishes_without_extraction(self):
        published = []
        self.service.portal_publish_fn = lambda: published.append("published")
        self.agent.extract = lambda *_args: self.fail("explicit cancel must not wait for extraction")

        self.assertTrue(self.service.receive(
            ChatMessage("cancel-now", "chat1", "nick", "Rally, cancel the plan", NOW)))

        plan = self.store.get_plan("chat1")
        self.assertEqual(plan.state, "ABANDONED")
        self.assertTrue(plan.facts.abandoned)
        self.assertEqual(published, ["published"])
        self.assertTrue(any("canceled the active plan" in text.lower() for _, text in self.sent))

    def test_deferred_plan_extraction_batches_quick_messages_per_chat(self):
        extracted = []

        class BatchingAgent(FakeAgent):
            def extract(self, messages, previous):
                extracted.append([message.message_id for message in messages])
                return PlanFacts()

        service = RallyService(self.store, BatchingAgent(self.facts), lambda _: [],
                               lambda *_args: None, defer_heavy_work=True)
        first = ChatMessage("batch-1", "batch-chat", "nick", "first message", NOW)
        second = ChatMessage("batch-2", "batch-chat", "sarah", "second message", NOW)
        self.assertTrue(service.receive(first))
        self.assertTrue(service.receive(second))

        deadline = time.monotonic() + 3
        while not (self.store.is_processed(first.message_id) and self.store.is_processed(second.message_id)) and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(self.store.is_processed(first.message_id))
        self.assertTrue(self.store.is_processed(second.message_id))
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0][-2:], ["batch-1", "batch-2"])


if __name__ == "__main__":
    unittest.main()


def test_web_answer_uses_read_only_search_and_survives_provider_failure(tmp_path):
    from app.agent import GrokProviderError
    from app.models import ChatMessage
    from app.orchestrator import RallyService
    from app.store import Store
    store = Store(tmp_path / 'state.sqlite3')
    called = []
    sent = []
    class Agent:
        def answer_direct(self, *args):
            raise AssertionError('web answer must bypass ordinary model')
        def extract(self, *args):
            raise AssertionError('web answer must not trigger plan extraction')
    def failing_web(request, *, tone):
        called.append(request)
        raise GrokProviderError('timeout', 'webanswer')
    service = RallyService(store, Agent(), lambda _: [], lambda chat,text: sent.append(text),
                           web_answer_fn=failing_web)
    message = ChatMessage('m-web', 'iMessage;+;group', 'friend',
                          'Rally, find dinner nearby', NOW)
    assert service.receive(message)
    assert called == [message.text]
    assert len(sent) == 1 and 'web search' in sent[0].lower()
    assert store.is_processed('m-web')
    assert not service.receive(message)
    assert len(sent) == 1


def test_web_answer_is_sent_once_without_following_extraction(tmp_path):
    from app.models import ChatMessage
    from app.orchestrator import RallyService
    from app.store import Store
    store=Store(tmp_path/'state.sqlite3')
    searched=[]; sent=[]
    class Agent:
        def extract(self, *args):
            raise AssertionError('web reply must not run plan extraction')
        def answer_direct(self, *args):
            raise AssertionError('web reply must use search')
    service=RallyService(store,Agent(),lambda _:[],lambda chat,text:sent.append((chat,text)),
                         web_answer_fn=lambda request,*,tone: searched.append((request,tone)) or 'Two public options: https://example.com')
    message=ChatMessage('web-success','iMessage;+;group','friend','Rally find food nearby',NOW)
    assert service.receive(message)
    assert searched==[(message.text,'neutral')]
    assert sent==[(message.chat_id,'Two public options: https://example.com')]
    assert store.is_processed(message.message_id)
    assert not service.receive(message)
    assert len(sent)==1
