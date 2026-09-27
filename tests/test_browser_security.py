from datetime import datetime, timezone

import pytest

from app.browser.agent import BrowserTaskService, ToolContext, looks_like_browser_request
from app.browser.runtime import BrowserObservation, classify_download, validate_action
from app.browser.store import BrowserStore
from app.browser.url_policy import validate_public_url


OWNER = "iMessage;-;owner"
SENDER = "+15555550123"


class FakeRuntime:
    def __init__(self):
        self.actions = []
        self.page = BrowserObservation("https://news.example.com/files", "Files", "Downloads",
                                       ({"role": "link", "name": "Download installer"},))

    def observe(self, *, chat_id, authenticated):
        return self.page

    def act(self, *, chat_id, authenticated, action):
        self.actions.append(action)
        if action.get("name") == "Download installer":
            return {"status": "blocked", "reason": "download type is not allowed"}
        raise RuntimeError("browser crashed")


def settings():
    return type("S", (), {
        "browser_enabled": True,
        "browser_owner_chat_id": OWNER,
        "browser_owner_sender_id": SENDER,
        "allowed_chat_ids": frozenset(),
        "browser_max_actions": 3,
        "browser_max_text_chars": 6000,
    })()


def test_private_redirect_url_is_rejected_before_navigation():
    with pytest.raises(ValueError):
        validate_public_url("http://127.0.0.1/secret")
    with pytest.raises(ValueError):
        validate_action({"action": "navigate", "url": "http://169.254.169.254/latest/meta-data"})


def test_download_cap_and_executables_are_blocked():
    assert classify_download("notes.txt", 100) == "ok"
    assert classify_download("payload.exe", 100) == "blocked"
    assert classify_download("notes.txt", 5_000_001) == "blocked"


def test_crash_and_blocked_download_return_specific_status(tmp_path):
    runtime = FakeRuntime()
    service = BrowserTaskService(
        runtime, BrowserStore(tmp_path / "r.sqlite3"),
        lambda *a: {"action": "download", "role": "link", "name": "Download installer"},
        settings())
    result = service.run(ToolContext(OWNER, SENDER, "m1", "Download the installer"),
                         "Download the installer")
    assert result["status"] == "blocked"

    def crash_transport(*args):
        return {"action": "navigate", "url": "https://news.example.com/article"}

    crashing = FakeRuntime()
    crashing.page = BrowserObservation("", "", "", ())
    service = BrowserTaskService(crashing, BrowserStore(tmp_path / "r2.sqlite3"),
                                 crash_transport, settings())
    result = service.run(ToolContext(OWNER, SENDER, "m2", "Open the article"),
                         "Open the article")
    assert result["status"] == "failed"
    assert "crash" in result["answer"].lower() or "unavailable" in result["answer"].lower()


def test_relationship_and_group_text_never_look_like_silent_browser_work():
    assert looks_like_browser_request("Open https://news.example.com/article")
    assert looks_like_browser_request("Hey Rally, check the airline site")
    assert looks_like_browser_request("Hey Rally, search for italian in midtown")
    assert looks_like_browser_request("Hey Rally, reserve a table at Carbone")
    assert not looks_like_browser_request("Hey Rally, remind me to call mom")
    assert not looks_like_browser_request("dinner Friday in Midtown")
    assert not looks_like_browser_request("forget that I live in Atlanta")
    assert not looks_like_browser_request("how do I implement binary search")
