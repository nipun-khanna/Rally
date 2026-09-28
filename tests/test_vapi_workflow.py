from datetime import datetime, timezone
import sqlite3

from app.store import Store
from app.voice.call_store import CallAttemptStore
from app.voice.caller import ReservationCaller
from app.voice.handler import ReservationCallInbound


CHAT = "iMessage;+;call-workflow"
TIME = datetime(2026, 9, 27, tzinfo=timezone.utc)
CALL_ID = "019a9046-121e-766d-bd1f-84f3ccc309c1"


def message(ident, body):
    return {"type": "new-message", "data": {
        "guid": ident, "text": body, "isFromMe": False,
        "dateCreated": int(TIME.timestamp() * 1000),
        "handle": {"address": "+15555550123"},
        "chats": [{"guid": CHAT}],
    }}


class FakeVapi:
    def __init__(self):
        self.placed = []
        self.status = "queued"
        self.evidence = {"status": "ended", "structured": None, "transcript": "",
                         "messages": []}

    def ready(self):
        return True

    def allows(self, number):
        return number == "+14155550123"

    def place_call(self, *, to_number, assistant_overrides=None):
        self.placed.append(to_number)
        self.overrides = assistant_overrides
        return {"id": CALL_ID, "status": self.status}

    def get_call(self, call_id):
        assert call_id == CALL_ID
        return {"id": call_id, "status": self.status}

    def get_call_evidence(self, call_id):
        assert call_id == CALL_ID
        return dict(self.evidence)


