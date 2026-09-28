import json
import traceback

import httpx
import pytest

from app.voice.vapi import VapiDialer, VapiError


CALL_ID = "019a9046-121e-766d-bd1f-84f3ccc309c1"
ASSISTANT_ID = "4a170597-a0c2-4657-8c32-cb93f080cead"
PHONE_ID = "c6ea6cb0-0dfb-4a65-918f-6a33abb54b64"


def dialer_with(handler, **overrides):
    options = dict(api_key="private-test-key", assistant_id=ASSISTANT_ID,
                   phone_number_id=PHONE_ID)
    options.update(overrides)
    return VapiDialer(**options, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_places_only_authorized_destination_with_provider_request():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(201, json={"id": CALL_ID, "status": "queued",
                                         "monitor": {"controlUrl": "secret"}})

    dialer = dialer_with(respond)
    assert dialer.ready()
    assert dialer.place_call(to_number="+16785991244") == {"id": CALL_ID, "status": "queued"}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.vapi.ai/call"
    assert request.headers["authorization"] == "Bearer private-test-key"
    assert json.loads(request.content) == {
        "assistantId": ASSISTANT_ID, "phoneNumberId": PHONE_ID,
        "customer": {"number": "+16785991244"},
    }


@pytest.mark.parametrize("number", ["+0123456789", "+1", "+1234567890123456", "6785991244",
                                    " +16785991244", "+16785991244 ", "", None])
def test_rejects_other_destinations_before_network(number):
    requests = []
    dialer = dialer_with(lambda request: requests.append(request))
    assert not dialer.allows(number)
    with pytest.raises(VapiError, match="authorized"):
        dialer.place_call(to_number=number)
    assert requests == []


def test_accepts_other_valid_e164_destinations():
    dialer = dialer_with(lambda request: httpx.Response(
        201, json={"id": CALL_ID, "status": "queued"}))
    assert dialer.allows("+17032004231")
    assert dialer.place_call(to_number="+17032004231")["id"] == CALL_ID


@pytest.mark.parametrize("missing", ["api_key", "assistant_id", "phone_number_id"])
def test_incomplete_configuration_cannot_place_call(missing):
    requests = []
    dialer = dialer_with(lambda request: requests.append(request), **{missing: "  "})
    assert not dialer.ready()
    with pytest.raises(VapiError, match="configured"):
        dialer.place_call(to_number="+16785991244")
    assert requests == []


@pytest.mark.parametrize("status_code", [301, 401, 403, 429, 500])
def test_provider_errors_are_sanitized_and_never_retried(status_code):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status_code, text="private-test-key sensitive-response",
                              headers={"Location": "https://example.com/secret"})

    dialer = dialer_with(respond)
    with pytest.raises(VapiError) as error:
        dialer.place_call(to_number="+16785991244")
    rendered = "".join(traceback.format_exception(error.value))
    assert "private-test-key" not in rendered
    assert "sensitive-response" not in rendered
    assert str(status_code) in str(error.value)
    assert len(requests) == 1


def test_timeout_does_not_retry_or_expose_transport_details():
    requests = []

    def respond(request):
        requests.append(request)
        raise httpx.ReadTimeout("private-test-key sensitive-response", request=request)

    dialer = dialer_with(respond)
    with pytest.raises(VapiError, match="unknown") as error:
        dialer.place_call(to_number="+16785991244")
    rendered = "".join(traceback.format_exception(error.value))
    assert "private-test-key" not in rendered
    assert "sensitive-response" not in rendered
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [None, [], {}, {"id": CALL_ID},
    {"id": "", "status": "queued"}, {"id": "../../secret", "status": "queued"},
    {"id": 42, "status": "queued"}, {"id": CALL_ID, "status": "booked"},
    {"id": CALL_ID, "status": ["queued"]}])
def test_rejects_malformed_provider_responses(payload):
    dialer = dialer_with(lambda request: httpx.Response(201, json=payload))
    with pytest.raises(VapiError, match="invalid"):
        dialer.place_call(to_number="+16785991244")


def test_rejects_non_json_response():
    dialer = dialer_with(lambda request: httpx.Response(201, text="sensitive-response"))
    with pytest.raises(VapiError, match="invalid"):
        dialer.place_call(to_number="+16785991244")


