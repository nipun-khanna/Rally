from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.browser.agent import looks_like_browser_request
from app.browser.handler import BrowserInbound
from app.group_memory import GroupMemoryStore
from app.group_turns import GroupTurnStore
from app.main import create_app
from app.media import looks_like_image_request
from app.models import ChatMessage, PlanFacts
from app.orchestrator import HELP_REPLY, RallyService, looks_like_help_request
from app.store import Store


NOW = datetime(2026, 9, 26, 21, tzinfo=timezone.utc)
HACK = "iMessage;+;hackgt13"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc`\x00\x00"
    b"\x00\x02\x00\x01\xe5'\xde\xfc\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


class WatchAgent:
    def extract(self, messages, previous):
        raise AssertionError("capability routing must not extract a plan")

    def decide_conversation(self, request, facts, messages, **kwargs):
        raise AssertionError(f"must not use the conversation path: {request}")


def _service(tmp_path, **kwargs):
    db = tmp_path / "rally.sqlite3"
    sent, attachments, prompts = [], [], []

    def image_fn(prompt):
        prompts.append(prompt)
        return PNG

    def send_attachment(chat_id, path, *, name=None, mime_type=None):
        attachments.append({
            "chat_id": chat_id,
            "data": Path(path).read_bytes(),
            "name": name,
        })
        return {"status": 200}

    service = RallyService(
        Store(db), WatchAgent(), lambda facts: [],
        lambda chat, text: sent.append((chat, text)),
        group_memory=GroupMemoryStore(db), group_turns=GroupTurnStore(db),
        allowed_chat_ids={HACK},
        image_fn=image_fn,
        send_attachment_fn=send_attachment,
        **kwargs,
    )
    return service, sent, attachments, prompts


def test_what_can_you_do_lists_real_tools(tmp_path):
    assert looks_like_help_request("Rally, what can you do")
    assert looks_like_help_request("what can you help with")
    assert looks_like_help_request("Hey Rally, help")
    assert not looks_like_help_request("Rally, help us decide")
    assert not looks_like_help_request("Hey Rally, draw a cat")
    assert not looks_like_help_request("Hey Rally, open example.com")
    assert not looks_like_help_request("Rally, recap the plan")

    service, sent, _, _ = _service(tmp_path)
    assert service.receive(ChatMessage(
        "help1", HACK, "nick", "Rally, what can you do", NOW))
    body = sent[-1][1].lower()
    assert "image" in body
    assert "browser" in body
    assert "dashboard" in body
    assert "reservation" in body
    assert "rallyplans.vercel.app" in body
    assert "coward" not in body
    assert body == HELP_REPLY


def test_draw_a_cat_still_image_path(tmp_path):
    assert looks_like_image_request("Hey Rally, draw a cat")
    service, sent, attachments, prompts = _service(tmp_path)
    assert service.receive(ChatMessage(
        "img1", HACK, "nick", "Hey Rally, draw a cat", NOW))
    assert prompts and "cat" in prompts[0].casefold()
    assert attachments and attachments[0]["data"].startswith(b"\x89PNG")
    assert "here's the plan" not in sent[-1][1].lower()


def test_open_example_com_still_browser(tmp_path):
    text = "Hey Rally, open example.com"
    assert looks_like_browser_request(text)
    assert not looks_like_help_request(text)
    service, sent, _, _ = _service(tmp_path)
    message = ChatMessage("br1", HACK, "nick", text, NOW)
    assert service._has_local_reply(message, None) is False

    runtime_sent = []

    class FakeTask:
        def run(self, ctx, request):
            return {"status": "complete", "answer": "opened example.com",
                    "url": "https://example.com"}

    inbound = BrowserInbound(
        HACK, "nick", FakeTask(),
        lambda chat, body: runtime_sent.append((chat, body)),
        allowed_chat_ids={HACK})
    app = create_app(
        service, webhook_token="secret", schedule=False,
        browser_inbound=inbound, browser_enabled=True)
    client = TestClient(app)
    response = client.post("/webhooks/bluebubbles?token=secret", json={
        "type": "new-message",
        "data": {
            "guid": "open-1", "text": text, "isFromMe": False,
            "dateCreated": int(NOW.timestamp() * 1000),
            "handle": {"address": "nick"}, "chats": [{"guid": HACK}],
        },
    })
    assert response.json()["accepted"] is True
    assert runtime_sent and "example.com" in runtime_sent[-1][1].lower()
    assert all("here's the plan" not in body.lower() for _, body in runtime_sent)
    client.close()


def test_recap_ask_still_recap(tmp_path):
    service, sent, _, _ = _service(tmp_path)
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", location="Rambler Atlanta"), NOW)
    assert service.receive(ChatMessage(
        "r1", HACK, "nick", "Rally, recap the plan", NOW))
    body = sent[-1][1].lower()
    assert "dinner" in body and "rambler" in body
    assert "here's the plan" in body
    assert "image" not in body
