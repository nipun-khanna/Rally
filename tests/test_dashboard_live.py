from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app.adaptive.tools import build_default_registry
from app.dashboard_live import generate_dashboard, lookup_dashboard
from app.main import create_app
from app.models import ChatMessage, PlanFacts
from app.orchestrator import RallyService
from app.portal_store import PortalStore
from app.store import Store


NOW = datetime(2026, 9, 26, 21, 30, tzinfo=timezone.utc)
GROUP = "iMessage;+;hackgt13"
OTHER = "iMessage;+;other-group"
APP = "https://rallyplans.vercel.app"
PLANTED = "dinner 2026-09-27 at 8pm near taj, atlanta, indian"


class QuietAgent:
    def extract(self, messages, previous):
        return PlanFacts()

    def answer_direct(self, request, facts, messages):
        raise AssertionError("dashboard must not wait on the model")

    def decide_conversation(self, *args, **kwargs):
        raise AssertionError("dashboard must not wait on the model")


def _setup(tmp_path, *, chats=None):
    chats = chats or {GROUP, OTHER}
    path = tmp_path / "rally.sqlite3"
    store = Store(path)
    portal = PortalStore(path)
    sent = []
    rally = RallyService(
        store, QuietAgent(), lambda facts: [], lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids=chats,
    )
    app = create_app(
        rally, webhook_token="webhook-secret", admin_token="admin-secret",
        schedule=False, portal_store=portal, history_enabled=True, app_url=APP,
    )
    return TestClient(app), rally, portal, sent


def _plant(rally, chat=GROUP):
    rally.store.add_message(ChatMessage("planted", chat, "nick", PLANTED, NOW))
    rally.store.save_plan(chat, PlanFacts(
        activity="dinner", date="2026-09-27", time="20:00",
        location="taj, atlanta", preferred_cuisines=["indian"]), NOW)


def _webhook(client, message_id, text, *, chat=GROUP):
    return client.post("/webhooks/bluebubbles?token=webhook-secret", json={
        "type": "new-message",
        "data": {"guid": message_id, "text": text, "isFromMe": True,
                 "dateCreated": int(NOW.timestamp() * 1000),
                 "handle": {"address": "member"}, "chats": [{"guid": chat}]},
    })


def _public_id_from(url: str) -> str:
    path = urlparse(url).path
    assert path.startswith("/") and path != "/"
    return path[1:]


def test_dashboard_ask_sends_vercel_url_and_lookup_has_planted_plan(tmp_path):
    client, rally, portal, sent = _setup(tmp_path)
    _plant(rally)
    other_id = portal.ensure_group(OTHER)
    assert _webhook(client, "dash-live", "Rally, send the dashboard").status_code == 200
    assert sent, "dashboard ask must text a link"
    body = sent[0][1]
    assert APP in body
    assert "admin-secret" not in body
    assert "token=" not in body
    assert "127.0.0.1" not in body
    assert GROUP not in body
    url = next(part for part in body.split() if part.startswith(APP))
    public_id = _public_id_from(url)
    assert public_id == portal.ensure_group(GROUP)
    assert public_id == url[len(APP) + 1:]
    snapshot = lookup_dashboard(rally.store, portal, public_id)
    assert snapshot is not None
    blob = " ".join([
        snapshot.get("title") or "",
        " ".join(plan.get("title") or "" for plan in snapshot.get("plans") or []),
        " ".join(" ".join(plan.get("details") or []) for plan in snapshot.get("plans") or []),
        " ".join(msg.get("text") or "" for msg in snapshot.get("messages") or []),
    ]).lower()
    assert "taj" in blob and "atlanta" in blob and "indian" in blob
    page = client.get(f"/{public_id}")
    assert page.status_code == 200
    lowered = page.text.lower()
    assert "taj" in lowered and "atlanta" in lowered and "indian" in lowered
    other_page = client.get(f"/{other_id}")
    assert other_page.status_code == 200
    assert "taj" not in other_page.text.lower()
    assert lookup_dashboard(rally.store, portal, other_id) is not None
    other_blob = " ".join(" ".join(plan.get("details") or [])
                          for plan in lookup_dashboard(rally.store, portal, other_id)["plans"]).lower()
    assert "taj" not in other_blob


def test_generate_dashboard_tool_is_chat_scoped_and_findable(tmp_path):
    path = tmp_path / "rally.sqlite3"
    store = Store(path)
    portal = PortalStore(path)
    store.add_message(ChatMessage("planted", GROUP, "nick", PLANTED, NOW))
    store.save_plan(GROUP, PlanFacts(
        activity="dinner", location="taj, atlanta", preferred_cuisines=["indian"]), NOW)

    def generate(chat_id):
        return generate_dashboard(
            store, portal, chat_id, app_url=APP, allowed_chat_ids={GROUP})

    registry = build_default_registry({GROUP}, plan_store=store, generate_dashboard_fn=generate)
    assert "generate_dashboard" in registry.names()
    assert "publish_archive" in registry.names()
    import pytest
    with pytest.raises(PermissionError):
        registry.execute("generate_dashboard", {}, chat_id=OTHER)
    result = registry.execute("publish_archive", {}, chat_id=GROUP)
    assert result["url"] == f"{APP}/{result['public_id']}"
    snapshot = lookup_dashboard(store, portal, result["public_id"])
    blob = " ".join(" ".join(plan.get("details") or []) for plan in snapshot["plans"]).lower()
    assert "taj" in blob and "atlanta" in blob and "indian" in blob


def test_live_sync_does_not_replace_member_display_names(tmp_path):
    path = tmp_path / "rally.sqlite3"
    store = Store(path)
    portal = PortalStore(path)
    portal.ensure_group(GROUP)
    portal.set_member(GROUP, "nick", "Nick")
    store.add_message(ChatMessage("planted", GROUP, "nick", PLANTED, NOW))
    generate_dashboard(store, portal, GROUP, app_url=APP, allowed_chat_ids={GROUP})
    names = {member["sender_id"]: member["display_name"] for member in portal.members(GROUP)}
    assert names["nick"] == "Nick"


def test_hyphenated_mixed_case_public_id_lookup_stays_exact(tmp_path):
    path = tmp_path / "rally.sqlite3"
    store = Store(path)
    portal = PortalStore(path)
    public_id = "YSOVrF57lVMS4Bj8Nk2xbkET82nB-aD4"
    portal.ensure_group(GROUP)
    with portal._db() as db:
        db.execute("UPDATE portal_groups SET public_id=? WHERE chat_id=?", (public_id, GROUP))
    store.add_message(ChatMessage("planted", GROUP, "nick", PLANTED, NOW))
    store.save_plan(GROUP, PlanFacts(
        activity="dinner", location="taj, atlanta", preferred_cuisines=["indian"]), NOW)
    result = generate_dashboard(store, portal, GROUP, app_url=APP, allowed_chat_ids={GROUP})
    assert result["public_id"] == public_id
    assert result["url"] == f"{APP}/{public_id}"
    snapshot = lookup_dashboard(store, portal, public_id)
    blob = " ".join(" ".join(plan.get("details") or []) for plan in snapshot["plans"]).lower()
    assert "taj" in blob
    assert lookup_dashboard(store, portal, public_id.lower()) is None
