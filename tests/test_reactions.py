import json
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from app.reactions import REACTION_KINDS, clear_helper_cache, send_reaction, set_typing


CHAT = "iMessage;+;group123"
MESSAGE = "A1B2-C3D4"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.payload).encode("utf-8")


class ReactionTests(unittest.TestCase):
    def setUp(self):
        clear_helper_cache()

    def test_posts_documented_payload_after_private_api_preflight(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            if len(requests) == 1:
                return FakeResponse({"status": 200, "data": {"private_api": True, "helper_connected": True}})
            return FakeResponse({"status": 200, "message": "Reaction sent!", "data": {"guid": "reaction-1"}})

        result = send_reaction("http://127.0.0.1:1234/", "p&secret", CHAT, MESSAGE, "like", opener=opener)
        self.assertEqual(result.status, "sent")
        self.assertEqual(result.provider_message_guid, "reaction-1")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0][0].get_method(), "GET")
        self.assertEqual(urlsplit(requests[0][0].full_url).path, "/api/v1/server/info")
        self.assertEqual(requests[1][0].get_method(), "POST")
        self.assertEqual(urlsplit(requests[1][0].full_url).path, "/api/v1/message/react")
        self.assertEqual(parse_qs(urlsplit(requests[1][0].full_url).query), {"password": ["p&secret"]})
        self.assertEqual(json.loads(requests[1][0].data), {
            "chatGuid": CHAT, "selectedMessageGuid": MESSAGE, "reaction": "like", "partIndex": 0,
        })

    def test_skips_post_when_private_api_or_helper_is_disabled(self):
        for private_api, helper_connected in ((False, False), (True, False), (False, True)):
            with self.subTest(private_api=private_api, helper_connected=helper_connected):
                clear_helper_cache()
                requests = []

                def opener(request, timeout):
                    requests.append(request)
                    return FakeResponse({"status": 200, "data": {
                        "private_api": private_api, "helper_connected": helper_connected,
                    }})

                result = send_reaction("http://localhost:1234", "secret", CHAT, MESSAGE, "love", opener=opener)
                self.assertEqual(result.status, "unsupported")
                self.assertIn("helper", result.reason)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0].get_method(), "GET")

    def test_preflight_failure_does_not_send(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            raise URLError(f"failed: {request.full_url}")

        result = send_reaction("http://localhost:1234", "secret", CHAT, MESSAGE, "laugh", opener=opener)
        self.assertEqual(result.status, "unavailable")
        self.assertNotIn("secret", result.reason)
        self.assertEqual(len(requests), 1)

    def test_uncertain_post_is_not_retried(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            if len(requests) == 1:
                return FakeResponse({"status": 200, "data": {"private_api": True, "helper_connected": True}})
            raise URLError(f"timeout: {request.full_url}")

        result = send_reaction("http://localhost:1234", "secret", CHAT, MESSAGE, "question", opener=opener)
        self.assertEqual(result.status, "uncertain")
        self.assertNotIn("secret", result.reason)
        self.assertEqual(len(requests), 2)

    def test_rejected_or_incomplete_response_is_uncertain(self):
        for reaction_response in ({"status": 500}, {"status": 200}, {"status": 200, "data": {"guid": ""}}):
            with self.subTest(response=reaction_response):
                clear_helper_cache()
                responses = iter((
                    {"status": 200, "data": {"private_api": True, "helper_connected": True}},
                    reaction_response,
                ))
                result = send_reaction("http://localhost:1234", "secret", CHAT, MESSAGE, "like",
                                       opener=lambda request, timeout: FakeResponse(next(responses)))
                self.assertEqual(result.status, "uncertain")

    def test_invalid_input_never_calls_provider(self):
        def forbidden_opener(request, timeout):
            self.fail("Provider must not be called for invalid input")

        cases = (
            ("iMessage;-;+15551234567", MESSAGE, "like"),
            ("group123", MESSAGE, "like"),
            (CHAT, "", "like"),
            (CHAT, "bad guid", "like"),
            (CHAT, MESSAGE, "fire"),
        )
        for chat, message, kind in cases:
            with self.subTest(chat=chat, message=message, kind=kind):
                with self.assertRaises(ValueError):
                    send_reaction("http://localhost:1234", "secret", chat, message, kind,
                                  opener=forbidden_opener)
        self.assertEqual(len(REACTION_KINDS), 6)

    def test_posts_each_bluebubbles_tapback_kind(self):
        from app.reactions import completion_reaction
        self.assertEqual(completion_reaction("haha"), "laugh")
        self.assertEqual(completion_reaction("!!"), "emphasize")
        self.assertEqual(completion_reaction("heart"), "love")
        self.assertEqual(completion_reaction("?"), "question")
        self.assertEqual(completion_reaction("👀"), None)
        for kind in ("love", "like", "dislike", "laugh", "emphasize", "question"):
            with self.subTest(kind=kind):
                clear_helper_cache()
                requests = []

                def opener(request, timeout):
                    requests.append(request)
                    if sum(1 for item in requests if item.get_method() == "POST") == 0:
                        return FakeResponse({"status": 200, "data": {"private_api": True, "helper_connected": True}})
                    return FakeResponse({"status": 200, "message": "Reaction sent!", "data": {"guid": kind}})

                result = send_reaction("http://localhost:1234", "secret", CHAT, MESSAGE, kind, opener=opener)
                self.assertEqual(result.status, "sent")
                self.assertEqual(json.loads(requests[-1].data)["reaction"], kind)

    def test_posts_eyes_and_can_remove_it(self):
        for kind in ("👀", "-👀"):
            with self.subTest(kind=kind):
                clear_helper_cache()
                requests = []

                def opener(request, timeout):
                    requests.append(request)
                    if len(requests) == 1:
                        return FakeResponse({"status": 200, "data": {"private_api": True, "helper_connected": True}})
                    return FakeResponse({"status": 200, "message": "Reaction sent!", "data": {"guid": "r-1"}})

                result = send_reaction("http://localhost:1234", "secret", CHAT, MESSAGE, kind, opener=opener)
                self.assertEqual(result.status, "sent")
                self.assertEqual(json.loads(requests[1].data)["reaction"], kind)

    def test_helper_status_is_cached_and_typing_uses_it(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            if request.get_method() == "GET":
                return FakeResponse({"status": 200, "data": {"private_api": True, "helper_connected": True}})
            return FakeResponse({"status": 200, "data": {"guid": "r-1"}})

        send_reaction("http://localhost:1234", "secret", CHAT, MESSAGE, "like", opener=opener)
        send_reaction("http://localhost:1234", "secret", CHAT, MESSAGE, "love", opener=opener)
        self.assertEqual(sum(1 for item in requests if item.get_method() == "GET"), 1)
        typing = set_typing("http://localhost:1234", "secret", CHAT, True, opener=opener)
        self.assertEqual(typing.status, "sent")
        self.assertEqual(requests[-1].get_method(), "POST")
        self.assertIn("/api/v1/chat/", urlsplit(requests[-1].full_url).path)
        self.assertTrue(urlsplit(requests[-1].full_url).path.endswith("/typing"))
        stopped = set_typing("http://localhost:1234", "secret", CHAT, False, opener=opener)
        self.assertEqual(stopped.status, "sent")
        self.assertEqual(requests[-1].get_method(), "DELETE")

    def test_allowlist_any_plus_guid_is_a_group_chat(self):
        live = "any;+;chat536074477903103142"
        requests = []

        def opener(request, timeout):
            requests.append(request)
            if request.get_method() == "GET":
                return FakeResponse({"status": 200, "data": {"private_api": True, "helper_connected": True}})
            return FakeResponse({"status": 200, "message": "Reaction sent!", "data": {"guid": "reaction-1"}})

        result = send_reaction("http://127.0.0.1:1234/", "secret", live, MESSAGE, "like", opener=opener)
        self.assertEqual(result.status, "sent")
        self.assertEqual(json.loads(requests[-1].data)["chatGuid"], live)

    def test_uncached_helper_status_is_skipped_when_not_waiting(self):
        live = "any;+;chat536074477903103142"

        def forbidden_opener(request, timeout):
            self.fail("uncached helper_status must not run in front of a text reply")

        result = send_reaction(
            "http://127.0.0.1:1234/", "secret", live, MESSAGE, "like",
            opener=forbidden_opener, wait_for_helper=False,
        )
        self.assertEqual(result.status, "unsupported")
        typing = set_typing(
            "http://127.0.0.1:1234/", "secret", live, True,
            opener=forbidden_opener, wait_for_helper=False,
        )
        self.assertEqual(typing.status, "unsupported")

    def test_cached_helper_status_is_used_without_a_second_get(self):
        live = "any;+;chat536074477903103142"
        requests = []

        def opener(request, timeout):
            requests.append(request)
            if request.get_method() == "GET":
                return FakeResponse({"status": 200, "data": {"private_api": True, "helper_connected": True}})
            return FakeResponse({"status": 200, "message": "Reaction sent!", "data": {"guid": "reaction-1"}})

        send_reaction("http://127.0.0.1:1234/", "secret", live, MESSAGE, "like", opener=opener)
        before = len(requests)
        result = send_reaction(
            "http://127.0.0.1:1234/", "secret", live, MESSAGE, "love",
            opener=opener, wait_for_helper=False,
        )
        self.assertEqual(result.status, "sent")
        self.assertEqual(sum(1 for item in requests if item.get_method() == "GET"), 1)
        self.assertGreater(len(requests), before)


if __name__ == "__main__":
    unittest.main()
