import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import PlanFacts
from app.orchestrator import RallyService
from app.relationships.store import RelationshipStore
from app.store import Store
from app.voice.store import VoiceActionStore
from app.voice.tools import VoiceToolRegistry, build_voice_tools

OWNER = "local-imessage-account"
CHAT = "iMessage;+;chat1"
NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)


class VoiceTestBase(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mktemp(suffix=".sqlite3"))
        self.store = Store(self.path)
        self.sent = []
        self.evaluated = []
        self.service = RallyService(self.store, agent=None, search_fn=lambda f: [],
                                    send_fn=lambda chat, text: self.sent.append((chat, text)),
                                    stall_minutes=30, allowed_chat_ids={CHAT})
        self.service.evaluate = lambda chat_id, now=None: self.evaluated.append(chat_id) or False
        self.rel_store = RelationshipStore(self.path)
        self.actions = VoiceActionStore(self.path)
        self.registry = build_voice_tools(OWNER, relationship_store=self.rel_store,
                                          plan_store=self.store, service=self.service,
                                          action_store=self.actions)

    def tearDown(self):
        if self.path.exists():
            self.path.unlink()


class ToolSchemaTests(unittest.TestCase):
    def test_duplicate_tool_name_rejected(self):
        from app.voice.tools import VoiceTool
        registry = VoiceToolRegistry()
        spec = VoiceTool("x", "d", {"type": "object", "properties": {}, "required": []},
                         "read", lambda args: {})
        registry.register(spec)
        with self.assertRaises(ValueError):
            registry.register(spec)

    def test_unknown_tool_call_raises(self):
        registry = VoiceToolRegistry()
        with self.assertRaises(ValueError):
            registry.call("nope", {})

    def test_missing_required_argument_rejected(self):
        from app.voice.tools import VoiceTool
        registry = VoiceToolRegistry()
        registry.register(VoiceTool(
            "needs_label", "d", {"type": "object", "properties": {"label": {"type": "string"}},
                                 "required": ["label"]}, "read", lambda args: args))
        with self.assertRaises(ValueError):
            registry.call("needs_label", {})

    def test_wrong_argument_type_rejected(self):
        from app.voice.tools import VoiceTool
        registry = VoiceToolRegistry()
        registry.register(VoiceTool(
            "needs_days", "d", {"type": "object", "properties": {"days": {"type": "integer"}},
                                "required": ["days"]}, "read", lambda args: args))
        with self.assertRaises(ValueError):
            registry.call("needs_days", {"days": "seven"})
        with self.assertRaises(ValueError):
            registry.call("needs_days", {"days": True})  # bool is not an int here


class ListAttentionTests(VoiceTestBase):
    def test_empty_state_reports_no_overdue_and_labels_followups_as_stubbed(self):
        result = self.registry.call("list_attention", {})
        self.assertEqual(result["overdue_relationships"], [])
        self.assertEqual(result["stalled_plans"], [])
        self.assertEqual(result["unfinished_followups"], [])
        self.assertIn("not implemented", result["unfinished_followups_note"])

    def test_overdue_relationship_and_stalled_plan_both_surface(self):
        self.rel_store.configure(OWNER, "iMessage;-;+15555550123", "America/New_York", 18)
        self.rel_store.upsert(OWNER, "Mom", "call", 3, NOW - timedelta(days=10))
        self.store.save_plan(CHAT, PlanFacts(goal="dinner", activity="dinner",
                                             participants=["a", "b"],
                                             blockers=["no venue chosen"]), NOW)
        result = self.registry.call("list_attention", {})
        self.assertEqual(result["overdue_relationships"],
                         [{"label": "Mom", "mode": "call", "category": None, "target_days": 3,
                           "days_since_contact": None}])
        self.assertEqual(len(result["stalled_plans"]), 1)
        self.assertEqual(result["stalled_plans"][0]["chat_id"], CHAT)

    def test_plan_outside_allowlist_is_excluded(self):
        self.store.save_plan("iMessage;+;other", PlanFacts(goal="x", activity="x",
                                                            participants=["a", "b"],
                                                            blockers=["b"]), NOW)
        result = self.registry.call("list_attention", {})
        self.assertEqual(result["stalled_plans"], [])


