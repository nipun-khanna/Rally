import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import PlanFacts, Proposal, Reservation
from app.orchestrator import RallyService
from app.store import Store


NOW = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)
CHAT = "iMessage;+;group-one"


class QuietAgent:
    def extract(self, messages, previous):
        return PlanFacts(goal="Friday dinner", activity="dinner", participants=["nick"])

    def answer_direct(self, request, facts, messages):
        return "Friday dinner is being discussed; no venue is chosen yet."


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "rally.sqlite3")
        self.sent = []
        service = RallyService(self.store, QuietAgent(), lambda facts: [],
                               lambda chat, text: self.sent.append((chat, text)))
        self.client = TestClient(create_app(service, webhook_token="secret", demo_mode=True, schedule=False))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_health_and_authenticated_webhook(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        payload = {"type": "new-message", "data": {"guid": "m1", "text": "Dinner Friday?",
                   "isFromMe": False, "handle": {"address": "nick"},
                   "chats": [{"guid": CHAT}], "dateCreated": int(NOW.timestamp() * 1000)}}
        self.assertEqual(self.client.post("/webhooks/bluebubbles", json=payload).status_code, 403)
        first = self.client.post("/webhooks/bluebubbles?token=secret", json=payload)
        second = self.client.post("/webhooks/bluebubbles?token=secret", json=payload)
        self.assertEqual(first.json(), {"accepted": True})
        self.assertEqual(second.json(), {"accepted": False})
        self.assertEqual(len(self.store.recent_messages(CHAT)), 1)

    def test_addressed_group_webhook_sends_one_same_thread_reply(self):
        payload = {"type": "new-message", "data": {
            "guid": "direct-http", "text": "Hey Rally, what's the plan?", "isFromMe": False,
            "handle": {"address": "sarah"}, "chats": [{"guid": CHAT}],
            "dateCreated": int(NOW.timestamp() * 1000)}}
        url = "/webhooks/bluebubbles?token=secret"
        self.assertEqual(self.client.post(url, json=payload).json(), {"accepted": True})
        self.assertEqual(self.client.post(url, json=payload).json(), {"accepted": False})
        self.assertEqual(self.sent, [(CHAT, "Rally: Friday dinner is being discussed; no venue is chosen yet.")])

    def test_debug_view_requires_token_and_reads_persisted_plan(self):
        self.store.save_plan(CHAT, PlanFacts(goal="Friday dinner", activity="dinner",
            participants=["nick", "sarah"], blockers=["venue missing"], confidence=0.9),
            NOW - timedelta(minutes=31))
        self.assertEqual(self.client.get("/debug", params={"chat_id": CHAT}).status_code, 403)
        view = self.client.get("/debug", params={"chat_id": CHAT, "token": "secret"})
        self.assertEqual(view.status_code, 200)
        self.assertIn("Friday dinner", view.text)
        self.assertIn("BLOCKED", view.text)
        self.assertIn("venue missing", view.text)

    def test_debug_view_shows_proposal_and_reservation_result(self):
        plan = self.store.save_plan(CHAT, PlanFacts(goal="Friday dinner", activity="dinner",
            participants=["nick", "sarah"], date="2026-10-02", time="20:00",
            location="Midtown, New York", blockers=["venue missing"], confidence=0.9), NOW)
        proposal = Proposal("p1", plan.id, plan.version, "venue-1", "An Italian Table",
                            "123 Main St", "2026-10-02", "20:00", 2,
                            created_at=NOW.isoformat())
        self.store.save_proposal(proposal)
        ready = self.client.get("/debug", params={"chat_id": CHAT, "token": "secret"}).text
        self.assertIn("An Italian Table", ready)
        self.assertIn("Wait for approval", ready)
        self.store.save_reservation(Reservation("p1", "RLY-123", "confirmed"))
        self.store.set_state(plan.id, "DONE")
        done = self.client.get("/debug", params={"chat_id": CHAT, "token": "secret"}).text
        self.assertIn("RLY-123", done)
        self.assertIn("confirmed", done)


if __name__ == "__main__":
    unittest.main()
