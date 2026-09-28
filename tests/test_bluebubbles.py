import json
import unittest
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import time
from unittest.mock import patch

from app.bluebubbles import (
    DeliveryUncertainError,
    IncomingMessage,
    _ECHO_TEXT_TTL_SECONDS,
    configure_outbound_echoes,
    is_private_direct_chat,
    normalize_webhook,
    reset_outbound_echoes,
    send_attachment,
    send_message,
)


def group_event():
    return {
        "type": "new-message",
        "data": {
            "guid": "message-1",
            "text": "Dinner Friday?",
            "isFromMe": False,
            "dateCreated": 1_727_452_800_000,
            "handle": {"address": "+15551234567"},
            "chats": [{
                "guid": "iMessage;+;chat123",
                "participants": [{"address": "+15551234567"}, {"address": "+15557654321"}],
            }],
        },
    }


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.payload).encode("utf-8")


class BlueBubblesTests(unittest.TestCase):
    def setUp(self):
        reset_outbound_echoes()

    def test_private_direct_chat_accepts_service_dash_id(self):
        self.assertTrue(is_private_direct_chat("iMessage;-;+15555550100"))
        self.assertTrue(is_private_direct_chat("any;-;+15555550100"))
        self.assertTrue(is_private_direct_chat("SMS;-;+15555550100"))
        self.assertTrue(is_private_direct_chat("other;-;person"))
        self.assertFalse(is_private_direct_chat("iMessage;+;group"))
        self.assertFalse(is_private_direct_chat("any;+;chat123"))
        self.assertFalse(is_private_direct_chat("iMessage;-;"))
        self.assertFalse(is_private_direct_chat(";-;person"))
        self.assertFalse(is_private_direct_chat("any"))

    def test_normalizes_group_message(self):
        message = normalize_webhook(group_event())
        self.assertIsInstance(message, IncomingMessage)
        self.assertEqual(message.message_id, "message-1")
        self.assertEqual(message.chat_id, "iMessage;+;chat123")
        self.assertEqual(message.sender_id, "+15551234567")
        self.assertEqual(message.text, "Dinner Friday?")
        self.assertEqual(message.sent_at, datetime.fromtimestamp(1_727_452_800, timezone.utc))
        self.assertFalse(message.is_from_rally)

    def test_updated_message_is_still_inbound(self):
        event = group_event()
        event["type"] = "updated-message"
        message = normalize_webhook(event)
        self.assertIsNotNone(message)
        self.assertEqual(message.text, "Dinner Friday?")
        event["type"] = "message-updated"
        self.assertEqual(normalize_webhook(event).message_id, "message-1")

    def test_ignores_non_message_and_direct_chat(self):
        event = group_event()
        event["type"] = "chat-read-status"
        self.assertIsNone(normalize_webhook(event))

        event = group_event()
        event["data"]["chats"] = [{"guid": "iMessage;-;+15551234567", "participants": [{}, {}]}]
        self.assertIsNone(normalize_webhook(event))

    def test_reaction_is_not_a_planning_message(self):
        event = group_event()
        event['data'].update({'text': 'Loved “Hey Rally, book it”',
                              'associatedMessageType': 2000,
                              'associatedMessageGuid': 'message-0'})
        self.assertIsNone(normalize_webhook(event))
        event = group_event()
        event['data']['associatedMessageType'] = 0
        self.assertIsNotNone(normalize_webhook(event))

    def test_accepts_local_human_prompt_but_ignores_rally_echo(self):
        event = group_event()
        event["data"].update({"isFromMe": True, "handle": None,
                              "text": "Hey Rally, what's the plan?"})
        message = normalize_webhook(event)
        self.assertIsNotNone(message)
        self.assertEqual(message.sender_id, "local-imessage-account")
        event["data"]["guid"] = "owner-typed-prefix"
        event["data"]["text"] = "Rally: Friday dinner is at 8."
        self.assertIsNotNone(normalize_webhook(event))

        def opener(request, timeout):
            return FakeResponse({"status": 200, "message": "Message sent!",
                                 "data": {"guid": "legacy-bot-guid"}})

        send_message(
            "https://bb.example/", "pw", "iMessage;+;chat123",
            "Rally: Friday dinner is at 8.", opener=opener)
        event["data"]["guid"] = "legacy-bot-guid"
        self.assertIsNone(normalize_webhook(event))

    def test_ignores_incomplete_and_nontext_payloads(self):
        event = group_event()
        event["data"]["text"] = None
        self.assertIsNone(normalize_webhook(event))

        event = group_event()
        event["data"]["handle"] = None
        self.assertIsNone(normalize_webhook(event))

        event = group_event()
        event["data"]["dateCreated"] = "yesterday"
        self.assertIsNone(normalize_webhook(event))

        self.assertIsNone(normalize_webhook(None))

    def test_sends_to_original_chat_with_password_query(self):
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse({"status": 200, "message": "Message sent!", "data": {"guid": "sent-1"}})

        result = send_message("https://bb.example/", "p&=secret", "iMessage;+;chat123", "Here is a venue", opener=opener)
        request = captured["request"]
        url = urlsplit(request.full_url)
        self.assertEqual(url.path, "/api/v1/message/text")
        self.assertEqual(parse_qs(url.query), {"password": ["p&=secret"]})
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data)
        self.assertEqual(body["chatGuid"], "iMessage;+;chat123")
        self.assertEqual(body["message"], "Here is a venue")
        self.assertTrue(body["tempGuid"])
        self.assertNotIn("selectedMessageGuid", body)
        self.assertNotIn("partIndex", body)
        self.assertEqual(result["data"]["guid"], "sent-1")
        self.assertGreaterEqual(captured["timeout"], 30)

    def test_send_message_includes_selected_message_guid_for_thread_reply(self):
        captured = {}

        def opener(request, timeout):
            captured["body"] = json.loads(request.data)
            return FakeResponse({"status": 200, "message": "Message sent!", "data": {"guid": "sent-2"}})

        result = send_message(
            "https://bb.example/", "pw", "any;+;chat536074477903103142",
            "Rally: locked-in chaos.", opener=opener,
            selected_message_guid="inbound-guid-1",
        )
        self.assertEqual(captured["body"]["chatGuid"], "any;+;chat536074477903103142")
        self.assertEqual(captured["body"]["message"], "locked-in chaos.")
        self.assertFalse(captured["body"]["message"].startswith("Rally:"))
        self.assertEqual(captured["body"]["selectedMessageGuid"], "inbound-guid-1")
        self.assertEqual(captured["body"]["partIndex"], 0)
        self.assertTrue(captured["body"]["tempGuid"])
        self.assertEqual(result["data"]["guid"], "sent-2")

    def test_invalid_selected_message_guid_still_sends_unthreaded(self):
        captured = {}

        def opener(request, timeout):
            captured["body"] = json.loads(request.data)
            return FakeResponse({"status": 200, "message": "Message sent!", "data": {"guid": "sent-3"}})

        send_message(
            "https://bb.example/", "pw", "any;+;chat1", "Rally: still sending.",
            opener=opener, selected_message_guid="bad guid",
        )
        self.assertEqual(captured["body"]["message"], "still sending.")
        self.assertNotIn("selectedMessageGuid", captured["body"])
        self.assertNotIn("partIndex", captured["body"])

    def test_never_exposes_password_from_transport_error(self):
        def failing_opener(request, timeout):
            raise URLError(f"request failed: {request.full_url}")

        with self.assertRaises(DeliveryUncertainError) as caught:
            send_message("https://bb.example", "topsecret", "group", "hello", opener=failing_opener)
        self.assertNotIn("topsecret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_rejects_provider_failure(self):
        def opener(request, timeout):
            return FakeResponse({"status": 500, "message": "Error"})

        with self.assertRaisesRegex(RuntimeError, "rejected"):
            send_message("https://bb.example", "pw", "group", "hello", opener=opener)

    def test_send_attachment_posts_multipart_and_strips_dm_prefix(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["content_type"] = request.get_header("Content-type")
            captured["body"] = request.data
            captured["timeout"] = timeout
            return FakeResponse({"status": 200, "message": "Message sent!"})

        png = b"\x89PNG\r\n\x1a\n" + b"data"
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rally.png"
            path.write_bytes(png)
            result = send_attachment(
                "https://bb.example/", "p&=secret", "any;-;+15555550100",
                path, name="rally.png", mime_type="image/png", opener=opener)
        url = urlsplit(captured["url"])
        self.assertEqual(url.path, "/api/v1/message/attachment")
        self.assertEqual(parse_qs(url.query), {"password": ["p&=secret"]})
        self.assertEqual(captured["method"], "POST")
        self.assertIn("multipart/form-data", captured["content_type"])
        body = captured["body"]
        self.assertIn(b"name=\"chatGuid\"", body)
        self.assertIn(b"+15555550100", body)
        self.assertNotIn(b"any;-;+15555550100", body)
        self.assertIn(b"rally.png", body)
        self.assertIn(png, body)
        self.assertEqual(result["status"], 200)
        self.assertGreaterEqual(captured["timeout"], 30)

    def test_send_attachment_keeps_group_guid(self):
        captured = {}

        def opener(request, timeout):
            captured["body"] = request.data
            return FakeResponse({"status": 200})

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.mp4"
            path.write_bytes(b"ftypmp42")
            send_attachment(
                "https://bb.example/", "pw", "iMessage;+;chat123",
                path, name="clip.mp4", mime_type="video/mp4", opener=opener)
        self.assertIn(b"iMessage;+;chat123", captured["body"])
        self.assertIn(b"clip.mp4", captured["body"])

    def test_send_attachment_hides_password_on_error(self):
        def failing_opener(request, timeout):
            raise URLError(f"request failed: {request.full_url}")

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rally.png"
            path.write_bytes(b"png")
            with self.assertRaises(DeliveryUncertainError) as caught:
                send_attachment("https://bb.example", "topsecret", "group", path,
                                opener=failing_opener)
        self.assertNotIn("topsecret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_prefix_free_send_still_drops_its_own_echo(self):
        import tempfile
        from pathlib import Path

        reset_outbound_echoes()
        captured = {}

        def opener(request, timeout):
            captured["body"] = json.loads(request.data)
            inflight = group_event()
            inflight["data"].update({
                "isFromMe": True, "handle": None, "guid": "inflight-unknown",
                "text": "Dinner Friday at 8",
            })
            captured["inflight_dropped"] = normalize_webhook(inflight) is None
            return FakeResponse({"status": 200, "message": "Message sent!",
                                 "data": {"guid": "apple-guid-1"}})

        try:
            send_message(
                "https://bb.example/", "pw", "iMessage;+;chat123",
                "Rally: Dinner Friday at 8", opener=opener)
            self.assertEqual(captured["body"]["message"], "Dinner Friday at 8")
            self.assertTrue(captured["inflight_dropped"])
            temp_guid = captured["body"]["tempGuid"]

            echo = group_event()
            echo["data"].update({
                "isFromMe": True, "handle": None, "guid": "apple-guid-1",
                "text": "Dinner Friday at 8",
            })
            self.assertIsNone(normalize_webhook(echo))

            by_temp = group_event()
            by_temp["data"].update({
                "isFromMe": True, "handle": None, "guid": "not-the-apple-guid",
                "tempGuid": temp_guid, "text": "Dinner Friday at 8",
            })
            self.assertIsNone(normalize_webhook(by_temp))

            human = group_event()
            human["data"].update({
                "isFromMe": True, "handle": None, "guid": "human-probe",
                "text": "Hey Rally, what's the plan?",
            })
            self.assertIsNotNone(normalize_webhook(human))

            other_chat = group_event()
            other_chat["data"].update({
                "isFromMe": True, "handle": None, "guid": "other-chat-copy",
                "text": "Dinner Friday at 8",
                "chats": [{"guid": "iMessage;+;chat-other"}],
            })
            self.assertIsNotNone(normalize_webhook(other_chat))

            same_words = group_event()
            same_words["data"].update({
                "isFromMe": True, "handle": None, "guid": "owner-repeat-now",
                "text": "Dinner Friday at 8",
            })
            self.assertIsNotNone(normalize_webhook(same_words))

            owner_prefix = group_event()
            owner_prefix["data"].update({
                "isFromMe": True, "handle": None, "guid": "owner-typed-prefix",
                "text": "Rally: Friday dinner is at 8.",
            })
            self.assertIsNotNone(normalize_webhook(owner_prefix))
            generated = group_event()
            generated["data"].update({
                "isFromMe": True, "handle": None, "guid": "apple-guid-1",
                "text": "Rally: Friday dinner is at 8.",
            })
            self.assertIsNone(normalize_webhook(generated))

            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "outbound-echo.json"
                configure_outbound_echoes(path)
                send_message(
                    "https://bb.example/", "pw", "iMessage;+;chat123",
                    "Saved reply", opener=opener)
                stored = path.read_text()
                self.assertNotIn("Saved reply", stored)
                configure_outbound_echoes(path)
                reloaded = group_event()
                reloaded["data"].update({
                    "isFromMe": True, "handle": None, "guid": "apple-guid-1",
                    "text": "a different body",
                })
                self.assertIsNone(normalize_webhook(reloaded))
        finally:
            reset_outbound_echoes()

    def test_text_fallback_expires_when_send_has_no_confirmed_id(self):
        reset_outbound_echoes()

        def opener(request, timeout):
            return FakeResponse({"status": 200, "message": "Message sent!", "data": {}})

        try:
            send_message(
                "https://bb.example/", "pw", "iMessage;+;chat123",
                "Same words", opener=opener)
            pending = group_event()
            pending["data"].update({
                "isFromMe": True, "handle": None, "guid": "owner-same-words",
                "text": "Same words",
            })
            self.assertIsNone(normalize_webhook(pending))
            later = time.time() + _ECHO_TEXT_TTL_SECONDS + 5
            with patch("app.bluebubbles.time.time", return_value=later):
                repeated = group_event()
                repeated["data"].update({
                    "isFromMe": True, "handle": None, "guid": "owner-same-words-later",
                    "text": "Same words",
                })
                self.assertIsNotNone(normalize_webhook(repeated))
        finally:
            reset_outbound_echoes()


if __name__ == "__main__":
    unittest.main()
