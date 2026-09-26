import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import PlanFacts
from app.orchestrator import RallyService
from app.portal_store import PortalStore
from app.store import Store


CHAT = "iMessage;+;portal-test"
NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


class Agent:
    def extract(self, messages, previous):
        return PlanFacts()

    def answer_direct(self, request, facts, messages):
        return "I can help with that plan."

    def _call(self, schema, prompt, data):
        first = data["messages"][0]
        return {"findings": [{"title": "Old dinner", "summary": "A dinner was suggested.",
                              "evidence_ids": [first["id"]]}]}


class PortalHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "rally.sqlite3"
        self.store = Store(path)
        self.portal = PortalStore(path)
        self.sent = []
        self.service = RallyService(self.store, Agent(), lambda facts: [],
                                    lambda chat, body: self.sent.append((chat, body)),
                                    allowed_chat_ids={CHAT})
        self.client = TestClient(create_app(self.service, portal_store=self.portal,
                                            app_url="https://rallyplans.vercel.app",
                                            webhook_token="secret", schedule=False))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def webhook(self, message_id, text):
        return self.client.post("/webhooks/bluebubbles?token=secret", json={"type": "new-message",
            "data": {"guid": message_id, "text": text, "isFromMe": False,
                     "dateCreated": int(NOW.timestamp() * 1000),
                     "handle": {"address": "member"}, "chats": [{"guid": CHAT}]}})

    def test_link_and_group_settings_stay_in_original_chat(self):
        self.assertEqual(self.webhook("m1", "Hey Rally, send our page link").status_code, 200)
        public_id = self.portal.ensure_group(CHAT)
        self.assertEqual(self.sent, [(CHAT, f"Rally: Our group page: https://rallyplans.vercel.app/{public_id}")])
        page = self.client.get(f"/{public_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Conversation history", page.text)
        self.assertIn("send our page link", page.text)
        self.assertIn("Rally activity", page.text)
        self.assertIn("direct_reply", page.text)
        self.assertEqual(self.webhook("m2", "Hey Rally, hide media on our page").status_code, 200)
        self.assertFalse(self.portal.group_for_chat(CHAT)["sections"]["media"])
        self.assertEqual(self.webhook("m3", "Hey Rally, show media").status_code, 200)
        self.assertTrue(self.portal.group_for_chat(CHAT)["sections"]["media"])
        self.assertEqual(self.webhook("m4", "Hey Rally, set our page theme to midnight").status_code, 200)
        self.assertIn('class="midnight"', self.client.get(f"/{public_id}").text)
        self.assertEqual(self.client.get("/unknown-group").status_code, 404)

    def test_historical_search_is_separate_from_rally_plan_records(self):
        public_id = self.portal.ensure_group(CHAT)
        self.portal.upsert_messages(CHAT, [{"message_id": "old-1", "sender_id": "member",
            "text": "Dinner next Friday?", "sent_at": NOW.isoformat()}])
        page = self.client.get(f"/{public_id}", params={"old_plan_query": "dinner"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("Possible plan", page.text)
        self.assertIn("Dinner next Friday?", page.text)
        self.assertIn("Rally has not tracked a plan", page.text)

    def test_admin_updates_require_token_and_media_respects_visibility(self):
        public_id = self.portal.ensure_group(CHAT)
        self.assertEqual(self.client.post(f"/portal/admin/{CHAT}/settings",
                                          json={"sections": {"media": False}}).status_code, 403)
        self.assertEqual(self.client.post(f"/portal/admin/{CHAT}/settings?token=secret",
                                          json={"sections": {"media": False}}).status_code, 200)
        self.assertEqual(self.client.get(f"/{public_id}/media/a1").status_code, 404)


if __name__ == "__main__":
    unittest.main()
