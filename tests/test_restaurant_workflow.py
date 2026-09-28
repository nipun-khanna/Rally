"""Restaurant discovery, exact brief, same-chat authorization, and dry-run Vapi prep."""

import json
import re
from datetime import datetime, timezone

from app.browser.agent import PublicRestaurantLookup, phone_on_fetched_page, verified_phone_from_page
from app.group_turns import GroupTurnStore
from app.store import Store
from app.voice.call_store import CallAttemptStore
from app.voice.caller import ReservationCaller
from app.voice.handler import ReservationCallInbound
from app.voice.restaurant import restaurant_assistant_overrides, restaurant_outcome


CHAT = "iMessage;+;restaurant"
OTHER = "iMessage;+;other-table"
NOW = datetime(2026, 9, 27, 18, tzinfo=timezone.utc)
CALL_ID = "019a9046-121e-766d-bd1f-84f3ccc309c1"
ASK = (
    "Hey Rally, reserve a table at Carbone for 4 on October 2, 2026 at 7:30pm "
    "Eastern Time under Tarun on behalf of Ada callback (404) 555-0199"
)


def message(ident, body, chat=CHAT):
    return {"type": "new-message", "data": {
        "guid": ident, "text": body, "isFromMe": False,
        "dateCreated": int(NOW.timestamp() * 1000),
        "handle": {"address": "+15555550123"},
        "chats": [{"guid": chat}],
    }}


def lookup(venue):
    assert venue == "Carbone"
    return {"number": "+12125550199", "source_url": "https://carbone.example/contact"}


class RecordingVapi:
    def __init__(self):
        self.placed = []
        self.prepared = []
        self.evidence = {"id": CALL_ID, "status": "queued", "structured": None, "transcript": ""}

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


def test_public_page_verification_accepts_one_matching_number():
    found = verified_phone_from_page(
        "Carbone New York. Call (212) 555-0199 for a table.",
        "Carbone", "https://carbone.example/contact")
    assert found["number"] == "+12125550199"
    assert found["source_url"] == "https://carbone.example/contact"


def test_digits_inside_an_image_url_are_not_a_restaurant_phone():
    page = (
        'Carbone Restaurants. <img src="https://cdn.example/images/'
        '39fe9020464639b5868c14edfeb362aebd4eb1f1.jpg"> Call (212) 555-0199.'
    )
    found = verified_phone_from_page(page, "Carbone", "https://carbone.example/contact")
    assert found["number"] == "+12125550199"
    only_url = (
        'Carbone Restaurants. <img src="https://cdn.example/images/'
        '39fe9020464639b5868c14edfeb362aebd4eb1f1.jpg">'
    )
    assert verified_phone_from_page(
        only_url, "Carbone", "https://carbone.example/") is None


def test_public_page_verification_rejects_ambiguous_or_unrelated_numbers():
    assert verified_phone_from_page(
        "Carbone (212) 555-0199 or (212) 555-0100",
        "Carbone", "https://carbone.example/contact") is None
    assert verified_phone_from_page(
        "Call (212) 555-0199", "Carbone", "https://carbone.example/contact") is None
    assert verified_phone_from_page(
        "Carbone (212) 555-0199", "Carbone", "http://127.0.0.1/contact") is None
    assert verified_phone_from_page(
        "Carbone (212) 555-0199", "Carbone",
        "https://duckduckgo.com/html/?q=carbone") is None


def test_verified_number_comes_from_the_fetched_page_not_the_snippet():
    search = """
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fcarbone.example%2F">Carbone</a>
    <a class="result__snippet">Carbone New York. Phone (212) 555-0199.</a>
    """
    homepage = "<html>Carbone New York restaurant. <a href=\"/contact\">Contact</a></html>"
    contact = "Carbone New York. Reservations (212) 555-0144."
    seen = []

    def fetch(url):
        seen.append(url)
        if "duckduckgo" in url:
            return search, url
        if url.rstrip("/").endswith("/contact"):
            return contact, "https://carbone.example/contact"
        return homepage, "https://carbone.example/"

    found = PublicRestaurantLookup(fetch=fetch).find("Carbone")
    assert found["number"] == "+12125550144"
    assert found["source_url"] == "https://carbone.example/contact"
    assert "https://carbone.example/" in seen
    assert any(url.endswith("/contact") for url in seen)


