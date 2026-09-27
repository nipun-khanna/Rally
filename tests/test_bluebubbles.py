import json
import unittest
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from app.bluebubbles import (
    DeliveryUncertainError,
    IncomingMessage,
    is_private_direct_chat,
    normalize_webhook,
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

    def test_ignores_non_message_and_direct_chat(self):
        event = group_event()
        event["type"] = "updated-message"
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
        event["data"]["text"] = "Rally: Friday dinner is at 8."
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
        self.assertEqual(captured["body"]["message"], "Rally: locked-in chaos.")
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
        self.assertEqual(captured["body"]["message"], "Rally: still sending.")
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


if __name__ == "__main__":
    unittest.main()
