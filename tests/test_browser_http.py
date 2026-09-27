import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models import PlanFacts
from app.orchestrator import RallyService
from app.store import Store


NOW = datetime(2026, 9, 26, 21, tzinfo=timezone.utc)
OWNER = "iMessage;-;owner"
SENDER = "+15555550123"
GROUP = "iMessage;+;HackGT13"
ADMIN = "W6SWqB8dA_5f5SUS2ms-CNu0WhxFLBL34ff2A7vfVBQ"
TOKEN = "secret"


class QuietAgent:
    def extract(self, messages, previous):
        return PlanFacts()

    def answer_direct(self, request, facts, messages):
        return "group should not see browser work"


class FakeRuntime:
    def __init__(self, installed=True):
        self.installed = installed
        self.running = False
        self.starts = 0
        self.proxy_url = None

    def status(self):
        return {"running": self.running, "installed": self.installed,
                "profile": "configured"}

    def start(self):
        if not self.installed:
            raise RuntimeError("Chromium is not installed")
        self.running = True
        self.starts += 1
        return self.status()

    def stop(self):
        self.running = False
        return self.status()


def group_app(tmp_path, runtime=None, inbound=None, enabled=True):
    store = Store(tmp_path / "r.sqlite3")
    sent = []
    service = RallyService(store, QuietAgent(), lambda facts: [],
                           lambda chat, text: sent.append((chat, text)),
                           allowed_chat_ids={GROUP})
    app = create_app(service, webhook_token=TOKEN, schedule=False,
                     browser_runtime=runtime, browser_inbound=inbound,
                     browser_admin_token=ADMIN if enabled else "",
                     browser_enabled=enabled)
    return app, service, sent


def loopback(app, method, path, **kwargs):
    async def go():
        transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            return await getattr(client, method)(path, **kwargs)
    return asyncio.run(go())


def test_browser_routes_require_admin_token_and_loopback(tmp_path):
    runtime = FakeRuntime()
    app, _, _ = group_app(tmp_path, runtime=runtime)
    remote = TestClient(app)
    assert loopback(app, "get", "/browser/status").status_code == 403
    assert loopback(app, "get", "/browser/status",
                    headers={"X-Rally-Admin-Token": "nope"}).status_code == 403
    assert remote.get("/browser/status", headers={"X-Rally-Admin-Token": ADMIN}).status_code == 403
    status = loopback(app, "get", "/browser/status",
                      headers={"X-Rally-Admin-Token": ADMIN})
    assert status.status_code == 200
    assert status.json()["running"] is False
    assert "cookie" not in status.text.lower()
    start = loopback(app, "post", "/browser/start",
                     headers={"X-Rally-Admin-Token": ADMIN})
    assert start.status_code == 200
    assert start.json()["running"] is True
    assert runtime.starts == 1
    stop = loopback(app, "post", "/browser/stop",
                    headers={"X-Rally-Admin-Token": ADMIN})
    assert stop.json()["running"] is False


def test_disabled_or_missing_install_is_a_clear_status(tmp_path):
    app, _, _ = group_app(tmp_path, runtime=FakeRuntime(), enabled=False)
    assert loopback(app, "get", "/browser/status",
                    headers={"X-Rally-Admin-Token": ADMIN}).status_code == 404

    missing = FakeRuntime(installed=False)
    app, _, _ = group_app(tmp_path, runtime=missing)
    started = loopback(app, "post", "/browser/start",
                       headers={"X-Rally-Admin-Token": ADMIN})
    assert started.status_code == 503
    assert "not installed" in started.json()["detail"].lower()
