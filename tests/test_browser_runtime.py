import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.browser.chrome import persistent_launch_kwargs
from app.browser.runtime import (
    BrowserObservation,
    BrowserRuntime,
    bound_text,
    classify_download,
    is_commitment_control,
    is_secret_fill,
    rewrite_blocked_search_url,
    search_url,
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
        self.current = {}
        self.persistent_chats = set()

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
        if kind == "wait_for_human":
            return {"status": "waiting", "url": self.current.get(chat_id, {}).get("url", "")}
        if kind == "fill" and "password" in (action.get("name") or "").lower():
            return {"status": "blocked", "reason": "credentials must be entered on the Mac"}
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
    cleaned = validate_action({
        "action": "click_link", "selector": "#x", "role": "link", "name": "Go",
    })
    assert cleaned == {"action": "click_link", "role": "link", "name": "Go"}
    cleaned = validate_action({
        "action": "download", "path": "/etc/passwd", "name": "report.pdf",
    })
    assert cleaned == {"action": "download", "name": "report.pdf"}
    assert "path" not in cleaned
    assert validate_action({"action": "inspect"})["action"] == "inspect"
    assert validate_action({"action": "search", "query": "italian midtown"})["action"] == "search"
    assert validate_action({"action": "wait_for_human", "reason": "sign in"})["action"] == "wait_for_human"
    assert "maps/search" in search_url("italian midtown")
    assert "google.com/search" in search_url("italian midtown", hosted=True)
    assert is_secret_fill("textbox", "Password")
    assert not is_secret_fill("textbox", "Party size")


def test_local_search_rewrites_google_sorry_to_maps():
    sorry = validate_action({
        "action": "navigate",
        "url": "https://www.google.com/sorry/index?continue=https://www.google.com/search%3Fq%3Ditalian+midtown",
    })
    assert "maps/search" in sorry["url"]
    assert "italian" in sorry["url"].lower() or "midtown" in sorry["url"].lower()
    web = rewrite_blocked_search_url("https://www.google.com/search?q=tacos+atlanta")
    assert "maps/search" in web
    assert "tacos" in web.lower()
    hosted = rewrite_blocked_search_url(
        "https://www.google.com/search?q=tacos+atlanta", hosted=True)
    assert hosted.startswith("https://www.google.com/search")


def test_stealth_launch_kwargs_disable_automation_flag():
    kwargs = persistent_launch_kwargs(
        downloads_path="data/browser/downloads", headed=True, channel=None)
    assert "--disable-blink-features=AutomationControlled" in kwargs["args"]
    assert "--enable-automation" in kwargs["ignore_default_args"]
    assert kwargs["headless"] is False


def test_validate_action_ignores_unknown_planner_fields():
    cleaned = validate_action({
        "action": "navigate",
        "url": "https://example.com",
        "reason": "open the demo site",
        "timeout_seconds": 12,
        "extra": True,
    })
    assert cleaned == {"action": "navigate", "url": "https://example.com"}


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


class RecoveringDriver(ScriptedDriver):
    def __init__(self):
        super().__init__()
        self.crash_next = False

    def start(self, **kwargs):
        super().start(**kwargs)
        self.crash_next = False

    def observe(self, chat_id, authenticated):
        if self.crash_next:
            raise RuntimeError("TargetClosedError: browser has been closed")
        return super().observe(chat_id, authenticated)


def test_runtime_observe_recovers_after_fake_driver_crash(tmp_path):
    driver = RecoveringDriver()
    runtime = BrowserRuntime(tmp_path / "profile", tmp_path / "downloads",
                             None, 6000, driver=driver, resolver=public_resolver)
    runtime.start()
    driver.crash_next = True
    seen = runtime.observe(chat_id="iMessage;-;owner", authenticated=True)
    assert seen.url == ""
    assert driver.closed is True
    assert driver.crash_next is False
    assert runtime.status()["running"] is True


def test_runtime_serializes_work_on_one_worker_thread(tmp_path):
    seen = []

    class ThreadDriver(ScriptedDriver):
        def start(self, **kwargs):
            seen.append(("start", threading.get_ident()))
            super().start(**kwargs)

        def observe(self, chat_id, authenticated):
            seen.append(("observe", threading.get_ident()))
            return super().observe(chat_id, authenticated)

        def act(self, chat_id, authenticated, action):
            seen.append(("act", threading.get_ident()))
            return super().act(chat_id, authenticated, action)

        def stop(self):
            seen.append(("stop", threading.get_ident()))
            super().stop()

    runtime = BrowserRuntime(tmp_path / "profile", tmp_path / "downloads",
                             None, 6000, driver=ThreadDriver(), resolver=public_resolver)
    runtime.start()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [
            pool.submit(runtime.observe, chat_id="iMessage;-;owner", authenticated=True)
            for _ in range(3)
        ]
        futs.append(pool.submit(
            runtime.act, chat_id="iMessage;-;owner", authenticated=True,
            action={"action": "inspect"}))
        for fut in futs:
            fut.result()
    runtime.recover()
    runtime.stop()
    idents = {ident for _name, ident in seen}
    assert len(idents) == 1
    assert threading.get_ident() not in idents
    assert {name for name, _ident in seen} >= {"start", "observe", "act", "stop"}


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
    secret = runtime.act(chat_id="owner", authenticated=True,
                        action={"action": "fill", "role": "textbox", "name": "Password",
                                "text": "hunter2"})
    assert secret["status"] == "blocked"
    assert "credential" in secret["reason"].lower()
    waited = runtime.act(chat_id="owner", authenticated=True,
                         action={"action": "wait_for_human", "timeout_seconds": 0,
                                 "reason": "sign in"})
    assert waited["status"] == "waiting"
    assert not any(item[2].get("text") == "hunter2" for item in driver.history)
