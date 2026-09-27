import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import ChatMessage, PlanFacts
from app.policy import (eligible_for_intervention, eligible_for_revival,
                        plan_state, unfinished_plan, valid_approval,
                        valid_calendar_approval)
from app.store import Store


NOW = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "rally.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_message_deduplication_and_persistence(self):
        message = ChatMessage("m1", "chat1", "nick", "Dinner Friday?", NOW)
        self.assertTrue(self.store.add_message(message))
        self.assertFalse(self.store.add_message(message))
        self.assertEqual(len(Store(self.store.path).recent_messages("chat1")), 1)
        self.assertEqual(Store(self.store.path).recent_messages("chat2"), [])

    def test_unfinished_plan_revival_allows_stall_after_recent_rally(self):
        facts = PlanFacts(activity="eat out", date="2026-09-26", location="Midtown")
        plan = self.store.save_plan("chat1", facts, NOW - timedelta(minutes=20))
        self.assertTrue(unfinished_plan(plan))
        recent_rally = NOW - timedelta(minutes=6)
        self.assertTrue(eligible_for_revival(
            plan, NOW, last_rally_at=recent_rally, incoming_stall=True))
        self.assertFalse(eligible_for_revival(
            plan, NOW, last_rally_at=recent_rally, incoming_stall=False))
        self.store.mark_intervened(plan.id, plan.version, NOW)
        self.assertFalse(eligible_for_revival(
            self.store.get_plan("chat1"), NOW, incoming_stall=True))

    def test_blocked_plan_waits_for_stall_and_nudges_once(self):
        facts = PlanFacts(goal="Friday dinner", activity="dinner", participants=["nick", "sarah"],
                          date="2026-09-25", location="Midtown", blockers=["venue missing"])
        plan = self.store.save_plan("chat1", facts, NOW - timedelta(minutes=31))
        self.assertEqual(plan_state(facts, False), "BLOCKED")
        self.assertTrue(eligible_for_intervention(plan, NOW, 30))
        self.store.mark_intervened(plan.id, plan.version, NOW)
        self.assertFalse(eligible_for_intervention(self.store.get_plan("chat1"), NOW, 30))

    def test_interest_is_not_approval(self):
        self.assertFalse(valid_approval("I'm down"))
        self.assertTrue(valid_approval("Book it."))
        self.assertFalse(valid_calendar_approval("Book it."))
        self.assertTrue(valid_approval("Book it and add a calendar event."))
        self.assertTrue(valid_calendar_approval("Book it and add a calendar event."))

    def test_unrelated_message_does_not_reset_stall_clock(self):
        facts = PlanFacts(activity="dinner", participants=["nick", "sarah"], blockers=["venue missing"])
        old = self.store.save_plan("chat1", facts, NOW - timedelta(minutes=31))
        new = self.store.save_plan("chat1", facts, NOW)
        self.assertEqual(new.last_human_at, old.last_human_at)

    def test_completed_plan_remains_when_new_one_starts(self):
        first = self.store.save_plan("chat1", PlanFacts(activity="dinner", goal="Friday dinner"), NOW)
        self.store.set_state(first.id, "DONE")
        second = self.store.save_plan("chat1", PlanFacts(activity="hike", goal="Sunday hike"), NOW)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(self.store.get_plan_by_id(first.id).state, "DONE")

    def test_free_provider_request_cap_persists(self):
        day = "2026-09-25"
        self.assertTrue(self.store.consume_quota(day, 2))
        self.assertTrue(Store(self.store.path).consume_quota(day, 2))
        self.assertFalse(self.store.consume_quota(day, 2))
        self.assertTrue(self.store.consume_quota("2026-09-26", 2))

    def test_calendar_approval_result_and_quota_survive_restart(self):
        self.assertTrue(self.store.approve("proposal-1", "nick", "message-1", includes_calendar=True))
        self.assertEqual(Store(self.store.path).approval("proposal-1")["includes_calendar"], 1)
        self.store.save_calendar_result("proposal-1", "confirmed", "event-1", None)
        result = Store(self.store.path).calendar_result("proposal-1")
        self.assertEqual(result["event_id"], "event-1")
        self.assertTrue(self.store.consume_calendar_quota("2026-09-25", 1))
        self.assertFalse(Store(self.store.path).consume_calendar_quota("2026-09-25", 1))


if __name__ == "__main__":
    unittest.main()
