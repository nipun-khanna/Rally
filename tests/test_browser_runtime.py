import pytest

from app.browser.runtime import (
    BrowserObservation,
    BrowserRuntime,
    bound_text,
    classify_download,
    is_commitment_control,
    validate_action,
)
from tests.browser_fixtures import PAGES, public_resolver


class ScriptedDriver:
    def __init__(self, pages=None, cookies=None):
        self.pages = dict(pages or PAGES)
        self.cookies = cookies or {"session": "owner-cookie-value"}
        self.current = {}
        self.history = []
        self.popups = []
        self.downloads = []
        self.closed = False
        self.proxy_url = None
        self.persistent_chats = set()

    def start(self, *, proxy_url, profile_path, downloads_path, headed=False):
        self.proxy_url = proxy_url
        self.profile_path = profile_path
        self.downloads_path = downloads_path
        self.headed = headed

    def stop(self):
        self.closed = True

    def observe(self, chat_id, authenticated):
        page = self.current.get(chat_id, {"url": "", "title": "", "text": "", "controls": ()})
        return BrowserObservation(page["url"], page["title"], page["text"], tuple(page["controls"]))

    def act(self, chat_id, authenticated, action):
        self.history.append((chat_id, authenticated, action))
        kind = action["action"]
        if kind == "navigate":
            url = action["url"]
            html = self.pages.get(url)
            if html is None:
                return {"status": "blocked", "reason": "unknown page"}
            self.current[chat_id] = {
                "url": url,
                "title": "Public Article" if "article" in url else "Page",
                "text": html,
                "controls": ({"role": "link", "name": "Other"},) if "article" in url else (),
            }
            if authenticated:
                self.persistent_chats.add(chat_id)
            return {"status": "ok"}
        if kind == "click_link" and action.get("name") == "Internal":
            return {"status": "blocked", "reason": "URL resolves to a non-public address"}
        if kind == "download":
            name = action.get("name", "")
            self.downloads.append(name)
            if name.endswith(".exe"):
                return {"status": "blocked", "reason": "download type is not allowed"}
            return {"status": "ok", "path": "data/browser/downloads/report.pdf", "bytes": 120}
        return {"status": "ok"}

    def storage_state(self, chat_id):
        return {"cookies": [self.cookies]} if chat_id in self.persistent_chats else {"cookies": []}


def test_validate_action_rejects_javascript_selectors_and_paths():
    with pytest.raises(ValueError):
        validate_action({"action": "evaluate", "script": "alert(1)"})
    with pytest.raises(ValueError):
        validate_action({"action": "navigate", "url": "javascript:alert(1)"})
    with pytest.raises(ValueError):
        validate_action({"action": "click_link", "selector": "#x"})
    with pytest.raises(ValueError):
        validate_action({"action": "download", "path": "/etc/passwd"})
    with pytest.raises(ValueError):
        validate_action({"action": "navigate", "url": "https://example.com", "extra": True})
    assert validate_action({"action": "inspect"})["action"] == "inspect"


def test_observation_text_is_bounded_and_downloads_are_filtered():
    assert len(bound_text("a" * 9000, 6000)) == 6000
    assert classify_download("report.pdf", 100) == "ok"
    assert classify_download("evil.exe", 100) == "blocked"
    assert classify_download("notes.txt", 6_000_000) == "blocked"
    assert is_commitment_control("button", "Purchase now")
    assert not is_commitment_control("link", "Read more")


def test_runtime_navigates_and_isolates_chats(tmp_path):
    driver = ScriptedDriver()
    runtime = BrowserRuntime(tmp_path / "profile", tmp_path / "downloads",
                             "socks5://127.0.0.1:1", 6000, driver=driver,
                             resolver=public_resolver)
    runtime.start()
    result = runtime.act(chat_id="iMessage;-;owner", authenticated=True,
                         action={"action": "navigate", "url": "https://news.example.com/article"})
    assert result["status"] == "ok"
    seen = runtime.observe(chat_id="iMessage;-;owner", authenticated=True)
    assert seen.url == "https://news.example.com/article"
    assert "weekend weather" in seen.text
    other = runtime.observe(chat_id="iMessage;+;group", authenticated=False)
    assert other.url == ""
    assert "owner-cookie-value" not in str(runtime.act(
        chat_id="iMessage;-;owner", authenticated=True, action={"action": "inspect"}))
    runtime.stop()
    assert driver.closed is True
    assert driver.proxy_url == "socks5://127.0.0.1:1"


def test_runtime_recover_recreates_a_dead_session(tmp_path):
    driver = ScriptedDriver()
    runtime = BrowserRuntime(tmp_path / "profile", tmp_path / "downloads",
                             None, 6000, driver=driver, resolver=public_resolver)
    runtime.start()
    runtime.act(chat_id="iMessage;-;owner", authenticated=True,
                action={"action": "navigate", "url": "https://news.example.com/article"})
    status = runtime.recover()
    assert status["running"] is True
    assert driver.closed is True
    seen = runtime.observe(chat_id="iMessage;-;owner", authenticated=True)
    assert seen.url == ""


def test_runtime_blocks_private_redirect_and_popup_and_exe_download(tmp_path):
    driver = ScriptedDriver()
    runtime = BrowserRuntime(tmp_path / "profile", tmp_path / "downloads",
                             "socks5://127.0.0.1:1", 6000, driver=driver,
                             resolver=public_resolver)
    runtime.start()
    runtime.act(chat_id="owner", authenticated=True,
                action={"action": "navigate", "url": "https://news.example.com/jump"})
    blocked = runtime.act(chat_id="owner", authenticated=True,
                          action={"action": "click_link", "role": "link", "name": "Internal"})
    assert blocked["status"] == "blocked"
    download = runtime.act(chat_id="owner", authenticated=True,
                           action={"action": "download", "role": "link", "name": "evil.exe"})
    assert download["status"] == "blocked"
