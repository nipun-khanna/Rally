from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.group_turns import GroupTurnStore
from app.main import create_app
from app.orchestrator import RallyService
from app.store import Store
from app.voice.caller import (
    ReservationCaller,
    format_call_status,
    handle_restaurant_turn,
    looks_like_card_number,
    looks_like_direct_call_request,
    looks_like_reservation_call_request,
    parse_reservation_call,
    payment_card_for_hold,
    run_loopback,
)
from app.voice.continuity import AUTHORIZED_TEST_NUMBER, ContinuityDialer, ContinuityError
from app.voice.handler import ReservationCallInbound
from app.voice.reservation_tools import build_reservation_call_tools
from app.voice.telco import TwilioDialer, can_place_pstn_call, public_media_base


NOW = datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc)
GROUP = "iMessage;+;chat-reserve"
SENDER = "+15555550123"


def payload(chat, text, ident="m1", sender=SENDER):
    return {"type": "new-message", "data": {
        "guid": ident, "text": text, "isFromMe": False,
        "dateCreated": int(NOW.timestamp() * 1000),
        "handle": {"address": sender}, "chats": [{"guid": chat}]}}


def test_reservation_call_intent_routes_and_ignores_other_asks():
    assert looks_like_reservation_call_request(
        "Hey Rally, call Taj and book for 4 at 8")
    assert looks_like_reservation_call_request(
        "Rally, phone the restaurant and reserve a table")
    assert not looks_like_reservation_call_request(
        "Hey Rally, remind me to call mom")
    assert not looks_like_reservation_call_request(
        "Hey Rally, reserve a table at Carbone")
    assert not looks_like_reservation_call_request("dinner Friday in Midtown")
    assert looks_like_direct_call_request("Hey Rally, call 7032004231")
    assert looks_like_direct_call_request("Rally, dial +1 703-200-4231")
    assert not looks_like_direct_call_request("Hey Rally, remind me to call mom")
    assert not looks_like_direct_call_request("Hey Rally, call Taj and book for 4")
    assert looks_like_direct_call_request("Hey Rally, call 2125550100")


def test_parse_pulls_venue_party_time_and_never_invents_a_phone():
    request = parse_reservation_call("Hey Rally, call Taj and book for 4 at 8")
    assert request.venue == "Taj"
    assert request.party_size == 4
    assert request.time.startswith("8")
    assert request.destination_phone == ""


def test_loopback_never_books_and_never_invents_a_card():
    request = parse_reservation_call("Hey Rally, call Taj and book for 4 at 8")
    result = run_loopback(request)
    assert result.status == "waiting_for_human"
    assert result.dialed is False
    assert result.confirmation_id is None
    assert payment_card_for_hold() is None
    assert not looks_like_card_number(result.spoken)
    assert not looks_like_card_number(result.notes)
    assert "card" in result.notes.lower()
    status = format_call_status(result)
    assert "booked" not in status.split("—")[0]
    assert "nothing is booked" in status
    assert "4111111111111111" not in status


def test_card_ask_waits_for_human_without_digits():
    request = parse_reservation_call("call Taj and book for 4 at 8")
    result = handle_restaurant_turn(
        "I'll need a credit card to hold the table. Number please?", request)
    assert result.status == "waiting_for_human"
    assert payment_card_for_hold() is None
    assert not looks_like_card_number(result.spoken)


def test_loopback_booked_claim_is_downgraded():
    from app.voice.caller import CallResult, finalize_result
    fake = CallResult(
        status="booked", transport="loopback", dialed=False, venue="Taj",
        confirmation_id="RLY-FAKE")
    honest = finalize_result(fake)
    assert honest.status != "booked"
    assert honest.confirmation_id is None
    assert "nothing is booked" in format_call_status(honest)


def test_reservation_tools_refuse_card_numbers():
    caller = ReservationCaller()
    registry = build_reservation_call_tools(caller)
    refused = registry.call("report_reservation_result", {
        "status": "booked",
        "confirmation_id": "4111111111111111",
        "notes": "paid with 4111-1111-1111-1111",
    })
    assert refused["ok"] is False
    waiting = registry.call("wait_for_human", {"reason": "host asked for a card"})
    assert waiting["status"] == "waiting_for_human"
    assert payment_card_for_hold() is None


def test_twilio_defaults_off_without_public_url_or_phone():
    settings_empty = TwilioDialer("", "", "")
    assert settings_empty.ready() is False
    assert public_media_base("http://127.0.0.1:8770") is None
    assert can_place_pstn_call(
        TwilioDialer("ACsid", "token", "+15551230000"),
        "http://127.0.0.1:8770", destination_phone="+14045551212") is False
    assert can_place_pstn_call(
        TwilioDialer("ACsid", "token", "+15551230000"),
        "https://rally.example.com", destination_phone="") is False
    assert can_place_pstn_call(
        TwilioDialer("ACsid", "token", "+15551230000"),
        "https://rally.example.com", destination_phone="+14045551212") is False


def test_chat_command_sends_status_and_does_not_claim_booked(tmp_path):
    sent = []
    store = Store(tmp_path / "r.sqlite3")
    service = RallyService(
        store, agent=None, search_fn=lambda facts: [],
        send_fn=lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={GROUP}, group_turns=GroupTurnStore(tmp_path / "turns.sqlite3"))
    inbound = ReservationCallInbound(
        ReservationCaller(plan_store=store),
        lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={GROUP},
        group_turns=service.group_turns)
    app = create_app(service, webhook_token="secret", schedule=False,
                     reservation_call_inbound=inbound)
    client = TestClient(app)
    response = client.post(
        "/webhooks/bluebubbles?token=secret",
        json=payload(GROUP, "Hey Rally, call Taj and book for 4 at 8"))
    client.close()
    assert response.json() == {"accepted": True}
    assert sent
    assert sent[0][0] == GROUP
    body = sent[0][1].lower()
    assert not body.startswith("rally:")
    assert "will not place a call" in body
    assert "you're all set" not in body
    assert "4111" not in body


