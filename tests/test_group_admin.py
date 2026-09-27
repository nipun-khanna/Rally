from datetime import datetime, timedelta, timezone

from app.group_admin import build_group_admin, list_admin_groups
from app.group_admin_view import render_group_admin, render_group_picker
from app.group_memory import GroupMemoryStore
from app.group_turns import GroupTurnStore
from app.models import ChatMessage, PlanFacts, Proposal, Reservation
from app.orchestrator import RallyService
from app.portal_store import PortalStore
from app.store import Store


NOW = datetime(2026, 9, 26, 21, 30, tzinfo=timezone.utc)
GROUP = "iMessage;+;hackgt13"
OTHER = "iMessage;+;other-crew"
PRIVATE = "iMessage;-;mom"


class QuietAgent:
    def extract(self, messages, previous):
        return PlanFacts()


def service(path, chats=(GROUP,)):
    store = Store(path)
    memory = GroupMemoryStore(path)
    turns = GroupTurnStore(path)
    return RallyService(
        store, QuietAgent(), lambda facts: [], lambda chat, text: None,
        allowed_chat_ids=set(chats), group_memory=memory, group_turns=turns,
        react_fn=lambda *args: None,
    )


def test_picker_lists_only_allowlisted_groups_and_skips_private_chats(tmp_path):
    path = tmp_path / "rally.sqlite3"
    rally = service(path, chats=(GROUP, OTHER, PRIVATE))
    portal = PortalStore(path)
    portal.ensure_group(GROUP)
    portal.update_settings(GROUP, title="HackGT13")
    rally.store.add_message(ChatMessage("priv", PRIVATE, "mom", "call me about the wedding", NOW))
    groups = list_admin_groups(rally, portal, excluded_chat_ids={PRIVATE})
    ids = [item["chat_id"] for item in groups]
    assert ids == [GROUP, OTHER] or set(ids) == {GROUP, OTHER}
    assert PRIVATE not in ids
    titles = {item["chat_id"]: item["title"] for item in groups}
    assert titles[GROUP] == "HackGT13"
    assert "call me about the wedding" not in str(groups)


def test_detail_assembles_group_operations_without_other_chats_or_secrets(tmp_path):
    path = tmp_path / "rally.sqlite3"
    rally = service(path)
    portal = PortalStore(path)
    portal.ensure_group(GROUP)
    portal.update_settings(GROUP, title="HackGT13", theme="midnight")
    rally.store.add_message(ChatMessage("m1", GROUP, "nick", "Dinner Friday?", NOW - timedelta(minutes=8)))
    rally.store.add_message(ChatMessage("m2", GROUP, "sarah", "Rally, book the Italian place", NOW - timedelta(minutes=2)))
    rally.store.add_message(ChatMessage("r1", GROUP, "rally", "Rally: booked the table.", NOW - timedelta(minutes=1), True))
    rally.store.add_message(ChatMessage("leak", OTHER, "alex", "SECRET OTHER GROUP", NOW))
    rally.store.add_message(ChatMessage("dm", PRIVATE, "mom", "private relationship note", NOW))
    rally.store.record_processing_failure("m1", kind="timeout", stage="extract", status_code=408)
    plan = rally.store.save_plan(GROUP, PlanFacts(
        goal="Friday dinner", activity="dinner", participants=["nick", "sarah"],
        date="2026-10-02", time="20:00", location="Midtown", confidence=0.8,
    ), NOW)
    proposal = Proposal("p1", plan.id, plan.version, "v1", "An Italian Table",
                        "123 Main", "2026-10-02", "20:00", 2, created_at=NOW.isoformat())
    rally.store.save_proposal(proposal)
    rally.store.approve("p1", "sarah", "m2", includes_calendar=True)
    rally.store.save_reservation(Reservation("p1", "RLY-9", "confirmed"))
    rally.store.queue_message(GROUP, "Rally: booked the table.", "direct_reply", "m2")
    rally.group_memory.upsert_fact(GROUP, "food.preference", "The group prefers Italian",
                                   "m1", NOW)
    rally.group_memory.upsert_fact(OTHER, "food.preference", "Other group likes tacos",
                                   "leak", NOW)
    rally.group_turns.open(GROUP, "m2", NOW - timedelta(minutes=2), "Rally, book the Italian place")
    rally.group_turns.remember_reaction("m2", "like")

    data = build_group_admin(
        rally, GROUP, portal_store=portal, excluded_chat_ids={PRIVATE},
        identity={"webhook_token": "whsec_live_token", "admin_token": "adm_live_token",
                  "bluebubbles_password": "bb-password", "xai_api_key": "xai-key"},
        now=NOW,
    )
    texts = [item["text"] for item in data["messages"]]
    assert "Dinner Friday?" in texts
    assert "SECRET OTHER GROUP" not in texts
    assert "private relationship note" not in str(data)
    assert data["plan"]["state"]
    assert data["proposal"]["venue_name"] == "An Italian Table"
    assert data["approval"]["sender_id"] == "sarah"
    assert data["memory"][0]["fact"] == "The group prefers Italian"
    assert all("tacos" not in fact["fact"] for fact in data["memory"])
    assert data["turn"]["active"] is True
    assert data["processing"]["pending"] >= 1
    assert data["outbound"]
    assert data["reactions"]["transport"] == "configured"
    assert data["identity"]["webhook_token"] == "configured"
    assert data["identity"]["admin_token"] == "configured"
    assert data["identity"]["bluebubbles_password"] == "configured"
    assert "whsec_live_token" not in str(data)
    assert "adm_live_token" not in str(data)
    assert "bb-password" not in str(data)
    assert "xai-key" not in str(data)


