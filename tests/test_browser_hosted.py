from app.browser.hosted import BrowserbaseClient, BrowserUseClient, compose_browser_use_task
from app.browser.runtime import BrowserRuntime, search_url
from tests.test_browser_runtime import ScriptedDriver


def hosted_resolver(host, port, type=0):
    if host in {"news.example.com", "example.com", "www.google.com", "google.com"}:
        return [(2, 1, 6, "", ("93.184.216.34", port))]
    raise OSError("unknown host")


class FakeHosted:
    def __init__(self, connect_url="wss://connect.browserbase.com/s1"):
        self.created = []
        self.released = []
        self.connect_url = connect_url

    def create_session(self):
        self.created.append("s1")
        return {"id": "s1", "connect_url": self.connect_url}

    def release(self):
        self.released.append("s1")


def test_browserbase_client_parses_connect_url_and_omits_key_from_errors():
    calls = []

    def transport(method, url, api_key, body):
        calls.append((method, url, body))
        assert api_key == "secret-key"
        return {"id": "sess-1", "connectUrl": "wss://connect.browserbase.com/sess-1"}

    client = BrowserbaseClient("secret-key", "proj-1", transport=transport)
    session = client.create_session()
    assert session == {"id": "sess-1", "connect_url": "wss://connect.browserbase.com/sess-1"}
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/v1/sessions")
    assert calls[0][2]["projectId"] == "proj-1"
    assert calls[0][2]["browserSettings"]["solveCaptchas"] is True
    client.release()
    assert client.session_id is None
    assert any(call[1].endswith("/v1/sessions/sess-1") for call in calls)


def test_search_and_open_use_hosted_client_when_configured(tmp_path):
    hosted = FakeHosted()
    driver = ScriptedDriver()
    runtime = BrowserRuntime(tmp_path / "profile", tmp_path / "downloads",
                             None, 6000, driver=driver, resolver=hosted_resolver,
                             hosted=hosted)
    runtime.start()
    assert runtime.status()["backend"] == "browserbase"
    runtime.act(chat_id="iMessage;-;owner", authenticated=True,
                action={"action": "search", "query": "italian midtown"})
    opened = runtime.act(chat_id="iMessage;-;owner", authenticated=True,
                         action={"action": "navigate",
                                 "url": "https://news.example.com/article"})
    assert opened["status"] == "ok"
    assert hosted.created == ["s1"]
    urls = [item[2]["url"] for item in driver.history if item[2].get("action") == "navigate"]
    assert urls[0].startswith("https://www.google.com/search")
    assert "google.com/search" in search_url("italian midtown", hosted=True)
    assert "maps/search" not in urls[0]
    assert urls[1] == "https://news.example.com/article"
    runtime.stop()
    assert hosted.released == ["s1"]


def test_search_uses_maps_when_local_to_avoid_google_captcha(tmp_path):
    driver = ScriptedDriver()
    runtime = BrowserRuntime(tmp_path / "profile", tmp_path / "downloads",
                             None, 6000, driver=driver, resolver=hosted_resolver)
    runtime.start()
    assert runtime.status()["backend"] == "local"
    runtime.act(chat_id="iMessage;-;owner", authenticated=True,
                action={"action": "search", "query": "italian midtown"})
    assert "maps/search" in driver.history[0][2]["url"]
    runtime.act(chat_id="iMessage;-;owner", authenticated=True,
                action={"action": "navigate",
                        "url": "https://www.google.com/search?q=pizza+decatur"})
    assert "maps/search" in driver.history[1][2]["url"]
    runtime.stop()


def test_browserbase_infers_project_id_when_omitted():
    calls = []

    def transport(method, url, api_key, body):
        calls.append((method, url, body))
        if url.endswith("/v1/projects"):
            return [{"id": "proj-inferred", "name": "Default"}]
        return {"id": "sess-2", "connectUrl": "wss://connect.browserbase.com/sess-2"}

    client = BrowserbaseClient("secret-key", transport=transport)
    session = client.create_session()
    assert session["id"] == "sess-2"
    assert any(call[0] == "GET" and call[1].endswith("/v1/projects") for call in calls)
    create = next(call for call in calls if call[0] == "POST" and call[1].endswith("/v1/sessions"))
    assert create[2]["projectId"] == "proj-inferred"
    assert create[2]["proxies"] is True
    assert create[2]["browserSettings"]["solveCaptchas"] is True


def test_browser_use_client_runs_vendor_agent_and_omits_key_from_errors():
    calls = []

    def transport(method, url, api_key, body):
        calls.append((method, url, body))
        assert api_key == "secret-use-key"
        if method == "POST":
            assert "WAIT_FOR_HUMAN" in body["task"]
            assert "example.com" in body["task"]
            assert body["model"] == "grok-4.5"
            return {"id": "run-1", "status": "running"}
        return {"id": "run-1", "status": "finished",
                "result": "Example Domain", "url": "https://example.com"}

    client = BrowserUseClient("secret-use-key", transport=transport, sleeper=lambda _: None)
    result = client.run_task("Open https://example.com")
    assert result["status"] == "ok"
    assert result["answer"] == "Example Domain"
    assert result["url"] == "https://example.com"
    assert result["waiting"] is False
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/api/v4/runs")
    assert any(call[0] == "GET" and call[1].endswith("/api/v4/runs/run-1") for call in calls)
    assert "secret-use-key" not in compose_browser_use_task("Open https://example.com")


def test_runtime_reports_browser_use_backend_when_vendor_configured(tmp_path):
    runtime = BrowserRuntime(
        tmp_path / "profile", tmp_path / "downloads", None, 6000,
        vendor=object())
    assert runtime.status()["backend"] == "browser-use"
