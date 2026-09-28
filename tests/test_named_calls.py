from datetime import datetime, timezone

import pytest

from app.store import Store
from app.voice.call_store import CallAttemptStore
from app.voice.caller import ReservationCaller, looks_like_direct_call_request
from app.voice.handler import ReservationCallInbound


CHAT = "any;+;named-call-test"
CALL_ID = "019a9046-121e-766d-bd1f-84f3ccc309c1"
COMMAND = "rally call Tarun ask him when hes free"


class Vapi:
    def __init__(self):
        self.calls = []

    def ready(self):
        return True

    def allows(self, number):
        return number == "+14155550123"

    def place_call(self, **body):
        self.calls.append(body)
        return {"id": CALL_ID, "status": "queued"}


def incoming(text=COMMAND, ident="named-1"):
    return {"type": "new-message", "data": {
        "guid": ident, "text": text, "isFromMe": False,
        "dateCreated": int(datetime.now(timezone.utc).timestamp() * 1000),
        "handle": {"address": "+15555550123"}, "chats": [{"guid": CHAT}],
    }}


def test_named_commands_are_call_intents():
    assert looks_like_direct_call_request(COMMAND)
    assert looks_like_direct_call_request("Rally, please phone Tarun Devi and ask when he is free")
    for text in ["Rally, don't call Tarun", "Rally, should I call Tarun?",
                 "Rally, remind me to call Tarun", "Rally, let's call it a day"]:
        assert not looks_like_direct_call_request(text)


def contact(first="Tarun", last="Devi", number="+14155550123"):
    return {"firstName": first, "lastName": last, "displayName": f"{first} {last}",
            "phoneNumbers": [] if number is None else [{"address": number}]}


def test_local_lookup_duplicate_cards_and_exact_full_name():
    from app.voice.contacts import LocalContactLookup
    lookup = LocalContactLookup(lambda: [contact(number=None), contact(), contact(last="Other")])
    assert lookup("Tarun Devi") == "+14155550123"
    with pytest.raises(ValueError, match="multiple contacts"):
        lookup("Tarun")
    assert LocalContactLookup(lambda: [contact(number=None), contact()])("tarun") == "+14155550123"


def test_local_lookup_multiple_numbers_missing_and_unavailable():
    from app.voice.contacts import LocalContactLookup
    with pytest.raises(ValueError, match="multiple numbers"):
        LocalContactLookup(lambda: [contact(), contact(number="+14155550124")])("Tarun")
    with pytest.raises(ValueError, match="number"):
        LocalContactLookup(lambda: [contact(number=None)])("Tarun")
    with pytest.raises(ValueError, match="number"):
        LocalContactLookup(lambda: [])("Unknown")
    def broken():
        raise RuntimeError("private token")
    with pytest.raises(ValueError, match="contacts are unavailable") as error:
        LocalContactLookup(broken)("Tarun")
    assert "private token" not in str(error.value)


def test_named_call_routes_to_vapi_once_and_preserves_requested_task(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    attempts = CallAttemptStore(path)
    vapi, replies, lookups = Vapi(), [], []
    def lookup(name):
        lookups.append(name)
        return "+14155550123"
    def inbound():
        return ReservationCallInbound(
            ReservationCaller(vapi=vapi, contact_lookup=lookup),
            lambda chat, body: replies.append(body), allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound().try_receive(incoming()) is True
    assert inbound().try_receive(incoming()) is True
    assert len(vapi.calls) == 1
    assert vapi.calls[0]["to_number"] == "+14155550123"
    overrides = vapi.calls[0]["assistant_overrides"]
    assert "Tarun" in overrides["firstMessage"]
    assert "ask him when hes free" in overrides["model"]["messages"][0]["content"]
    assert attempts.get("named-1")["destination"] == "+14155550123"
    assert attempts.get("named-1")["call_id"] == CALL_ID
    assert len(replies) == 1 and "call started" in replies[0]
    assert CALL_ID not in replies[0]
    assert "vapi call" not in replies[0].lower()
    assert not replies[0].startswith("Rally:")
    # Resolving a duplicate must not cause another contact read or call.
    assert lookups == ["Tarun"]


def test_missing_contact_is_handled_without_conversation_fallback(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    attempts = CallAttemptStore(path)
    replies, vapi = [], Vapi()
    caller = ReservationCaller(vapi=vapi, contact_lookup=lambda _: "")
    inbound = ReservationCallInbound(caller, lambda chat, body: replies.append(body),
                                     allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound.try_receive(incoming()) is True
    assert vapi.calls == [] and attempts.get("named-1")["status"] == "noted"
    assert len(replies) == 1 and "number" in replies[0].lower()
    assert "call started" not in replies[0] and "calling" not in replies[0]


def test_named_call_does_not_resolve_or_dial_without_explicit_address(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    def forbidden(_):
        raise AssertionError("unauthorized contact lookup")
    inbound = ReservationCallInbound(ReservationCaller(vapi=Vapi(), contact_lookup=forbidden),
                                     lambda *_: None, allowed_chat_ids={CHAT})
    assert inbound.try_receive(incoming("call Tarun ask him when hes free")) is None
    outside = incoming()
    outside["data"]["chats"] = [{"guid": "other"}]
    assert inbound.try_receive(outside) is None


def test_webhook_named_call_preempts_conversation_agent(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.models import PlanFacts
    from app.orchestrator import RallyService
    from app.portal_store import PortalStore

    path = tmp_path / "r.sqlite3"
    store = Store(path)
    sent, ordinary = [], []

    class Agent:
        def extract(self, *_):
            return PlanFacts()

        def answer_direct(self, *_):
            ordinary.append(True)
            return "calling now"

    service = RallyService(store, Agent(), lambda _: [],
                           lambda chat, body: sent.append(body),
                           allowed_chat_ids={CHAT}, defer_heavy_work=False)
    vapi = Vapi()
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi, contact_lookup=lambda _: "+14155550123"),
        service.send_fn, allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
    app = create_app(service, webhook_token="secret", schedule=False,
                     reservation_call_inbound=inbound, portal_store=PortalStore(path),
                     history_enabled=False)
    with TestClient(app) as client:
        response = client.post("/webhooks/bluebubbles?token=secret", json=incoming())
    assert response.json() == {"accepted": True}
    assert ordinary == []
    assert len(vapi.calls) == 1
    assert CallAttemptStore(path).get("named-1")["call_id"] == CALL_ID
    assert sent == [sent[0]] and "call started" in sent[0]
