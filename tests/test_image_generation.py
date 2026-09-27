from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent import GrokClient
from app.group_memory import GroupMemoryStore
from app.group_safety import illegal_assistance_request, refusal_text
from app.group_turns import GroupTurnStore
from app.main import create_app
from app.media import (
    image_prompt,
    looks_like_image_request,
    looks_like_video_request,
    video_prompt,
)
from app.models import ChatMessage, PlanFacts
from app.orchestrator import RallyService
from app.store import Store


NOW = datetime(2026, 9, 26, 21, tzinfo=timezone.utc)
HACK = "iMessage;+;hackgt13"
DM = "any;-;+15555550100"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc`\x00\x00"
    b"\x00\x02\x00\x01\xe5'\xde\xfc\x00\x00\x00\x00IEND\xaeB`\x82"
)
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 24
_REFUSE = ("spicy", "espn", "google for that", "pen pics", "live scores",
           "ask google")


class WatchAgent:
    def extract(self, messages, previous):
        raise AssertionError("image requests must not extract a plan")

    def decide_conversation(self, request, facts, messages, **kwargs):
        raise AssertionError("image requests must not use the conversation refuse path")


def _service(tmp_path, *, chats=None, image_bytes=PNG, video_bytes=None,
             video_url=None):
    db = tmp_path / "rally.sqlite3"
    sent, attachments, prompts, video_prompts = [], [], [], []

    def image_fn(prompt):
        prompts.append(prompt)
        return image_bytes

    def video_fn(prompt):
        video_prompts.append(prompt)
        return video_bytes

    def video_link_fn(prompt):
        video_prompts.append(prompt)
        return video_url

    def send_attachment(chat_id, path, *, name=None, mime_type=None):
        data = Path(path).read_bytes()
        attachments.append({
            "chat_id": chat_id,
            "path": str(path),
            "name": name,
            "mime_type": mime_type,
            "data": data,
        })
        return {"status": 200}

    service = RallyService(
        Store(db), WatchAgent(), lambda facts: [],
        lambda chat, text: sent.append((chat, text)),
        group_memory=GroupMemoryStore(db), group_turns=GroupTurnStore(db),
        allowed_chat_ids=set(chats or (HACK, DM)),
        image_fn=image_fn,
        video_fn=video_fn,
        video_link_fn=video_link_fn,
        send_attachment_fn=send_attachment,
    )
    return service, sent, attachments, prompts, video_prompts


def test_image_intent_matches_draw_generate_and_pen_pics():
    assert looks_like_image_request("Hey Rally, draw a cat")
    assert looks_like_image_request("Rally, generate an image of a sunset")
    assert looks_like_image_request("Rally, make me a picture of a red panda")
    assert looks_like_image_request("Rally, add an image of a cat")
    assert looks_like_image_request("Rally, send a pic of a lighthouse")
    assert looks_like_image_request("pen pics of a soccer player")
    assert looks_like_image_request("Rally, picture of a lighthouse")
    assert looks_like_image_request("draw a cat")
    assert not looks_like_image_request("Hey Rally, where should we eat?")
    assert not looks_like_image_request("Rally, draw up a dinner plan")
    assert not looks_like_image_request("Rally, recap the plan")
    assert not looks_like_image_request("Hey Rally, send a video of a cat")


def test_image_prompt_keeps_the_subject():
    assert "cat" in image_prompt("Hey Rally, draw a cat").casefold()
    assert "sunset" in image_prompt("Rally, generate an image of a sunset").casefold()
    assert "lighthouse" in image_prompt("Rally, send a pic of a lighthouse").casefold()
    assert "soccer" in image_prompt("Rally, pen pics of a soccer player").casefold()


def test_draw_a_cat_sends_attachment_not_refuse_recap(tmp_path):
    service, sent, attachments, prompts, _ = _service(tmp_path)
    assert service.receive(ChatMessage(
        "img1", HACK, "nick", "Hey Rally, draw a cat", NOW))
    assert prompts and "cat" in prompts[0].casefold()
    assert attachments and attachments[0]["chat_id"] == HACK
    assert attachments[0]["data"].startswith(b"\x89PNG")
    assert attachments[0]["data"] == PNG
    assert sent and sent[-1][0] == HACK
    body = sent[-1][1].casefold()
    assert not any(phrase in body for phrase in _REFUSE)
    assert body != refusal_text().casefold()


def test_generate_an_image_of_hits_image_path_on_dm(tmp_path):
    service, sent, attachments, prompts, _ = _service(tmp_path)
    assert service.receive(ChatMessage(
        "img2", DM, "local-imessage-account",
        "Hey Rally, generate an image of a lighthouse at dawn", NOW))
    assert prompts and "lighthouse" in prompts[0].casefold()
    assert attachments and attachments[0]["chat_id"] == DM
    assert sent[-1][0] == DM
    assert "spicy" not in sent[-1][1].casefold()


def test_turn_followup_can_request_an_image(tmp_path):
    service, sent, attachments, _, _ = _service(tmp_path)

    class RecapAgent:
        def extract(self, messages, previous):
            return PlanFacts(activity="dinner", goal="Friday dinner")

        def decide_conversation(self, request, facts, messages, **kwargs):
            if "draw" in request.casefold():
                raise AssertionError("image follow-up must not hit conversation")
            return type("D", (), {
                "relevant": True, "safety": "ok", "message": "ramen friday.",
                "reaction": "like", "memory_candidates": [],
            })()

    service.agent = RecapAgent()
    service.reply_agent = RecapAgent()
    service.receive(ChatMessage("open", HACK, "nick", "Hey Rally, recap?", NOW))
    assert service.receive(ChatMessage(
        "follow", HACK, "maya", "draw a cat", NOW + timedelta(seconds=30)))
    assert attachments and attachments[-1]["data"].startswith(b"\x89PNG")