def test_missing_owner_and_callback_are_asked_not_guessed():
    caller = ReservationCaller(
        owner_name="local-imessage-account", phone_lookup=lookup, dry_run=True,
        vapi=RecordingVapi())
    result = caller.run(
        "Hey Rally, reserve a table at Carbone for 4 on October 2, 2026 "
        "at 7:30pm Eastern Time under Tarun")
    assert result.dialed is False
    assert result.transport == "restaurant"
    notes = result.notes.lower()
    assert "owner name" in notes
    assert "callback number" in notes
    assert "local-imessage-account" not in notes
    assert "callback +12125550199" not in notes
    assert "will not place a call" in notes
    assert caller.vapi.placed == []


def test_yes_in_the_same_chat_prepares_vapi_without_placing(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    vapi = RecordingVapi()
    turns = GroupTurnStore(tmp_path / "turns.sqlite3")
    sent = []
    caller = ReservationCaller(
        vapi=vapi, phone_lookup=lookup, dry_run=True, snapshots=CallAttemptStore(path))
    inbound = ReservationCallInbound(
        caller, lambda chat, body: sent.append((chat, body)),
        allowed_chat_ids={CHAT, OTHER}, group_turns=turns,
        call_store=CallAttemptStore(path))
    assert inbound.try_receive(message("ask", ASK)) is True
    assert vapi.placed == []
    assert "reply yes" in sent[0][1].lower()
    other = message("other-yes", "Rally, yes", chat=OTHER)
    assert inbound.try_receive(other) is None
    assert vapi.prepared == []
    changed = message("change", "yes, party of 6")
    assert inbound.try_receive(changed) is True
    assert vapi.prepared == []
    assert "party of 6" not in sent[-1][1].lower() or "6" in sent[-1][1]
    assert inbound.try_receive(message("yes", "yes")) is True
    assert vapi.placed == []
    assert len(vapi.prepared) == 1
    opening = vapi.prepared[0]["assistantOverrides"]["firstMessage"]
    assert opening.startswith("I am calling on behalf of Ada")
    assert not re.search(r"\bai\b|\bbot\b|\bautomated\b|\bassistant\b", opening, re.I)
    system = vapi.prepared[0]["assistantOverrides"]["model"]["messages"][0]["content"].lower()
    assert "do not volunteer" in system
    assert "answer truthfully" in system
    assert vapi.prepared[0]["customer"]["number"] == "+12125550199"
    assert "private" not in json.dumps(vapi.prepared[0])
    assert "dry-run" in sent[-1][1].lower()
    assert "not placed" in sent[-1][1].lower()
    assert "for 6" in opening
    saved = CallAttemptStore(path).open_restaurant(CHAT)
    assert saved is None


def test_saved_brief_authorizes_after_restart_without_a_new_search(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    searches = []

    def counting_lookup(venue):
        searches.append(venue)
        return lookup(venue)

    first = ReservationCallInbound(
        ReservationCaller(phone_lookup=counting_lookup, dry_run=True, vapi=RecordingVapi(),
                          snapshots=CallAttemptStore(path)),
        lambda *_: None, allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
    assert first.try_receive(message("ask", ASK)) is True
    assert searches == ["Carbone"]
    vapi = RecordingVapi()
    second = ReservationCallInbound(
        ReservationCaller(phone_lookup=lambda venue: (_ for _ in ()).throw(AssertionError("researched")),
                          dry_run=True, vapi=vapi, snapshots=CallAttemptStore(path)),
        lambda *_: None, allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
    assert second.try_receive(message("yes", "Rally, yes")) is True
    assert vapi.placed == []
    assert vapi.prepared[0]["customer"]["number"] == "+12125550199"
    assert vapi.prepared[0]["assistantOverrides"]["firstMessage"].startswith(
        "I am calling on behalf of Ada")


def test_direct_call_still_dials_the_requested_number_without_restaurant_overrides():
    vapi = RecordingVapi()
    vapi.allows = lambda number: number == "+14155550100"
    result = ReservationCaller(vapi=vapi).run("Rally, call +14155550100")
    assert result.dialed is True
    assert result.transport == "vapi"
    assert vapi.placed == [{"to_number": "+14155550100", "assistant_overrides": None}]


def test_authorized_fake_call_uses_overrides_and_ended_is_not_booked(tmp_path):
    path = tmp_path / "r.sqlite3"
    store = Store(path)
    vapi = RecordingVapi()
    sent = []
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi, phone_lookup=lookup, dry_run=False,
                          snapshots=CallAttemptStore(path)),
        lambda chat, body: sent.append(body),
        allowed_chat_ids={CHAT}, call_store=CallAttemptStore(path))
    assert inbound.try_receive(message("ask", ASK)) is True
    assert inbound.try_receive(message("yes", "Rally, yes")) is True
    assert vapi.placed[0]["to_number"] == "+12125550199"
    assert vapi.placed[0]["assistant_overrides"]["firstMessage"].startswith(
        "I am calling on behalf of Ada")
    assert "booked" not in sent[-1].lower()
    vapi.evidence = {"id": CALL_ID, "status": "ended", "structured": {"outcome": "confirmed"},
                     "transcript": "thanks for calling"}
    assert inbound.reconcile_calls() == 1
    pending = store.pending_messages()
    assert "unresolved" in pending[0]["text"].lower()
    assert "did not confirm" in pending[0]["text"].lower()
    assert "confirmation" not in pending[0]["text"].lower()


def test_matching_restaurant_evidence_confirms_and_a_mismatch_does_not():
    terms = {
        "venue": "Carbone", "party_size": 4, "date": "2026-10-02", "time": "19:30",
        "timezone": "America/New_York", "guest_name": "Tarun", "owner_name": "Ada",
        "callback_number": "+14045550199", "destination_phone": "+12125550199",
        "destination_source": "https://carbone.example/contact",
    }
    host = (
        "You're booked at Carbone for 4 on October 2, 2026 at 7:30pm under Tarun. "
        "The confirmation code is AB12."
    )
    assert restaurant_outcome(
        {"status": "ended", "structured": None, "messages": [
            {"role": "assistant", "text": "I am calling on behalf of Ada."},
            {"role": "user", "text": host},
        ]}, terms) == ("confirmed", "AB12")
    assert restaurant_outcome(
        {"status": "ended", "structured": None, "transcript": f"AI: one moment\nUser: {host}"},
        terms) == ("confirmed", "AB12")
    assert restaurant_outcome(
        {"status": "ended", "structured": None, "transcript": host}, terms
    ) == ("unresolved", "")
    assert restaurant_outcome(
        {"status": "ended", "structured": None, "messages": [
            {"role": "assistant", "text": host},
        ]}, terms) == ("unresolved", "")
    assert restaurant_outcome(
        {"status": "ended", "structured": {
            "outcome": "confirmed", "confirmationCode": "AB12", "partySize": 4,
            "date": "2026-10-02", "time": "19:30", "guestName": "Tarun", "venue": "Carbone",
        }, "transcript": ""}, terms) == ("unresolved", "")
    assert restaurant_outcome(
        {"status": "ended", "structured": None, "messages": [
            {"role": "user", "text": host.replace("AB12", "set")},
        ]}, terms) == ("unresolved", "")
    assert restaurant_outcome(
        {"status": "ended", "structured": None, "transcript": "", "successEvaluation": "true"},
        terms) == ("unresolved", "")
    overrides = restaurant_assistant_overrides(terms)
    assert overrides["firstMessage"].startswith("I am calling on behalf of Ada")
    assert overrides["model"]["provider"] == "xai"


def test_browser_use_page_is_fetched_and_its_spoken_number_is_ignored():
    search = (
        '<a class="result__a" href="https://duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fcarbone.example%2F">Carbone</a>'
    )
    homepage = "Carbone restaurant"

    def fetch(url):
        if "duckduckgo" in url:
            return search, url
        if url.rstrip("/") == "https://carbone.example":
            return homepage, url
        if url.endswith("/visit"):
            return "Carbone restaurant. Phone (212) 555-0166.", url
        raise AssertionError(url)

    class Browser:
        def run_task(self, request, timeout_seconds=90):
            assert "homepage" in request.lower()
            return {"status": "ok", "url": "https://carbone.example/visit",
                    "answer": "The phone is (212) 555-0100"}

    found = PublicRestaurantLookup(fetch=fetch, browser_use=Browser()).find("Carbone")
    assert found["number"] == "+12125550166"
    assert found["source_url"] == "https://carbone.example/visit"


def test_one_phone_in_the_wrong_city_is_not_verified():
    url = "https://carbone.example/contact"
    miami = "Carbone Miami. Call (305) 555-0108 for a table."
    assert phone_on_fetched_page(miami, "Carbone", url, "new york") is None
    assert phone_on_fetched_page(miami, "Carbone", url, "brooklyn") is None
    bare = "Carbone. Call (212) 555-0199 for a table."
    assert phone_on_fetched_page(bare, "Carbone", url, "New York") is None
    brooklyn = "Carbone in Brooklyn. Call (718) 555-0142."
    found = phone_on_fetched_page(brooklyn, "Carbone", url, "New York")
    assert found["number"] == "+17185550142"
    assert found["timezone"] == "America/New_York"
    nyc = phone_on_fetched_page("Carbone NYC. Phone (212) 555-0199.", "Carbone", url, "Brooklyn")
    assert nyc["number"] == "+12125550199"


def test_named_location_selects_one_of_several_published_numbers():
    page = "Carbone New York (212) 555-0199. Carbone Miami (305) 555-0108."
    url = "https://carbone.example/locations"
    ambiguous = phone_on_fetched_page(page, "Carbone", url, "")
    assert "new york" in ambiguous["ambiguous_locations"]
    assert "miami" in ambiguous["ambiguous_locations"]
    found = phone_on_fetched_page(page, "Carbone", url, "new york")
    assert found["number"] == "+12125550199"
    assert found["timezone"] == "America/New_York"


def test_location_question_does_not_ask_for_a_phone_number():
    def finder(venue, location=""):
        assert venue == "Carbone"
        if location == "new york":
            return {"number": "+12125550199", "source_url": "https://carbone.example/ny",
                    "timezone": "America/New_York"}
        return {"ambiguous_locations": ["new york", "miami"]}

    sent = []
    caller = ReservationCaller(phone_lookup=finder, dry_run=True, vapi=RecordingVapi())
    caller.now = lambda: NOW
    inbound = ReservationCallInbound(
        caller, lambda chat, body: sent.append(body), allowed_chat_ids={CHAT})
    assert inbound.try_receive(message(
        "ask-loc",
        "Hey Rally, reserve a table at Carbone tonight at 7:30pm for 4 under Tarun "
        "on behalf of Ada callback (404) 555-0199")) is True
    assert "which location" in sent[-1].lower()
    assert "phone number" not in sent[-1].lower()
    assert inbound.try_receive(message("where", "Rally, New York")) is True
    assert "+12125550199" in sent[-1]
    assert "2026-09-27" in sent[-1]
    assert "america/new_york" in sent[-1].lower()
    assert "reply yes" in sent[-1].lower()


def test_tonight_and_a_later_same_venue_request_merge(tmp_path):
    path = tmp_path / "r.sqlite3"
    Store(path)
    searches = []

    def finder(venue, location=""):
        searches.append((venue, location))
        return {"number": "+12125550199", "source_url": "https://carbone.example/contact",
                "timezone": "America/New_York"}

    attempts = CallAttemptStore(path)
    caller = ReservationCaller(
        phone_lookup=finder, dry_run=True, vapi=RecordingVapi(), snapshots=attempts)
    caller.now = lambda: NOW
    inbound = ReservationCallInbound(
        caller, lambda *_: None, allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound.try_receive(message(
        "ask",
        "Hey Rally, reserve a table at Carbone in New York tonight at 7:30pm for 4 "
        "under Tarun on behalf of Ada callback (404) 555-0199")) is True
    assert inbound.try_receive(message(
        "more", "Hey Rally, reserve a table at Carbone for 6")) is True
    saved = attempts.open_restaurant(CHAT)
    assert saved["terms"]["party_size"] == 6
    assert saved["terms"]["date"] == "2026-09-27"
    assert saved["terms"]["destination_phone"] == "+12125550199"
    assert searches == [("Carbone", "new york")]
    assert inbound.try_receive(message(
        "switch", "Hey Rally, reserve a table at Lilia in New York tomorrow at 8:00pm")) is True
    switched = attempts.open_restaurant(CHAT)
    assert switched["terms"]["venue"] == "Lilia"
    assert switched["terms"]["date"] == "2026-09-28"
    assert not switched["terms"]["party_size"]
    assert searches[-1][0] == "Lilia"


def test_direct_calls_remain_open_to_any_explicit_number():
    vapi = RecordingVapi()
    first = ReservationCaller(vapi=vapi).run("Rally, call +14155550100")
    second = ReservationCaller(vapi=vapi).run("Rally, call +442079460958")
    assert first.dialed and second.dialed
    assert [item["to_number"] for item in vapi.placed] == ["+14155550100", "+442079460958"]
    assert all(item["assistant_overrides"] is None for item in vapi.placed)


def test_claim_precedes_place_and_a_missing_provider_id_is_not_redialed(tmp_path):
    path = tmp_path / "r.sqlite3"
    store = Store(path)
    attempts = CallAttemptStore(path)
    order = []
    real_claim = attempts.claim

    def claim(*args, **kwargs):
        order.append(kwargs.get("status"))
        return real_claim(*args, **kwargs)

    attempts.claim = claim
    vapi = RecordingVapi()

    def place_call(*, to_number, assistant_overrides=None):
        order.append("place")
        vapi.placed.append({"to_number": to_number, "assistant_overrides": assistant_overrides})
        return {"id": CALL_ID, "status": "queued"}

    vapi.place_call = place_call
    sent = []
    inbound = ReservationCallInbound(
        ReservationCaller(vapi=vapi, phone_lookup=lookup, dry_run=False, snapshots=attempts),
        lambda chat, body: sent.append(body), allowed_chat_ids={CHAT}, call_store=attempts)
    assert inbound.try_receive(message("ask", ASK)) is True
    assert inbound.try_receive(message("yes", "Rally, yes")) is True
    assert order.index("dialing") < order.index("place")
    assert vapi.placed[0]["assistant_overrides"]["firstMessage"].startswith(
        "I am calling on behalf of Ada")

    crashed = CallAttemptStore(path.parent / "crash.sqlite3")
    Store(path.parent / "crash.sqlite3")
    crash_store = Store(path.parent / "crash.sqlite3")
    vapi2 = RecordingVapi()
    vapi2.place_call = lambda **kwargs: (_ for _ in ()).throw(AssertionError("redial"))
    sent2 = []
    inbound2 = ReservationCallInbound(
        ReservationCaller(vapi=vapi2, phone_lookup=lookup, dry_run=False, snapshots=crashed),
        lambda chat, body: sent2.append(body), allowed_chat_ids={CHAT}, call_store=crashed)
    assert inbound2.try_receive(message("ask2", ASK)) is True
    assert crashed.claim("yes2", CHAT, "+12125550199", status="dialing")
    assert inbound2.try_receive(message("yes2", "Rally, yes")) is True
    assert "did not redial" in sent2[-1].lower()
    assert "check vapi" in sent2[-1].lower()
    assert inbound2.try_receive(message("yes3", "Rally, yes")) is None
    assert crashed.unidentified_claims() == []
    assert inbound2.reconcile_calls() == 0
    assert crash_store.pending_messages() == []
