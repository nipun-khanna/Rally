from datetime import datetime, timezone
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.group_memory import GroupMemoryStore
from app.group_turns import GroupTurnStore
from app.main import create_app
from app.models import ChatMessage, PlanFacts
from app.orchestrator import RallyService
from app.portal_store import PortalStore
from app.relationships.service import RelationshipService
from app.relationships.store import RelationshipStore
from app.store import Store


NOW = datetime(2026, 9, 26, 21, 30, tzinfo=timezone.utc)
GROUP = "iMessage;+;hackgt13"
PRIVATE = "iMessage;-;mom"


class QuietAgent:
    def extract(self, messages, previous):
        return PlanFacts()

    def answer_direct(self, request, facts, messages):
        return "plan is forming"


def setup(tmp_path, *, admin_token="admin-secret", webhook_token="webhook-secret"):
    path = tmp_path / "rally.sqlite3"
    store = Store(path)
    portal = PortalStore(path)
    private = RelationshipStore(path)
    private.configure("local-imessage-account", PRIVATE, "UTC", 18)
    private.upsert("local-imessage-account", "Mom", "call", 7, NOW)
    rally = RallyService(
        store, QuietAgent(), lambda facts: [], lambda chat, text: None,
        allowed_chat_ids={GROUP},
        group_memory=GroupMemoryStore(path),
        group_turns=GroupTurnStore(path),
        react_fn=lambda *args: None,
    )
    relationships = RelationshipService(private, rally.send_fn)
    app = create_app(
        rally, webhook_token=webhook_token, admin_token=admin_token,
        schedule=False, portal_store=portal, relationship_service=relationships,
        history_enabled=False,
    )
    return TestClient(app), rally, portal, private


def test_group_admin_requires_admin_token_not_webhook_token(tmp_path):
    client, rally, portal, _ = setup(tmp_path)
    portal.ensure_group(GROUP)
    rally.store.add_message(ChatMessage("m1", GROUP, "nick", "Dinner Friday?", NOW))
    assert client.get("/admin/groups").status_code == 403
    assert client.get("/admin/groups", params={"token": "webhook-secret"}).status_code == 403
    assert client.get("/admin/groups", params={"token": "wrong"}).status_code == 403
    page = client.get("/admin/groups", params={"token": "admin-secret"})
    assert page.status_code == 200
    assert "HackGT13" in page.text or GROUP in page.text
    header = client.get("/admin/groups", headers={"X-Rally-Admin-Token": "admin-secret"})
    assert header.status_code == 200


def test_group_admin_fails_closed_without_configured_admin_token(tmp_path):
    client, *_ = setup(tmp_path, admin_token="")
    assert client.get("/admin/groups", params={"token": ""}).status_code == 403
    assert client.get("/admin/groups", headers={"X-Rally-Admin-Token": "anything"}).status_code == 403


def test_group_detail_shows_ops_and_hides_private_relationship_data(tmp_path):
    client, rally, portal, private = setup(tmp_path)
    portal.ensure_group(GROUP)
    portal.update_settings(GROUP, title="HackGT13")
    rally.store.add_message(ChatMessage("m1", GROUP, "nick", "Dinner Friday?", NOW))
    rally.store.save_plan(GROUP, PlanFacts(goal="Friday dinner", activity="dinner",
                                           participants=["nick"], confidence=0.4), NOW)
    rally.group_memory.upsert_fact(GROUP, "food.preference", "The group prefers pasta", "m1", NOW)
    encoded = quote(GROUP, safe="")
    missing = client.get(f"/admin/groups/{encoded}")
    assert missing.status_code == 403
    page = client.get(f"/admin/groups/{encoded}", params={"token": "admin-secret"})
    assert page.status_code == 200
    assert "Dinner Friday?" in page.text
    assert "Friday dinner" in page.text
    assert "The group prefers pasta" in page.text
    assert "Mom" not in page.text
    assert "admin-secret" not in page.text
    assert "webhook-secret" not in page.text
    private_page = client.get(f"/admin/groups/{quote(PRIVATE, safe='')}",
                              params={"token": "admin-secret"})
    assert private_page.status_code == 404
    assert "Mom" not in private_page.text


