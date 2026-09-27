from datetime import datetime, timezone

from app.browser.agent import BrowserTaskService, ToolContext
from app.browser.runtime import BrowserObservation
from app.browser.store import BrowserStore


OWNER = "iMessage;-;owner"
SENDER = "+15555550123"
NOW = datetime(2026, 9, 26, 21, tzinfo=timezone.utc)


class FakeRuntime:
    def __init__(self):
        self.actions = []
        self.page = BrowserObservation(
            "https://news.example.com/checkout", "Checkout", "Name Ada",
            ({"role": "button", "name": "Purchase now"},),
        )
        self.fail_after = None

    def observe(self, *, chat_id, authenticated):
        return self.page

    def act(self, *, chat_id, authenticated, action):
        if self.fail_after == "timeout":
            raise TimeoutError("navigation timed out")
        self.actions.append(action)
        self.page = BrowserObservation("https://news.example.com/submit", "Receipt",
                                       "Order confirmed. Confirmation ABC-1.", ())
        return {"status": "ok"}


def settings():
    return type("S", (), {
        "browser_enabled": True,
        "browser_owner_chat_id": OWNER,
        "browser_owner_sender_id": SENDER,
        "browser_max_actions": 4,
        "browser_max_text_chars": 6000,
    })()


def owner_context(message_id="m1", sender_id=SENDER):
    return ToolContext(OWNER, sender_id, message_id, "Click purchase")


def pending_service(tmp_path, runtime=None):
    runtime = runtime or FakeRuntime()
    service = BrowserTaskService(
        runtime, BrowserStore(tmp_path / "r.sqlite3"),
        lambda *a: {"action": "click_link", "role": "button", "name": "Purchase now"},
        settings())
    result = service.run(owner_context(), "Click purchase")
    return service, runtime, result


def test_owner_can_approve_exact_current_action_once(tmp_path):
    service, runtime, pending = pending_service(tmp_path)
    approved = service.resolve_approval(owner_context("m2"), pending["code"], True)
    assert approved["status"] == "complete"
    assert "ABC-1" in approved["answer"]
    assert runtime.actions == [{"action": "click_link", "role": "button", "name": "Purchase now"}]
    again = service.resolve_approval(owner_context("m3"), pending["code"], True)
    assert again is None or again["status"] in {"failed", "uncertain"}
    assert runtime.actions == [{"action": "click_link", "role": "button", "name": "Purchase now"}]


def test_wrong_actor_or_token_is_ignored(tmp_path):
    service, runtime, pending = pending_service(tmp_path)
    assert service.resolve_approval(owner_context("m2", sender_id="intruder"),
                                    pending["code"], True) is None
    assert service.resolve_approval(owner_context("m3"), "NOPE00", True) is None
    assert runtime.actions == []


def test_stale_values_invalidate_approval(tmp_path):
    runtime = FakeRuntime()
    service, runtime, pending = pending_service(tmp_path, runtime)
    runtime.page = BrowserObservation(
        "https://news.example.com/checkout", "Checkout", "Name Ada",
        ({"role": "button", "name": "Purchase now"},),
    )
    runtime.page = BrowserObservation(
        "https://news.example.com/checkout", "Checkout", "Name edited",
        ({"role": "button", "name": "Purchase now"},),
    )
    result = service.resolve_approval(owner_context("m2"), pending["code"], True)
    assert result["status"] in {"failed", "stale"}
    assert runtime.actions == []


def test_timeout_after_commit_is_uncertain_and_not_retried(tmp_path):
    runtime = FakeRuntime()
    runtime.fail_after = "timeout"
    service, runtime, pending = pending_service(tmp_path, runtime)
    result = service.resolve_approval(owner_context("m2"), pending["code"], True)
    assert result["status"] == "uncertain"
    assert runtime.actions == []
    again = service.resolve_approval(owner_context("m3"), pending["code"], True)
    assert again is None or again["status"] == "uncertain"
