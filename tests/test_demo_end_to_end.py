"""FastAPI demo path: synthetic group webhook, public discovery, dry-run Vapi, one outcome.

Uses a temp SQLite file, a fake sender, schedule=False, and an in-memory dialer.
Nothing in this module texts BlueBubbles, posts to Vapi, or deploys the portal.
"""

import json
import socket
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.browser.agent import BrowserTaskService, PublicRestaurantLookup, page_for_venue
from app.browser.handler import BrowserInbound
from app.browser.runtime import BrowserObservation
from app.browser.store import BrowserStore
from app.group_turns import GroupTurnStore
from app.main import create_app
from app.models import ChatMessage, PlanFacts
from app.orchestrator import RallyService
from app.portal_store import PortalStore
from app.store import Store
from app.voice.call_store import CallAttemptStore
from app.voice.caller import ReservationCaller
from app.voice.handler import ReservationCallInbound


NOW = datetime(2026, 9, 27, 18, tzinfo=timezone.utc)
GROUP = "iMessage;+;demo-e2e-group"
OTHER = "iMessage;+;demo-e2e-other"
UNLISTED = "iMessage;+;demo-e2e-unlisted"
SENDER = "+15555550123"
TOKEN = "demo-webhook-token"
PRIVATE = "sentinel-private-plan-note-9f3c"
CALL_ID = "019a9046-121e-766d-bd1f-84f3ccc309c1"
PHONE = "+12125550144"
SOURCE = "https://carbone.example/contact"
BROWSER_PHONE = "+12125550177"
BROWSER_SOURCE = "https://carbone.example/visit"
PARTIAL = (
    "Hey Rally, reserve a table at Carbone for 4 on October 2, 2026 at 7:30pm "
    "Eastern Time under Tarun"
)
COMPLETE = "Hey Rally, on behalf of Ada callback (404) 555-0199"
FULL = (
    "Hey Rally, reserve a table at Carbone for 4 on October 2, 2026 at 7:30pm "
    "Eastern Time under Tarun on behalf of Ada callback (404) 555-0199"
)
HOST = (
    "You're booked at Carbone for 4 on October 2, 2026 at 7:30pm under Tarun. "
    "The confirmation code is AB12."
)
SEARCH_HTML = (
    '<a class="result__a" href="https://duckduckgo.com/l/?uddg='
    'https%3A%2F%2Fcarbone.example%2F">Carbone</a>'
    '<a class="result__snippet">Carbone New York. Phone (212) 555-0199.</a>'
)
HOMEPAGE = '<html>Carbone New York restaurant. <a href="/contact">Contact</a></html>'
CONTACT = "Carbone New York. Reservations (212) 555-0144."


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("outbound network is blocked")

    monkeypatch.setattr(socket, "create_connection", blocked)


class QuietAgent:
    def __init__(self):
        self.direct = []

    def extract(self, messages, previous):
        return PlanFacts()

    def answer_direct(self, request, facts, messages):
        self.direct.append((request, [item.text for item in messages]))
        return "pong"


class InMemoryVapi:
    """Records the create-call body. Does not open a socket."""

    def __init__(self):
        self.placed = []
        self.prepared = []
        self.evidence = {
            "id": CALL_ID, "status": "queued", "structured": None,
            "transcript": "", "messages": [],
        }

    def ready(self):
        return True

    def allows(self, number):
        return isinstance(number, str) and number.startswith("+") and number != "+16785991244"

    def prepare_call(self, *, to_number, assistant_overrides=None):
        body = {
            "assistantId": "assistant",
            "phoneNumberId": "phone",
            "customer": {"number": to_number},
            "assistantOverrides": assistant_overrides,
        }
        self.prepared.append(body)
        return body

    def place_call(self, *, to_number, assistant_overrides=None):
        self.placed.append({"to_number": to_number, "assistant_overrides": assistant_overrides})
        return {"id": CALL_ID, "status": "queued"}

    def get_call(self, call_id):
        assert call_id == CALL_ID
        return {"id": call_id, "status": self.evidence["status"]}

    def get_call_evidence(self, call_id):
        assert call_id == CALL_ID
        return dict(self.evidence)