def test_group_admin_cookie_lets_picker_open_a_group_without_exposing_token(tmp_path):
    client, rally, portal, _ = setup(tmp_path)
    portal.ensure_group(GROUP)
    portal.update_settings(GROUP, title="HackGT13")
    rally.store.add_message(ChatMessage("m1", GROUP, "nick", "Dinner Friday?", NOW))
    first = client.get("/admin/groups", params={"token": "admin-secret"})
    assert first.status_code == 200
    assert "admin-secret" not in first.text
    assert "rally_admin" in first.cookies
    linked = client.get("/admin/groups")
    assert linked.status_code == 200
    detail = client.get(f"/admin/groups/{quote(GROUP, safe='')}")
    assert detail.status_code == 200
    assert "Dinner Friday?" in detail.text
    assert "admin-secret" not in detail.text


def setup_commands(tmp_path, *, app_url="https://rallyplans.vercel.app", admin_token="admin-secret"):
    path = tmp_path / "rally.sqlite3"
    store = Store(path)
    portal = PortalStore(path)
    private = RelationshipStore(path)
    private.configure("local-imessage-account", PRIVATE, "UTC", 18)
    sent = []
    rally = RallyService(
        store, QuietAgent(), lambda facts: [], lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={GROUP},
    )
    relationships = RelationshipService(private, rally.send_fn)
    app = create_app(
        rally, webhook_token="webhook-secret", admin_token=admin_token,
        schedule=False, portal_store=portal, relationship_service=relationships,
        history_enabled=False, app_url=app_url, voice_owner="local-imessage-account",
    )
    return TestClient(app), sent, portal


def webhook(client, message_id, text, *, mine=False, chat=GROUP, sender="member"):
    return client.post("/webhooks/bluebubbles?token=webhook-secret", json={
        "type": "new-message",
        "data": {"guid": message_id, "text": text, "isFromMe": mine,
                 "dateCreated": int(NOW.timestamp() * 1000),
                 "handle": {"address": sender}, "chats": [{"guid": chat}]},
    })


def test_dashboard_command_texts_hosted_archive_not_local_admin(tmp_path):
    client, sent, portal = setup_commands(tmp_path)
    public_id = portal.ensure_group(GROUP)
    assert webhook(client, "dash-1", "Rally, send the dashboard", mine=True).status_code == 200
    assert sent[0][0] == GROUP
    assert f"https://rallyplans.vercel.app/{public_id}" in sent[0][1]
    assert any(word in sent[0][1].lower() for word in ("damn", "shit", "fuck", "ass"))
    assert "admin-secret" not in sent[0][1]
    assert "127.0.0.1" not in sent[0][1]
    assert GROUP not in sent[0][1]


def test_admin_dashboard_phrase_keeps_vercel_link_and_no_token(tmp_path):
    client, sent, portal = setup_commands(tmp_path)
    public_id = portal.ensure_group(GROUP)
    assert webhook(client, "dash-2", "Rally, admin dashboard").status_code == 200
    assert sent[0][0] == GROUP
    assert f"https://rallyplans.vercel.app/{public_id}" in sent[0][1]
    assert any(word in sent[0][1].lower() for word in ("damn", "shit", "fuck", "ass"))
    assert "Mac" in sent[0][1]
    assert "admin-secret" not in sent[0][1]
    assert "127.0.0.1" not in sent[0][1]


def test_page_link_is_unchanged_when_dashboard_commands_exist(tmp_path):
    client, sent, portal = setup_commands(tmp_path)
    assert webhook(client, "page-1", "Hey Rally, send our page link").status_code == 200
    public_id = portal.ensure_group(GROUP)
    assert sent[0][0] == GROUP
    assert f"https://rallyplans.vercel.app/{public_id}" in sent[0][1]
    assert any(word in sent[0][1].lower() for word in ("damn", "shit", "fuck", "ass"))


def test_dashboard_command_without_app_url_does_not_text_localhost(tmp_path):
    client, sent, _ = setup_commands(tmp_path, app_url="")
    assert webhook(client, "dash-3", "Rally, send the dashboard", mine=True).status_code == 200
    assert sent
    assert all("127.0.0.1" not in body and "admin-secret" not in body for _, body in sent)
    assert all("http" not in body.lower() for _, body in sent)


def test_public_portal_stays_unauthenticated_and_lacks_admin_ops(tmp_path):
    client, rally, portal, _ = setup(tmp_path)
    public_id = portal.ensure_group(GROUP)
    rally.store.add_message(ChatMessage("m1", GROUP, "nick", "Dinner Friday?", NOW))
    page = client.get(f"/{public_id}")
    assert page.status_code == 200
    assert "Dinner Friday?" in page.text or "Conversation" in page.text
    assert "/admin/groups" not in page.text
    assert "unprocessed" not in page.text.lower()
    assert client.get("/admin/groups").status_code == 403