def test_active_turn_can_request_a_call_without_saying_rally(tmp_path):
    sent = []
    turns = GroupTurnStore(tmp_path / "turns.sqlite3")
    turns.open(GROUP, "open", NOW, "Hey Rally, recap")
    inbound = ReservationCallInbound(
        ReservationCaller(),
        lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={GROUP},
        group_turns=turns)
    assert inbound.try_receive(payload(
        GROUP, "call Taj and book for 4 at 8", ident="follow")) is True
    assert sent
    assert "will not place a call" in sent[0][1].lower()


def test_continuity_fallback_dials_allowlisted_number_and_does_not_book():
    opened = []
    caller = ReservationCaller(
        continuity=ContinuityDialer(opener=opened.append))
    result = caller.run("Hey Rally, call 7032004231")
    assert result.dialed is True
    assert result.transport == "continuity"
    assert result.status == "need_confirm"
    assert result.confirmation_id is None
    assert opened == [f"tel://{AUTHORIZED_TEST_NUMBER}"]
    status = format_call_status(result)
    assert "phone app" in status.lower()
    assert "nothing is booked" in status
    assert "booked" not in status.split("—")[0]


def test_mac_call_pipeline_attaches_grok_voice_without_booking():
    opened = []
    started = []

    class Voice:
        def start(self, brief=None):
            started.append(brief)
            return {"attached": True}

    caller = ReservationCaller(
        continuity=ContinuityDialer(opener=opened.append),
        voice=Voice())
    result = caller.run("Hey Rally, call 7032004231")
    assert result.dialed is True
    assert started and started[0]["callback_number"]
    assert "grok voice" in result.notes.lower()
    assert "nothing is booked" in format_call_status(result)
    assert result.status != "booked"


def test_continuity_refuses_other_numbers():
    opened = []
    dialer = ContinuityDialer(opener=opened.append)
    with pytest.raises(ContinuityError):
        dialer.place_call(to_number="+14045551212")
    assert opened == []
    caller = ReservationCaller(continuity=dialer)
    result = caller.run("Hey Rally, call 4045551212")
    assert result.dialed is False
    assert result.transport == "continuity"
    assert "booked" not in format_call_status(result).split("—")[0]


def test_chat_command_continuity_call_does_not_claim_booked(tmp_path):
    opened = []
    sent = []
    inbound = ReservationCallInbound(
        ReservationCaller(continuity=ContinuityDialer(opener=opened.append)),
        lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={GROUP})
    assert inbound.try_receive(payload(
        GROUP, "Hey Rally, call 7032004231", ident="c1")) is True
    assert opened == [f"tel://{AUTHORIZED_TEST_NUMBER}"]
    body = sent[0][1].lower()
    assert not body.startswith("rally:")
    assert "phone" in body
    assert "nothing is booked" in body


def test_never_dials_a_restaurant_number():
    opened = []
    caller = ReservationCaller(
        continuity=ContinuityDialer(opener=opened.append))
    result = caller.run("Hey Rally, call Carbone at 212-555-0100 and book for 4")
    assert opened == []
    assert result.dialed is False
    assert result.status != "booked"
    other = caller.run("Hey Rally, call 2125550100")
    assert opened == []
    assert other.dialed is False
    assert "restaurant" in format_call_status(other).lower() or "nothing is booked" in format_call_status(other)


def test_unallowlisted_chat_is_ignored():
    sent = []
    inbound = ReservationCallInbound(
        ReservationCaller(),
        lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={GROUP})
    assert inbound.try_receive(payload(
        "iMessage;+;other", "Hey Rally, call Taj and book for 4 at 8")) is None
    assert sent == []


def test_vapi_direct_request_routes_to_explicit_destination():
    from app.voice.vapi import AUTHORIZED_TEST_NUMBER as VAPI_TEST_NUMBER
    assert VAPI_TEST_NUMBER == "+16785991244"
    assert looks_like_direct_call_request("Rally, call 6785991244")
    assert looks_like_direct_call_request("Rally, call 2125550100")
    calls = []

    class Vapi:
        def ready(self):
            return True
        def allows(self, number):
            return number == VAPI_TEST_NUMBER
        def place_call(self, *, to_number):
            calls.append(to_number)
            return {"id": "vapi-test-id", "status": "queued"}

    caller = ReservationCaller(vapi=Vapi())
    result = caller.run("Rally, call 6785991244")
    assert calls == [VAPI_TEST_NUMBER]
    assert result.transport == "vapi"
    assert result.dialed is True
    assert result.status == "need_confirm"
    status = format_call_status(result).lower()
    assert "call started" in status
    assert "vapi-test-id" not in status
    assert "queued" not in status
    caller.run("Rally, call 2125550100")
    assert calls == [VAPI_TEST_NUMBER]


def test_vapi_unexpected_error_does_not_expose_provider_details():
    class Vapi:
        def ready(self):
            return True

        def place_call(self, *, to_number):
            raise RuntimeError("private-key provider response")

    result = ReservationCaller(vapi=Vapi()).run("Rally, call 6785991244")
    assert not result.dialed
    assert result.transport == "vapi"
    assert "private-key" not in format_call_status(result)
    assert "check the dashboard" in format_call_status(result)
    assert "call not confirmed" in format_call_status(result).lower()