class RecordingRuntime:
    def __init__(self, page):
        self.page = page
        self.calls = []

    def status(self):
        return {"running": True, "installed": True, "profile": "configured"}

    def start(self, headed=False):
        return self.status()

    def stop(self):
        return self.status()

    def act(self, *, chat_id, authenticated, action):
        self.calls.append(("act", chat_id, authenticated, dict(action)))
        return {"status": "ok"}

    def observe(self, *, chat_id, authenticated):
        self.calls.append(("observe", chat_id, authenticated, None))
        return self.page


def payload(chat, text, ident, sender=SENDER):
    return {"type": "new-message", "data": {
        "guid": ident, "text": text, "isFromMe": False,
        "dateCreated": int(NOW.timestamp() * 1000),
        "handle": {"address": sender},
        "chats": [{"guid": chat}],
    }}


def public_fetch(seen):
    def fetch(url):
        seen.append(url)
        assert PRIVATE not in url
        if "duckduckgo.com" in url:
            assert "carbone" in url.casefold()
            assert "555-0199" not in url
            return SEARCH_HTML, url
        if url.rstrip("/").endswith("/contact"):
            return CONTACT, SOURCE
        if "carbone.example" in url:
            return HOMEPAGE, "https://carbone.example/"
        raise AssertionError(url)

    return fetch