def test_explicit_call_claim_survives_restart_and_dials_once(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    vapi = FakeVapi()
    sent = []
    first = ReservationCallInbound(
        ReservationCaller(vapi=vapi), lambda chat, body: sent.append((chat, body)),
        allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
    command = message("request-1", "Rally, call +14155550123")
    assert first.try_receive(command) is True
    second = ReservationCallInbound(
        ReservationCaller(vapi=vapi), lambda chat, body: sent.append((chat, body)),
        allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
    assert second.try_receive(command) is True
    assert vapi.placed == ["+14155550123"]
    assert len(sent) == 1
    assert "booked" not in sent[0][1].lower()
    assert CallAttemptStore(path).get("request-1")["call_id"] == CALL_ID


def test_direct_dial_requires_explicit_address_and_allowed_chat(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    vapi = FakeVapi()
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi), lambda *_: None,
        allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
    assert inbound.try_receive(message("quiet", "call +14155550123")) is None
    outside = message("outside", "Rally, call +14155550123")
    outside["data"]["chats"] = [{"guid": "iMessage;+;elsewhere"}]
    assert inbound.try_receive(outside) is None
    assert vapi.placed == []


def test_active_turn_does_not_authorize_implicit_dial(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    vapi = FakeVapi()

    class ActiveTurn:
        def active(self, *_):
            return True

    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi), lambda *_: None,
        allowed_chat_ids={CHAT}, group_turns=ActiveTurn(),
        call_store=CallAttemptStore(path))
    assert inbound.try_receive(message("quiet", "call +14155550123")) is None
    assert vapi.placed == []


def test_number_mention_is_not_a_call_command(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    vapi = FakeVapi()
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi), lambda *_: None,
        allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
    assert inbound.try_receive(message("negated", "Rally, don't call +14155550123")) is None
    assert inbound.try_receive(message("question", "Rally, should I call +14155550123?")) is None
    assert vapi.placed == []


def test_initial_provider_status_is_persisted(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    vapi = FakeVapi()
    vapi.status = "in-progress"
    attempts = CallAttemptStore(path)
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi), lambda *_: None,
        allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound.try_receive(message("request-1", "Rally, call +14155550123")) is True
    assert attempts.get("request-1")["status"] == "in-progress"


def test_ended_call_queues_one_followup_without_claiming_outcome(tmp_path):
    path = tmp_path / "r.sqlite3"
    store = Store(path)
    attempts = CallAttemptStore(path)
    vapi = FakeVapi()
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi), lambda *_: None,
        allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound.try_receive(message("request-1", "Rally, call +14155550123")) is True
    assert inbound.reconcile_calls() == 0
    assert store.pending_messages() == []
    vapi.status = "ended"
    assert inbound.reconcile_calls() == 1
    assert inbound.reconcile_calls() == 0
    pending = store.pending_messages()
    assert len(pending) == 1
    assert pending[0]["chat_id"] == CHAT
    assert pending[0]["kind"] == "voice_call_result"
    assert "ended" in pending[0]["text"].lower()
    assert "booked" not in pending[0]["text"].lower()


def test_ambiguous_post_is_claimed_and_never_retried(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)

    class Failing(FakeVapi):
        def place_call(self, *, to_number, assistant_overrides=None):
            self.placed.append(to_number)
            raise RuntimeError("provider secret")

    vapi = Failing()
    sent = []
    command = message("request-1", "Rally, call +14155550123")
    for _ in range(2):
        inbound = ReservationCallInbound(
            ReservationCaller(vapi=vapi), lambda chat, body: sent.append(body),
            allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
        assert inbound.try_receive(command) is True
    assert vapi.placed == ["+14155550123"]
    assert len(sent) == 1
    assert "secret" not in sent[0]


def test_stale_call_stops_polling_and_reports_unknown(tmp_path):
    path = tmp_path / "r.sqlite3"
    store = Store(path)
    attempts = CallAttemptStore(path)
    vapi = FakeVapi()
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi), lambda *_: None,
        allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound.try_receive(message("request-1", "Rally, call +14155550123")) is True
    with sqlite3.connect(path) as db:
        db.execute("UPDATE voice_call_attempts SET created_at='2020-01-01T00:00:00+00:00'")
    assert inbound.reconcile_calls() == 1
    assert attempts.get("request-1")["status"] == "timed_out"
    assert "no confirmed outcome" in store.pending_messages()[0]["text"].lower()


def test_ended_named_call_reports_callee_answer(tmp_path):
    path = tmp_path / "r.sqlite3"
    store = Store(path)
    attempts = CallAttemptStore(path)
    vapi = FakeVapi()
    vapi.evidence = {"messages": [
        {"role": "assistant", "text": "When are you free?"},
        {"role": "user", "text": "I'm free at 4:00 PM today."},
    ]}
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi, contact_lookup=lambda _: "+14155550123"),
        lambda *_: None, allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound.try_receive(
        message("named-1", "Rally, call Tarun and ask when he's free")) is True
    vapi.status = "ended"
    assert inbound.reconcile_calls() == 1
    text = store.pending_messages()[0]["text"].lower()
    assert "4:00 pm today" in text
    assert "tarun" in text
    assert attempts.get("named-1")["purpose"]
    assert attempts.get("named-1")["contact_name"].lower() == "tarun"


def test_ended_named_call_starts_a_plan_instead_of_dumping_transcript(tmp_path):
    path = tmp_path / "r.sqlite3"
    store = Store(path)
    attempts = CallAttemptStore(path)
    vapi = FakeVapi()
    vapi.evidence = {"messages": [
        {"role": "user", "text": "Yes."},
        {"role": "user", "text": "Um, can you find a restaurant near Midtown. Atlanta?"},
        {"role": "user", "text":
         "we're looking for a low price range for, uh, probably preferably Mexican food."},
        {"role": "user", "text": "Going to the side"},
    ]}
    inbound = ReservationCallInbound(
        ReservationCaller(
            vapi=vapi, contact_lookup=lambda _: "+14155550123", plan_store=store),
        lambda *_: None, allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound.try_receive(
        message("named-plan", "Rally, call Nipun and ask what he wants to eat")) is True
    vapi.status = "ended"
    assert inbound.reconcile_calls() == 1
    text = store.pending_messages()[0]["text"].lower()
    assert "started a plan" in text
    assert "mexican" in text and "midtown" in text
    assert "they said:" not in text
    assert "going to the side" not in text
    plan = store.get_plan(CHAT)
    assert plan is not None
    assert "Mexican" in plan.facts.preferred_cuisines
    assert plan.facts.location == "Midtown Atlanta"