def test_image_safety_still_blocks_disallowed_prompts(tmp_path):
    text = "Rally, generate an image of csam"
    assert illegal_assistance_request(text)
    service, sent, attachments, prompts, _ = _service(tmp_path)
    service.receive(ChatMessage("bad", HACK, "nick", text, NOW))
    assert attachments == []
    assert prompts == []
    assert sent[-1][1] == refusal_text()


def test_http_draw_a_cat_sends_mocked_attachment(tmp_path):
    sent, attachments = [], []
    store = Store(tmp_path / "rally.sqlite3")
    service = RallyService(
        store, WatchAgent(), lambda facts: [],
        lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={HACK},
        image_fn=lambda prompt: PNG,
        send_attachment_fn=lambda chat, path, **kwargs: attachments.append(
            (chat, Path(path).read_bytes(), kwargs)),
    )
    client = TestClient(create_app(service, webhook_token="secret", schedule=False))
    payload = {"type": "new-message", "data": {
        "guid": "http-img", "text": "Hey Rally, draw a cat", "isFromMe": False,
        "handle": {"address": "nick"}, "chats": [{"guid": HACK}],
        "dateCreated": int(NOW.timestamp() * 1000)}}
    result = client.post("/webhooks/bluebubbles?token=secret", json=payload)
    client.close()
    assert result.json() == {"accepted": True}
    assert attachments and attachments[0][0] == HACK
    assert attachments[0][1].startswith(b"\x89PNG")
    assert sent
    assert "espn" not in sent[-1][1].casefold()


def test_generate_image_uses_current_imagine_model_and_hides_key():
    captured = []

    def transport(payload):
        captured.append(payload)
        import base64
        return PNG

    client = GrokClient("secret-image-key", image_transport=transport)
    data = client.generate_image("a watercolor cat")
    assert data.startswith(b"\x89PNG")
    assert captured[0]["model"] == "grok-imagine-image-2.0"
    assert captured[0]["prompt"] == "a watercolor cat"
    assert captured[0]["response_format"] == "b64_json"
    assert "secret-image-key" not in str(captured)


def test_send_a_pic_also_hits_image_path(tmp_path):
    service, sent, attachments, prompts, _ = _service(tmp_path)
    assert service.receive(ChatMessage(
        "img3", HACK, "nick", "Hey Rally, send a pic of a red panda", NOW))
    assert prompts and "panda" in prompts[0].casefold()
    assert attachments and attachments[0]["data"].startswith(b"\x89PNG")
    assert "espn" not in sent[-1][1].casefold()


def test_video_intent_matches_send_video_and_link():
    assert looks_like_video_request("Hey Rally, send a video of a cat")
    assert looks_like_video_request("Rally, send a link to a video of overtime")
    assert looks_like_video_request("Rally, youtube clip of a sunset")
    assert looks_like_video_request("Rally, send me a video")
    assert not looks_like_video_request("Hey Rally, draw a cat")
    assert not looks_like_video_request("Rally, recap the plan")
    assert "cat" in video_prompt("Hey Rally, send a video of a cat").casefold()


def test_send_a_video_sends_https_url_not_refuse_recap(tmp_path):
    service, sent, attachments, _, prompts = _service(tmp_path, video_url=YT)
    assert service.receive(ChatMessage(
        "vid1", HACK, "nick", "Hey Rally, send a video of a cat", NOW))
    assert prompts and "cat" in prompts[0].casefold()
    assert attachments == []
    body = sent[-1][1]
    assert YT in body
    lowered = body.casefold()
    assert not any(phrase in lowered for phrase in _REFUSE)
    assert body != refusal_text()


def test_video_file_is_attached_when_generated(tmp_path):
    service, sent, attachments, _, prompts = _service(tmp_path, video_bytes=MP4)
    assert service.receive(ChatMessage(
        "vid2", DM, "local-imessage-account",
        "Hey Rally, generate a video of a lighthouse", NOW))
    assert prompts
    assert attachments and attachments[0]["data"].startswith(b"\x00\x00\x00")
    assert (attachments[0]["mime_type"] or "").startswith("video/")
    assert "espn" not in sent[-1][1].casefold()


def test_video_fail_closed_does_not_invent_a_url(tmp_path):
    service, sent, attachments, _, _ = _service(tmp_path)
    assert service.receive(ChatMessage(
        "vid3", HACK, "nick", "Hey Rally, send a video of a cat", NOW))
    assert attachments == []
    body = sent[-1][1].casefold()
    assert "http" not in body
    assert "couldn't" in body or "could not" in body or "can't find" in body
    assert not any(phrase in body for phrase in _REFUSE)


def test_video_safety_still_blocks_disallowed_prompts(tmp_path):
    text = "Rally, send a video of csam"
    assert illegal_assistance_request(text)
    service, sent, attachments, _, prompts = _service(tmp_path, video_url=YT)
    service.receive(ChatMessage("badvid", HACK, "nick", text, NOW))
    assert attachments == []
    assert prompts == []
    assert sent[-1][1] == refusal_text()
    assert YT not in sent[-1][1]
