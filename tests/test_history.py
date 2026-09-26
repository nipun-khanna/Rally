import io
import json
from urllib.error import URLError

import pytest

from app.history import BlueBubblesHistoryClient, HistoryFetchError, HistoryImporter, normalize_archive_message


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_fetch_page_encodes_chat_guid_and_requests_ascending_history():
    seen = []

    def opener(request, timeout):
        seen.append((request.full_url, timeout))
        return Response(json.dumps({"status": 200, "data": [{"guid": "m1"}]}).encode())

    client = BlueBubblesHistoryClient("http://127.0.0.1:1234", "secret", opener)
    assert client.fetch_messages("iMessage;+;chat/1", limit=25, offset=50) == [{"guid": "m1"}]
    assert "/chat/iMessage%3B%2B%3Bchat%2F1/message?" in seen[0][0]
    assert "sort=ASC" in seen[0][0]
    assert "offset=50" in seen[0][0]
    assert "with=handle%2Cattachment" in seen[0][0]


def test_error_does_not_expose_password():
    def failing(*_args, **_kwargs):
        raise URLError("secret")

    client = BlueBubblesHistoryClient("http://127.0.0.1:1234", "secret", failing)
    with pytest.raises(HistoryFetchError) as error:
        client.fetch_messages("group")
    assert "secret" not in str(error.value)


def test_attachment_download_is_atomic(tmp_path):
    def opener(*_args, **_kwargs):
        return Response(b"image bytes")

    client = BlueBubblesHistoryClient("http://127.0.0.1:1234", "secret", opener)
    destination = tmp_path / "a.bin"
    client.download_attachment("guid", destination)
    assert destination.read_bytes() == b"image bytes"
    assert not (tmp_path / "a.bin.part").exists()


def test_import_resumes_from_committed_offset_and_keeps_media(tmp_path):
    class Store:
        state = {"cursor": None, "status": "pending"}
        messages = []

        def import_state(self, _chat):
            return self.state

        def set_import_state(self, _chat, **kwargs):
            self.state = {**self.state, **kwargs}

        def upsert_messages(self, _chat, messages):
            self.messages.extend(messages)

    class Client:
        offsets = []

        def fetch_messages(self, _chat, limit, offset):
            self.offsets.append(offset)
            if offset:
                return []
            return [{"guid": "m1", "dateCreated": 1000, "text": "hello",
                     "isFromMe": False, "handle": {"address": "person"},
                     "attachments": [{"guid": "a1", "mimeType": "image/png",
                                      "transferName": "photo.png", "totalBytes": 3}]}]

        def download_attachment(self, _guid, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"png")

    store = Store()
    client = Client()
    importer = HistoryImporter(client, store, tmp_path)
    assert importer.import_page("chat", limit=1) == 1
    assert store.state["cursor"] == "1"
    assert store.messages[0]["attachments"][0]["status"] == "available"
    assert importer.import_page("chat", limit=1) == 0
    assert store.state["status"] == "complete"
    assert client.offsets == [0, 1]


def test_failed_page_preserves_cursor(tmp_path):
    class Store:
        state = {"cursor": "10", "status": "pending"}

        def import_state(self, _chat):
            return self.state

        def set_import_state(self, _chat, **kwargs):
            self.state = {**self.state, **kwargs}

    class Client:
        def fetch_messages(self, *_args, **_kwargs):
            raise HistoryFetchError("BlueBubbles history request failed")

    store = Store()
    with pytest.raises(HistoryFetchError):
        HistoryImporter(Client(), store, tmp_path).import_page("chat")
    assert store.state["cursor"] == "10"
    assert store.state["status"] == "error"


def test_media_only_webhook_is_archived():
    message = normalize_archive_message({
        "guid": "m2", "dateCreated": 2000, "isFromMe": True, "text": None,
        "attachments": [{"guid": "a2", "mimeType": "video/mp4", "totalBytes": 42}],
    }, "group")
    assert message["text"] == ""
    assert message["attachments"][0]["status"] == "pending"


def test_pending_live_media_can_be_hydrated(tmp_path):
    class Store:
        message = normalize_archive_message({"guid": "m", "dateCreated": 1000,
                                             "attachments": [{"guid": "a"}]}, "chat")

        def list_messages(self, _chat, before=None, limit=500):
            return [self.message] if before is None else []

        def upsert_messages(self, _chat, messages):
            self.message = messages[0]

    class Client:
        def download_attachment(self, _guid, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"media")

    store = Store()
    importer = HistoryImporter(Client(), store, tmp_path)
    assert importer.hydrate_pending_media("chat") == 1
    assert store.message["attachments"][0]["status"] == "available"
    assert importer.hydrate_pending_media("chat") == 0