class SetIntentionTests(VoiceTestBase):
    def test_requires_reminder_destination_configured_first(self):
        result = self.registry.call("set_intention",
                                    {"label": "Mom", "mode": "call", "days": 7})
        self.assertFalse(result["ok"])
        self.assertIn("not configured", result["reason"])

    def test_creates_relationship_once_configured(self):
        self.rel_store.configure(OWNER, "iMessage;-;+15555550123", "America/New_York", 18)
        result = self.registry.call("set_intention",
                                    {"label": "Mom", "mode": "call", "days": 7})
        self.assertTrue(result["ok"])
        self.assertEqual(self.rel_store.list_relationships(OWNER)[0]["label"], "Mom")

    def test_invalid_mode_rejected_before_touching_store(self):
        self.rel_store.configure(OWNER, "iMessage;-;+15555550123", "America/New_York", 18)
        result = self.registry.call("set_intention",
                                    {"label": "Mom", "mode": "carrier-pigeon", "days": 7})
        self.assertFalse(result["ok"])

    def test_set_intention_with_category(self):
        self.rel_store.configure(OWNER, "iMessage;-;+15555550123", "America/New_York", 18)
        result = self.registry.call("set_intention",
                                    {"label": "Mom", "mode": "call", "days": 7,
                                     "category": "parent"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.rel_store.list_relationships(OWNER)[0]["category"], "parent")

    def test_set_intention_rejects_invalid_category(self):
        self.rel_store.configure(OWNER, "iMessage;-;+15555550123", "America/New_York", 18)
        result = self.registry.call("set_intention",
                                    {"label": "Mom", "mode": "call", "days": 7,
                                     "category": "not-a-category"})
        self.assertFalse(result["ok"])

    def test_set_category_on_existing_relationship(self):
        self.rel_store.configure(OWNER, "iMessage;-;+15555550123", "America/New_York", 18)
        self.registry.call("set_intention", {"label": "Mom", "mode": "call", "days": 7})
        result = self.registry.call("set_category", {"label": "Mom", "category": "parent"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.rel_store.list_relationships(OWNER)[0]["category"], "parent")

    def test_set_category_unknown_person(self):
        self.rel_store.configure(OWNER, "iMessage;-;+15555550123", "America/New_York", 18)
        result = self.registry.call("set_category", {"label": "Nobody", "category": "parent"})
        self.assertFalse(result["ok"])


class LinkedConversationTests(VoiceTestBase):
    def setUp(self):
        super().setUp()
        self.rel_store.configure(OWNER, "iMessage;-;+15555550123", "America/New_York", 18)
        self.rel_store.upsert(OWNER, "Jake", "message", 14, NOW)

    def test_check_plan_status_without_source_reports_unlinked(self):
        result = self.registry.call("check_plan_status", {"label": "Jake"})
        self.assertFalse(result["linked"])

    def test_check_plan_status_with_source_reads_real_plan(self):
        self.rel_store.add_source(OWNER, CHAT, "Jake")
        self.store.save_plan(CHAT, PlanFacts(goal="dinner", activity="dinner",
                                             participants=["a", "b"],
                                             blockers=["no venue chosen"]), NOW)
        result = self.registry.call("check_plan_status", {"label": "Jake"})
        self.assertTrue(result["linked"])
        self.assertEqual(result["status"], "BLOCKED")

    def test_propose_message_without_source_does_not_create_action(self):
        result = self.registry.call("propose_message", {"label": "Jake", "text": "hi"})
        self.assertFalse(result["ok"])

    def test_propose_then_confirm_sends_exactly_once(self):
        self.rel_store.add_source(OWNER, CHAT, "Jake")
        draft = self.registry.call("propose_message",
                                   {"label": "Jake", "text": "Dinner Thursday?"})
        self.assertTrue(draft["ok"])
        self.assertEqual(self.sent, [])
        first = self.registry.call("confirm_action", {"action_id": draft["pending_action_id"]})
        self.assertEqual(first, {"ok": True, "sent": True, "chat_id": CHAT})
        self.assertEqual(self.sent, [(CHAT, "Dinner Thursday?")])
        second = self.registry.call("confirm_action", {"action_id": draft["pending_action_id"]})
        self.assertFalse(second["ok"])
        self.assertEqual(self.sent, [(CHAT, "Dinner Thursday?")])

    def test_confirm_unknown_action_id_is_rejected(self):
        result = self.registry.call("confirm_action", {"action_id": "does-not-exist"})
        self.assertFalse(result["ok"])

    def test_nudge_then_confirm_calls_service_evaluate_once(self):
        self.rel_store.add_source(OWNER, CHAT, "Jake")
        draft = self.registry.call("nudge_plan", {"label": "Jake"})
        self.assertTrue(draft["ok"])
        self.assertEqual(self.evaluated, [])
        self.registry.call("confirm_action", {"action_id": draft["pending_action_id"]})
        self.assertEqual(self.evaluated, [CHAT])
        self.registry.call("confirm_action", {"action_id": draft["pending_action_id"]})
        self.assertEqual(self.evaluated, [CHAT])  # second confirm is a no-op, not a replay


class FakeBlueBubblesClient:
    def __init__(self, chats):
        self._chats = chats

    def fetch_chats(self, limit=50):
        return self._chats


class GroupChatToolsTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mktemp(suffix=".sqlite3"))
        self.store = Store(self.path)
        self.sent = []
        self.evaluated = []
        self.service = RallyService(self.store, agent=None, search_fn=lambda f: [],
                                    send_fn=lambda chat, text: self.sent.append((chat, text)),
                                    stall_minutes=30, allowed_chat_ids={CHAT})
        self.service.evaluate = lambda chat_id, now=None: self.evaluated.append(chat_id) or False
        self.rel_store = RelationshipStore(self.path)
        self.actions = VoiceActionStore(self.path)
        self.bluebubbles = FakeBlueBubblesClient([
            {"guid": CHAT, "displayName": "JSMP"},
            {"guid": "iMessage;+;other", "displayName": "Not Allowed"},
        ])
        self.registry = build_voice_tools(OWNER, relationship_store=self.rel_store,
                                          plan_store=self.store, service=self.service,
                                          action_store=self.actions,
                                          bluebubbles_client=self.bluebubbles)

    def tearDown(self):
        if self.path.exists():
            self.path.unlink()

    def test_list_group_chats_filters_to_allowed(self):
        result = self.registry.call("list_group_chats", {})
        self.assertEqual(result["chats"], [{"name": "JSMP"}])

    def test_list_group_chats_without_client_reports_none(self):
        registry = build_voice_tools(OWNER, relationship_store=self.rel_store,
                                     plan_store=self.store, service=self.service,
                                     action_store=self.actions)
        result = registry.call("list_group_chats", {})
        self.assertEqual(result["chats"], [])
        self.assertIn("no group chats", result["note"].lower())

    def test_get_chat_status_resolves_by_name(self):
        self.store.save_plan(CHAT, PlanFacts(goal="dinner", activity="dinner",
                                             participants=["a", "b"],
                                             blockers=["no venue chosen"]), NOW)
        result = self.registry.call("get_chat_status", {"chat_name": "jsmp"})
        self.assertTrue(result["linked"])
        self.assertEqual(result["status"], "BLOCKED")

    def test_get_chat_status_unknown_name_does_not_guess(self):
        result = self.registry.call("get_chat_status", {"chat_name": "Some Other Group"})
        self.assertFalse(result["linked"])

    def test_propose_message_to_chat_then_confirm_sends_once(self):
        draft = self.registry.call("propose_message_to_chat",
                                   {"chat_name": "JSMP", "text": "Dinner Thursday?"})
        self.assertTrue(draft["ok"])
        self.assertEqual(self.sent, [])
        self.registry.call("confirm_action", {"action_id": draft["pending_action_id"]})
        self.assertEqual(self.sent, [(CHAT, "Dinner Thursday?")])

    def test_propose_message_to_chat_rejects_unallowed_name(self):
        result = self.registry.call("propose_message_to_chat",
                                    {"chat_name": "Not Allowed", "text": "hi"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.sent, [])

    def test_nudge_chat_then_confirm_calls_evaluate_once(self):
        draft = self.registry.call("nudge_chat", {"chat_name": "JSMP"})
        self.assertTrue(draft["ok"])
        self.registry.call("confirm_action", {"action_id": draft["pending_action_id"]})
        self.assertEqual(self.evaluated, [CHAT])


class StubbedCapabilityTests(VoiceTestBase):
    def test_find_hangout_slot_reports_unavailable_rather_than_inventing_a_time(self):
        result = self.registry.call("find_hangout_slot", {"label": "Jake"})
        self.assertFalse(result["available"])
        self.assertIn("not connected", result["note"])


if __name__ == "__main__":
    unittest.main()