def test_unknown_or_private_chat_is_rejected(tmp_path):
    rally = service(tmp_path / "rally.sqlite3")
    assert build_group_admin(rally, "iMessage;+;missing", excluded_chat_ids=set()) is None
    assert build_group_admin(rally, PRIVATE, excluded_chat_ids={PRIVATE}) is None


def test_admin_html_escapes_and_shows_operational_sections():
    data = {
        "chat_id": 'iMessage;+;<img src=x>',
        "title": '<script>alert(1)</script>',
        "identity": {"allowlisted": True, "chat_id": "iMessage;+;hackgt13",
                     "portal_title": "HackGT13", "webhook_token": "configured",
                     "admin_token": "configured", "bluebubbles_password": "missing"},
        "messages": [{"message_id": "m1", "sender_id": "<b>nick</b>",
                      "text": "<img src=x onerror=alert(1)>", "sent_at": NOW.isoformat(),
                      "is_from_rally": False, "reaction": "like"}],
        "plan": {"state": "READY", "version": 2, "goal": "<svg>", "activity": "dinner",
                 "date": "2026-10-02", "time": "20:00", "location": "Midtown",
                 "participants": ["nick"], "blockers": [], "confidence": 0.7},
        "proposal": {"venue_name": "Table", "venue_address": "1 St", "status": "pending",
                     "date": "2026-10-02", "time": "20:00", "party_size": 2},
        "approval": {"sender_id": "sarah", "includes_calendar": True},
        "reservation": {"confirmation_id": "RLY-1", "status": "confirmed"},
        "memory": [{"key": "food.preference", "fact": "Prefers pasta",
                    "source_message_id": "m1", "updated_at": NOW.isoformat()}],
        "turn": {"available": True, "active": True, "opened_by_message_id": "m1",
                 "last_relevant_at": NOW.isoformat(), "closed": False,
                 "replies_in_window": 1},
        "reactions": {"transport": "configured", "recent": [{"message_id": "m1", "reaction": "like"}]},
        "processing": {"pending": 3, "failures": [{"stage": "extract", "kind": "timeout",
                                                   "status": 408, "count": 3}]},
        "outbound": [{"kind": "direct_reply", "text": "Rally: on it.", "status": "sent"}],
        "token": "adm<&",
    }
    page = render_group_admin(data)
    assert "<script>" not in page
    assert "<img src=x" not in page
    assert "&lt;script&gt;" in page
    assert "3 unprocessed" in page or "pending" in page.lower()
    for heading in ("Messages Rally sees", "Plan", "Proposal", "Group memory",
                    "Turn", "Replies", "Processing", "Identity"):
        assert heading in page
    assert 'name="viewport"' in page
    assert "prefers-reduced-motion: reduce" in page
    assert ":focus-visible" in page
    assert "adm<&" not in page
    picker = render_group_picker([{"chat_id": GROUP, "title": "HackGT13", "plan_state": "READY",
                                   "pending": 2}], token="adm<&")
    assert "HackGT13" in picker
    assert "adm<&" not in picker
    assert "/admin/groups/" in picker
