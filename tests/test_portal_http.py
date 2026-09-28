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
        self.assertEqual(self.sent[0][0], CHAT)
        self.assertIn(f"https://rallyplans.vercel.app/{public_id}", self.sent[0][1])
        self.assertIn("page", self.sent[0][1].lower())
        page = self.client.get(f"/{public_id}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("Rally activity", page.text)
        self.assertNotIn("direct_reply", page.text)
        self.assertIn("Total messages", page.text)
        self.assertEqual(self.webhook("m2", "Hey Rally, hide media on our page").status_code, 200)
        self.assertFalse(self.portal.group_for_chat(CHAT)["sections"]["media"])
        self.assertEqual(self.webhook("m3", "Hey Rally, show media").status_code, 200)
        self.assertTrue(self.portal.group_for_chat(CHAT)["sections"]["media"])
        self.assertEqual(self.client.get("/unknown-group").status_code, 404)

    def test_historical_search_param_does_not_break_the_page(self):
        public_id = self.portal.ensure_group(CHAT)
        self.portal.upsert_messages(CHAT, [{"message_id": "old-1", "sender_id": "member",
            "text": "Dinner next Friday?", "sent_at": NOW.isoformat()}])
        page = self.client.get(f"/{public_id}", params={"old_plan_query": "dinner"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("No plan yet", page.text)

    def test_admin_updates_require_token_and_media_respects_visibility(self):
        public_id = self.portal.ensure_group(CHAT)
        self.assertEqual(self.client.post(f"/portal/admin/{CHAT}/settings",
                                          json={"sections": {"media": False}}).status_code, 403)
        self.assertEqual(self.client.post(f"/portal/admin/{CHAT}/settings?token=secret",
                                          json={"sections": {"media": False}}).status_code, 200)
        self.assertEqual(self.client.get(f"/{public_id}/media/a1").status_code, 404)


def test_restaurant_or_browser_return_still_archives_the_group_message(tmp_path):
    path = tmp_path / "rally.sqlite3"
    store = Store(path)
    portal = PortalStore(path)
    service = RallyService(store, Agent(), lambda facts: [], lambda chat, body: None,
                           allowed_chat_ids={CHAT})

    class Swallow:
        def try_receive(self, _payload):
            return True

    client = TestClient(create_app(
        service, webhook_token="secret", schedule=False, portal_store=portal,
        browser_inbound=Swallow()))
    payload = {"type": "new-message", "data": {
        "guid": "book-1", "text": "hello from the group", "isFromMe": False,
        "dateCreated": int(NOW.timestamp() * 1000),
        "handle": {"address": "member"}, "chats": [{"guid": CHAT}, {"guid": CHAT}]}}
    assert client.post("/webhooks/bluebubbles?token=secret", json=payload).status_code == 200
    assert client.post("/webhooks/bluebubbles?token=secret", json=payload).status_code == 200
    stored = portal.list_messages(CHAT)
    assert [item["message_id"] for item in stored] == ["book-1"]
    assert stored[0]["text"] == "hello from the group"
    client.close()


def test_direct_chat_is_excluded_from_live_portal_routes(tmp_path):
    direct = "iMessage;-;owner"
    path = tmp_path / "rally.sqlite3"
    store = Store(path)
    portal = PortalStore(path)
    service = RallyService(store, Agent(), lambda facts: [], lambda chat, body: None,
                           allowed_chat_ids={CHAT, direct})
    client = TestClient(create_app(
        service, webhook_token="secret", schedule=False, portal_store=portal))
    direct_id = portal.ensure_group(direct)
    portal.upsert_messages(direct, [{"message_id": "dm", "sender_id": "owner",
                                    "text": "direct only secret", "sent_at": NOW.isoformat()}])
    assert client.get(f"/{direct_id}").status_code == 404
    assert client.get(f"/{direct_id}", params={"before": "2026-09-01"}).status_code == 404
    assert client.get(f"/{direct_id}/media/a1").status_code == 404
    assert client.post(f"/portal/admin/{direct}/import?token=secret").status_code == 404
    group_id = portal.ensure_group(CHAT)
    assert client.get(f"/{group_id}").status_code == 200
    payload = {"type": "new-message", "data": {
        "guid": "dm-live", "text": "direct only secret", "isFromMe": False,
        "dateCreated": int(NOW.timestamp() * 1000),
        "handle": {"address": "owner"}, "chats": [{"guid": direct}]}}
    assert client.post("/webhooks/bluebubbles?token=secret", json=payload).status_code == 200
    assert portal.list_messages(direct, limit=20)[0]["message_id"] == "dm"
    client.close()


if __name__ == "__main__":
    unittest.main()