def snapshots(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    rows = [dict(row) for row in db.execute(
        "SELECT chat_id, state, terms_json, authorization_message_id, call_id "
        "FROM restaurant_call_snapshots ORDER BY created_at")]
    db.close()
    return rows


def outbox(path, kind=None):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    if kind:
        rows = db.execute("SELECT * FROM outbox WHERE kind=?", (kind,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM outbox").fetchall()
    db.close()
    return [dict(row) for row in rows]


def build(tmp_path, *, lookup, dry_run, browser=None, web_answer=None, agent=None):
    path = tmp_path / "rally.sqlite3"
    sent = []
    store = Store(path)
    store.add_message(ChatMessage(
        "private-row", GROUP, SENDER, PRIVATE, NOW, False))
    turns = GroupTurnStore(tmp_path / "turns.sqlite3")
    agent = agent or QuietAgent()
    service = RallyService(
        store, agent, lambda facts: [],
        lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={GROUP, OTHER},
        group_turns=turns,
        web_answer_fn=web_answer,
        defer_heavy_work=False,
        history_fn=None,
    )
    attempts = CallAttemptStore(path)
    vapi = InMemoryVapi()
    caller = ReservationCaller(
        plan_store=store, vapi=vapi, phone_lookup=lookup, dry_run=dry_run,
        snapshots=attempts, owner_name="", callback_number="")
    inbound = ReservationCallInbound(
        caller, lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={GROUP, OTHER}, group_turns=turns, call_store=attempts)
    portal = PortalStore(path)
    browser_inbound = None
    runtime = None
    if browser is not None:
        runtime, browser_inbound = browser
    app = create_app(
        service, webhook_token=TOKEN, schedule=False, portal_store=portal,
        history_client=None, history_enabled=True,
        reservation_call_inbound=inbound,
        browser_runtime=runtime, browser_inbound=browser_inbound,
        browser_enabled=browser is not None, browser_admin_token="demo-admin")
    client = TestClient(app)
    return {
        "client": client, "sent": sent, "vapi": vapi, "path": path, "inbound": inbound,
        "service": service, "portal": portal, "store": store, "agent": agent,
    }


def post(env, body, token=TOKEN):
    return env["client"].post(f"/webhooks/bluebubbles?token={token}", json=body)


def test_malformed_repeat_wrong_chat_then_one_dry_run_payload(tmp_path):
    seen = []

    def reader(*_args, **_kwargs):
        raise AssertionError("web discovery already verified the page")

    lookup = PublicRestaurantLookup(fetch=public_fetch(seen), browser_reader=reader).find
    env = build(tmp_path, lookup=lookup, dry_run=True)
    client = env["client"]
    try:
        assert client.post("/webhooks/bluebubbles", json=payload(GROUP, FULL, "no-token")).status_code == 403
        assert client.post("/webhooks/bluebubbles?token=nope", json=payload(GROUP, FULL, "bad-token")).status_code == 403
        assert post(env, ["not-a-message"]).status_code == 422
        assert post(env, {"type": "updated-message", "data": {}}).json() == {"accepted": False}
        assert post(env, {"type": "new-message", "data": {"text": 5, "isFromMe": False}}).json()["accepted"] is False
        assert post(env, payload(UNLISTED, FULL, "unlisted")).json()["accepted"] is False
        assert seen == []
        assert env["vapi"].prepared == []
        assert env["vapi"].placed == []

        first = post(env, payload(GROUP, PARTIAL, "ask"))
        assert first.status_code == 200
        assert first.json() == {"accepted": True}
        assert any(url.endswith("/contact") for url in seen)
        assert PHONE in env["sent"][-1][1]
        assert SOURCE in env["sent"][-1][1]
        assert "+12125550199" not in env["sent"][-1][1]
        assert not env["sent"][-1][1].startswith("Rally:")
        assert "owner name" in env["sent"][-1][1].lower()
        assert "callback" in env["sent"][-1][1].lower()
        assert "will not" in env["sent"][-1][1].lower()
        saved = snapshots(env["path"])
        assert len(saved) == 1
        terms = json.loads(saved[0]["terms_json"])
        assert saved[0]["state"] == "collecting"
        assert terms["venue"] == "Carbone"
        assert terms["party_size"] == 4
        assert terms["date"] == "2026-10-02"
        assert terms["time"] == "19:30"
        assert terms["timezone"] == "America/New_York"
        assert terms["guest_name"] == "Tarun"
        assert terms["destination_phone"] == PHONE
        assert terms["destination_source"] == SOURCE
        assert terms["owner_name"] == ""
        assert terms["callback_number"] == ""
        assert PRIVATE not in json.dumps(terms)

        before = len(env["sent"])
        fetches = list(seen)
        assert post(env, payload(GROUP, PARTIAL, "ask")).json()["accepted"] is True
        assert len(env["sent"]) == before
        assert seen == fetches
        assert len(env["portal"].list_messages(GROUP)) == 1
        archived = env["portal"].list_messages(GROUP)[0]
        assert archived["message_id"] == "ask"
        assert archived["sender_id"] == SENDER

        assert post(env, payload(GROUP, COMPLETE, "terms")).json()["accepted"] is True
        ready = json.loads(snapshots(env["path"])[0]["terms_json"])
        assert snapshots(env["path"])[0]["state"] == "awaiting_authorization"
        assert ready["owner_name"] == "Ada"
        assert ready["callback_number"] == "+14045550199"
        assert "reply yes" in env["sent"][-1][1].lower()
        assert not env["sent"][-1][1].startswith("Rally:")
        assert seen == fetches

        assert post(env, payload(OTHER, "Rally, yes", "other-yes")).json()["accepted"] is True
        assert env["vapi"].prepared == []
        assert env["vapi"].placed == []
        assert snapshots(env["path"])[0]["state"] == "awaiting_authorization"
        assert snapshots(env["path"])[0]["chat_id"] == GROUP
        assert all(row["chat_id"] != OTHER for row in snapshots(env["path"]))

        assert post(env, payload(GROUP, "yes, party of 6", "change")).json()["accepted"] is True
        changed = json.loads(snapshots(env["path"])[0]["terms_json"])
        assert changed["party_size"] == 6
        assert env["vapi"].prepared == []
        assert "reply yes" in env["sent"][-1][1].lower()

        assert post(env, payload(GROUP, "yes", "yes-1")).json()["accepted"] is True
        assert env["vapi"].placed == []
        assert len(env["vapi"].prepared) == 1
        body = env["vapi"].prepared[0]
        assert body["customer"]["number"] == PHONE
        opening = body["assistantOverrides"]["firstMessage"]
        assert opening.startswith("I am calling on behalf of Ada")
        assert "for 6" in opening
        assert PRIVATE not in json.dumps(body)
        assert "local-imessage-account" not in json.dumps(body)
        assert "dry-run" in env["sent"][-1][1].lower()
        assert "not placed" in env["sent"][-1][1].lower()
        assert not env["sent"][-1][1].startswith("Rally:")
        authorized = snapshots(env["path"])[0]
        assert authorized["state"] == "authorized"
        assert authorized["authorization_message_id"] == "yes-1"
        assert authorized["call_id"] is None

        assert post(env, payload(GROUP, "yes", "yes-1")).json()["accepted"] is True
        assert len(env["vapi"].prepared) == 1
        assert env["vapi"].placed == []
        assert env["inbound"].reconcile_calls() == 0
        env["service"].deliver_pending()
        assert outbox(env["path"], "voice_call_result") == []
        assert all(not text.startswith("Rally:") for _chat, text in env["sent"])
        assert env["path"].is_relative_to(tmp_path)
    finally:
        client.close()


def test_public_browser_discovery_does_not_open_the_owner_profile(tmp_path):
    page = BrowserObservation(
        BROWSER_SOURCE, "Carbone",
        "Carbone New York. Call (212) 555-0177 for a table.", ())
    runtime = RecordingRuntime(page)
    seen = []

    def fetch(url):
        seen.append(url)
        assert PRIVATE not in url
        return "", ""

    lookup = PublicRestaurantLookup(
        fetch=fetch, browser_reader=lambda venue, location="": page_for_venue(runtime, venue),
    ).find
    env = build(tmp_path, lookup=lookup, dry_run=True)
    try:
        response = post(env, payload(GROUP, PARTIAL, "browser-ask"))
        assert response.json()["accepted"] is True
        assert BROWSER_PHONE in env["sent"][-1][1]
        assert BROWSER_SOURCE in env["sent"][-1][1]
        assert seen and all("duckduckgo.com" in url for url in seen)
        flags = [(call[0], call[2]) for call in runtime.calls]
        assert flags == [("act", False), ("observe", False)], flags
        query = runtime.calls[0][3]["query"]
        assert "Carbone" in query
        assert PRIVATE not in query
    finally:
        env["client"].close()


def test_browser_search_web_answer_and_ordinary_reply_have_no_prefix(tmp_path):
    runtime = RecordingRuntime(BrowserObservation(
        "https://example.com/", "Example Domain",
        "Example Domain is a public placeholder page.", ()))
    prompts = []

    def transport(_schema, _prompt, data):
        prompts.append(data)
        assert PRIVATE not in json.dumps(data)
        return {"action": "complete", "answer": "Example Domain is a public placeholder page."}

    settings = type("S", (), {
        "browser_enabled": True,
        "browser_owner_chat_id": "iMessage;-;demo-owner",
        "browser_owner_sender_id": SENDER,
        "allowed_chat_ids": frozenset({GROUP, OTHER}),
        "browser_max_actions": 2,
        "browser_max_text_chars": 4000,
    })()
    task = BrowserTaskService(
        runtime, BrowserStore(tmp_path / "browser.sqlite3"), transport, settings)
    sent_holder = {}

    def send(chat, text):
        sent_holder["sent"].append((chat, text))

    web_calls = []

    def web_answer(request, tone="neutral"):
        web_calls.append((request, tone))
        assert PRIVATE not in request
        assert request == "Hey Rally, what's the weather for Example Domain"
        return "Example Domain weather was not checked live. Public topic only."

    agent = QuietAgent()
    env = build(tmp_path, lookup=lambda *_args, **_kwargs: None, dry_run=True,
                web_answer=web_answer, agent=agent)
    sent_holder["sent"] = env["sent"]
    inbound = BrowserInbound(
        "iMessage;-;demo-owner", SENDER, task, send, allowed_chat_ids={GROUP, OTHER})
    env["client"].close()
    app = create_app(
        env["service"], webhook_token=TOKEN, schedule=False, portal_store=env["portal"],
        history_client=None, history_enabled=True,
        reservation_call_inbound=env["inbound"],
        browser_runtime=runtime, browser_inbound=inbound,
        browser_enabled=True, browser_admin_token="demo-admin")
    client = TestClient(app)
    env["client"] = client
    try:
        search = post(env, payload(GROUP, "Hey Rally, search for Example Domain", "search"))
        assert search.json()["accepted"] is True
        assert prompts
        assert "example.com" in env["sent"][-1][1].lower() or "placeholder" in env["sent"][-1][1].lower()
        assert not env["sent"][-1][1].startswith("Rally:")
        assert "booked" not in env["sent"][-1][1].lower()

        weather = post(env, payload(
            GROUP, "Hey Rally, what's the weather for Example Domain", "weather"))
        assert weather.json()["accepted"] is True
        assert web_calls
        assert "public topic only" in env["sent"][-1][1].lower()
        assert not env["sent"][-1][1].startswith("Rally:")
        assert PRIVATE not in env["sent"][-1][1]

        ordinary = post(env, payload(GROUP, "Hey Rally, say pong", "pong"))
        assert ordinary.json()["accepted"] is True
        assert env["sent"][-1] == (GROUP, "pong")
        assert env["agent"].direct
        assert env["agent"].direct[-1][0] == "Hey Rally, say pong"
        assert env["vapi"].placed == []
        assert env["vapi"].prepared == []
        assert all(not text.startswith("Rally:") for _chat, text in env["sent"])
    finally:
        client.close()


def _placed_env(tmp_path):
    seen = []
    lookup = PublicRestaurantLookup(fetch=public_fetch(seen)).find
    env = build(tmp_path, lookup=lookup, dry_run=False)
    ignored = post(env, payload(OTHER, "yes", "wrong"))
    assert ignored.status_code == 200
    assert env["vapi"].placed == []
    assert snapshots(env["path"]) == []
    assert post(env, payload(GROUP, FULL, "ask")).json()["accepted"] is True
    assert PHONE in env["sent"][-1][1]
    assert post(env, payload(OTHER, "Rally, yes", "other-yes")).json()["accepted"] is True
    assert env["vapi"].placed == []
    assert post(env, payload(GROUP, "yes", "yes-1")).json()["accepted"] is True
    assert len(env["vapi"].placed) == 1
    assert env["vapi"].placed[0]["to_number"] == PHONE
    assert env["inbound"].reconcile_calls() == 0
    return env, seen


def test_host_evidence_delivers_exactly_one_outcome(tmp_path):
    env, _seen = _placed_env(tmp_path)
    try:
        env["vapi"].evidence = {
            "id": CALL_ID, "status": "ended", "structured": {
                "outcome": "confirmed", "confirmationCode": "AB12",
            },
            "transcript": "",
            "messages": [
                {"role": "assistant", "text": "I am calling on behalf of Ada."},
                {"role": "user", "text": HOST},
            ],
        }
        before = len(env["sent"])
        assert env["inbound"].reconcile_calls() == 1
        env["service"].deliver_pending()
        assert env["inbound"].reconcile_calls() == 0
        env["service"].deliver_pending()
        added = env["sent"][before:]
        assert len(added) == 1
        chat, text = added[0]
        assert chat == GROUP
        assert text == (
            "booked Carbone for 4 on 2026-10-02 at 19:30 America/New_York "
            "under Tarun. confirmation AB12."
        )
        assert not text.startswith("Rally:")
        assert "AB12" in text
        rows = snapshots(env["path"])
        assert rows[0]["state"] == "confirmed"
        assert rows[0]["call_id"] == CALL_ID
        queued = outbox(env["path"], "voice_call_result")
        assert len(queued) == 1
        assert queued[0]["status"] == "sent"
        assert PRIVATE not in text
    finally:
        env["client"].close()


def test_assistant_evidence_does_not_confirm(tmp_path):
    env, _seen = _placed_env(tmp_path)
    try:
        env["vapi"].evidence = {
            "id": CALL_ID, "status": "ended",
            "structured": {"outcome": "confirmed", "confirmationCode": "AB12"},
            "transcript": HOST,
            "messages": [{"role": "assistant", "text": HOST}],
        }
        before = len(env["sent"])
        assert env["inbound"].reconcile_calls() == 1
        env["service"].deliver_pending()
        assert env["inbound"].reconcile_calls() == 0
        env["service"].deliver_pending()
        added = env["sent"][before:]
        assert len(added) == 1
        text = added[0][1]
        assert text.lower().startswith("unresolved")
        assert "did not confirm" in text.lower()
        assert "booked" not in text.lower()
        assert "AB12" not in text
        assert "confirmation" not in text.lower()
        assert not text.startswith("Rally:")
        assert snapshots(env["path"])[0]["state"] == "unresolved"
    finally:
        env["client"].close()