@pytest.mark.parametrize("status", ["scheduled", "queued", "ringing", "in-progress", "forwarding", "ended"])
def test_get_call_returns_validated_provider_status(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"id": CALL_ID, "status": status, "transcript": "private"})

    dialer = dialer_with(respond)
    assert dialer.get_call(CALL_ID) == {"id": CALL_ID, "status": status}
    assert requests[0].method == "GET"
    assert str(requests[0].url) == f"https://api.vapi.ai/call/{CALL_ID}"
    assert requests[0].headers["authorization"] == "Bearer private-test-key"


@pytest.mark.parametrize("call_id", ["", "../../call", "id?token=secret", None, 42])
def test_get_call_rejects_invalid_id_before_network(call_id):
    requests = []
    dialer = dialer_with(lambda request: requests.append(request))
    with pytest.raises(VapiError, match="invalid"):
        dialer.get_call(call_id)
    assert requests == []


def test_prepare_call_adds_overrides_without_contacting_vapi():
    def respond(request):
        raise AssertionError("prepare must not contact Vapi")

    dialer = dialer_with(respond)
    overrides = {"firstMessage": "I am calling on behalf of Ada."}
    body = dialer.prepare_call(to_number="+12125550199", assistant_overrides=overrides)
    assert body["customer"] == {"number": "+12125550199"}
    assert body["assistantOverrides"] == overrides
    assert "private-test-key" not in json.dumps(body)


def test_place_call_sends_assistant_overrides():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(201, json={"id": CALL_ID, "status": "queued"})

    dialer = dialer_with(respond)
    overrides = {"firstMessage": "I am calling on behalf of Ada."}
    assert dialer.place_call(to_number="+12125550199", assistant_overrides=overrides)["id"] == CALL_ID
    assert json.loads(requests[0].content)["assistantOverrides"] == overrides


def test_get_call_evidence_keeps_confirmation_fields_only():
    dialer = dialer_with(lambda request: httpx.Response(200, json={
        "id": CALL_ID, "status": "ended",
        "monitor": {"controlUrl": "https://secret.example/private-test-key"},
        "transcript": "Carbone confirmed party of 4.",
        "analysis": {"structuredData": {
            "outcome": "confirmed", "confirmationCode": "AB12", "partySize": 4,
            "date": "2026-10-02", "time": "19:30", "guestName": "Tarun",
            "venue": "Carbone", "recordingUrl": "https://secret.example/audio",
        }, "successEvaluation": "true"},
    }))
    evidence = dialer.get_call_evidence(CALL_ID)
    assert evidence["structured"]["confirmationCode"] == "AB12"
    assert evidence["structured"]["partySize"] == 4
    assert "recordingUrl" not in evidence["structured"]
    assert "monitor" not in evidence
    assert "private-test-key" not in json.dumps(evidence)
    assert "confirmed party of 4" in evidence["transcript"]
    assert evidence["messages"] == []


def test_get_call_evidence_keeps_bounded_role_tagged_messages():
    dialer = dialer_with(lambda request: httpx.Response(200, json={
        "id": CALL_ID, "status": "ended",
        "artifact": {"messages": [
            {"role": "bot", "message": "You're booked. confirmation code is AB12."},
            {"role": "user", "message": "Yes, Carbone for 4. confirmation code is AB12."},
            {"role": "system", "message": "secret tool payload " + ("x" * 5000)},
        ], "recordingUrl": "https://secret.example/audio"},
    }))
    evidence = dialer.get_call_evidence(CALL_ID)
    assert evidence["messages"][0]["role"] == "assistant"
    assert evidence["messages"][1] == {
        "role": "user",
        "text": "Yes, Carbone for 4. confirmation code is AB12.",
    }
    assert all(len(item["text"]) <= 400 for item in evidence["messages"])
    assert "recordingUrl" not in json.dumps(evidence["messages"])


def test_get_call_rejects_mismatched_provider_id():
    dialer = dialer_with(lambda request: httpx.Response(200, json={"id": ASSISTANT_ID, "status": "ended"}))
    with pytest.raises(VapiError, match="invalid"):
        dialer.get_call(CALL_ID)
