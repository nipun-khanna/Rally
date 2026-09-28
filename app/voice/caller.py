"""Phone reservation calls: parse chat intent, talk (or loopback), report honestly.

Grok Voice does the restaurant back-and-forth. PSTN dialing is Twilio when
keys and a public callback URL exist. Otherwise Rally runs a local mock-host
loopback so the chat command still exists. Loopback never marks a table booked.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, replace
from typing import Callable

from app.policy import explicitly_addresses_rally
from app.voice.continuity import AUTHORIZED_TEST_NUMBER


_CALL_BOOK = re.compile(
    r"\b(?:call|phone|dial)\b.+\b(?:book|reserve|reservation|table)\b|"
    r"\b(?:book|reserve|reservation)\b.+\b(?:call|phone|dial)\b",
    re.I,
)
_REMIND_CALL = re.compile(r"\bremind me to call\b", re.I)
_VENUE = re.compile(
    r"\b(?:call|phone|dial)\s+(?:the\s+)?(.+?)\s+"
    r"(?:and\s+)?(?:to\s+)?(?:book|reserve|make)",
    re.I,
)
_PARTY = re.compile(r"\b(?:for|party(?:\s+of)?)\s+(\d{1,2})\b", re.I)
_TIME = re.compile(r"\bat\s+(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)\b", re.I)
_NAME = re.compile(r"\b(?:under|name(?:\s+is)?)\s+([A-Za-z][A-Za-z' -]{1,40})\b", re.I)
_PHONE = re.compile(
    r"(?<!\d)(\+?1[\s.-]?)?(?:\((\d{3})\)|(\d{3}))[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)",
)
_CARD_ASK = re.compile(
    r"\b(?:credit card|debit card|card number|cvv|cvc|expiration|exp date|"
    r"card to hold|hold (?:the )?(?:table|reservation) with (?:a )?card)\b",
    re.I,
)
_CARD_DIGITS = re.compile(r"(?:\d[ \-]*){13,19}")
_INVOKE_PREFIX = re.compile(
    r"^\s*(?:(?:hey|hi|hello|yo|ok|okay|ask)[,\s]+)?@?rally\b[\s,.:\-]*",
    re.I,
)


STATUSES = ("booked", "need_confirm", "failed", "waiting_for_human")


@dataclass(frozen=True)
class ReservationRequest:
    venue: str
    party_size: int | None
    time: str | None
    guest_name: str
    callback_number: str
    destination_phone: str
    chat_id: str = ""
    raw_text: str = ""
    contact_note: str = ""
    call_task: str = ""


@dataclass(frozen=True)
class CallResult:
    status: str
    transport: str
    dialed: bool
    venue: str
    party_size: int | None = None
    time: str | None = None
    confirmation_id: str | None = None
    notes: str = ""
    spoken: str = ""
    call_id: str | None = None
    provider_status: str | None = None
    prepared_call: dict | None = None

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError("Invalid reservation-call status")


_DIRECT_CALL = re.compile(r"\b(?:call|phone|dial)\b", re.I)
_DIRECT_COMMAND = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you|will you)\s+)?"
    r"(?:call|phone|dial)\b", re.I)
_E164_PHONE = re.compile(r"(?<![\w+])\+[1-9]\d{1,14}(?!\d)")


def looks_like_reservation_call_request(text: str) -> bool:
    if not isinstance(text, str) or not text.strip() or _REMIND_CALL.search(text):
        return False
    return bool(_CALL_BOOK.search(text))


def looks_like_direct_call_request(text: str) -> bool:
    if not isinstance(text, str) or not text.strip() or _REMIND_CALL.search(text):
        return False
    body = _INVOKE_PREFIX.sub("", text, count=1)
    return bool(_DIRECT_COMMAND.search(body) and (extract_phone(body) or direct_call_target(text)))


def direct_call_target(text: str) -> str:
    body = _INVOKE_PREFIX.sub("", text or "", count=1)
    command = _DIRECT_COMMAND.match(body)
    if not command:
        return ""
    rest = body[command.end():].strip()
    target = re.split(r"\s+(?:(?:and|to)\s+)?(?:ask|tell|see|find out|check)\b", rest,
                      maxsplit=1, flags=re.I)[0].strip(" ,.!?")
    if not re.fullmatch(r"[A-Za-z][A-Za-z'’ .-]{0,79}", target):
        return ""
    if target.casefold() in {"it a day", "it", "that", "this"}:
        return ""
    return target


def personal_call_overrides(request, owner_name="") -> dict:
    recipient = request.venue or "there"
    behalf = owner_name or "your group"
    return {
        "firstMessage": f"Hi {recipient}, I'm calling on behalf of {behalf}. Is now a good time to talk?",
        "firstMessageMode": "assistant-speaks-first",
        "model": {"provider": "xai", "model": "grok-4.3", "messages": [{
            "role": "system", "content": (
                "Make this requested phone call on behalf of the group. Ask one question at a time. "
                "Carry out only the conversation requested in the following JSON data. "
                "Collect the person's answer accurately; do not invent their availability or an agreement. "
                "Do not claim to send messages, create bookings, or change calendars. "
                "If asked whether you are automated, answer truthfully. Respect a refusal and end politely. "
                + json.dumps({"recipient": recipient, "request": request.call_task}, ensure_ascii=False)
            ),
        }]},
    }


def looks_like_call_request(text: str) -> bool:
    return looks_like_reservation_call_request(text) or looks_like_direct_call_request(text)


_TABLE_BOOKING = re.compile(
    r"\b(?:book|reserve)\s+(?:a\s+)?table\b|\bmake\s+a\s+reservation\b|\breservation\s+at\b",
    re.I,
)


def looks_like_restaurant_booking(text: str) -> bool:
    """A group ask to book a restaurant, including requests that never say call."""
    if not isinstance(text, str) or not text.strip() or _REMIND_CALL.search(text):
        return False
    return bool(looks_like_reservation_call_request(text) or _TABLE_BOOKING.search(text))


def iter_phones(text: str | None) -> list[str]:
    """Every explicit E.164 or US number in text, without inventing one."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _E164_PHONE.finditer(text):
        number = match.group()
        if number not in seen:
            seen.add(number)
            found.append(number)
    for match in _PHONE.finditer(text):
        number = normalize_phone(match.group(0))
        if number and number not in seen:
            seen.add(number)
            found.append(number)
    return found


def looks_like_card_number(text: str | None) -> bool:
    if not text:
        return False
    compact = re.sub(r"[ \-]", "", text)
    for match in re.finditer(r"\d{13,19}", compact):
        if _luhn_ok(match.group(0)):
            return True
    return bool(_CARD_DIGITS.search(text)) and any(
        ch.isdigit() for ch in text
    ) and len(re.sub(r"\D", "", text)) >= 13


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def payment_card_for_hold() -> None:
    """Rally never invents a card. Hosts that require one wait for a human."""
    return None


def redact_card_digits(text: str) -> str:
    if not text:
        return ""
    return _CARD_DIGITS.sub("[redacted]", text)


def normalize_phone(text: str | None) -> str:
    if not text:
        return ""
    match = _PHONE.search(text)
    if match is None:
        return ""
    area = match.group(2) or match.group(3) or ""
    rest = f"{match.group(4)}{match.group(5)}"
    if not area or len(rest) != 7:
        return ""
    return f"+1{area}{rest}"


def extract_phone(text: str | None) -> str:
    """Accept explicit E.164 worldwide or an unambiguous US ten-digit number."""
    if not text:
        return ""
    match = _E164_PHONE.search(text)
    return match.group() if match else normalize_phone(text)


def parse_reservation_call(
    text: str,
    *,
    plan=None,
    proposal=None,
    callback_number: str = "",
    guest_name: str = "",
    chat_id: str = "",
) -> ReservationRequest:
    body = _INVOKE_PREFIX.sub("", text or "", count=1).strip()
    venue = ""
    found = _VENUE.search(body)
    if found:
        venue = re.sub(r"\s+", " ", found.group(1)).strip(" .,!?")
        if venue.lower() in {"the restaurant", "restaurant", "them", "it"}:
            venue = ""
    facts = getattr(plan, "facts", None) if plan is not None else None
    if not venue and proposal is not None:
        venue = getattr(proposal, "venue_name", "") or ""
    if not venue and facts is not None:
        venue = getattr(facts, "location", "") or ""
    party = None
    party_match = _PARTY.search(body)
    if party_match:
        party = int(party_match.group(1))
        if not 1 <= party <= 20:
            party = None
    if party is None and proposal is not None:
        party = getattr(proposal, "party_size", None)
    if party is None and facts is not None:
        party = getattr(facts, "party_size", None)
    time_match = _TIME.search(body)
    when = time_match.group(1).strip() if time_match else None
    if not when and proposal is not None:
        when = getattr(proposal, "time", None)
    if not when and facts is not None:
        when = getattr(facts, "time", None)
    name_match = _NAME.search(body)
    name = name_match.group(1).strip() if name_match else guest_name
    if not name and facts is not None:
        people = [p for p in (getattr(facts, "participants", None) or []) if p]
        if people:
            name = people[0]
    destination = extract_phone(body)
    direct_only = bool(destination) and not _CALL_BOOK.search(body)
    return ReservationRequest(
        venue="" if direct_only else (venue or "the restaurant"),
        party_size=party,
        time=when,
        guest_name=name,
        callback_number=normalize_phone(callback_number) or destination,
        destination_phone=destination,
        chat_id=chat_id,
        raw_text=text or "",
    )


def restaurant_asked_for_card(line: str) -> bool:
    return bool(line and _CARD_ASK.search(line))


def handle_restaurant_turn(line: str, request: ReservationRequest) -> CallResult:
    """One host utterance. Never invent payment. Never claim a booking here."""
    spoken = (
        f"party of {request.party_size}" if request.party_size else "a group"
    )
    if request.time:
        spoken += f" at {request.time}"
    if request.guest_name:
        spoken += f", under {request.guest_name}"
    if request.callback_number:
        spoken += f", callback {request.callback_number}"
    if restaurant_asked_for_card(line):
        if payment_card_for_hold() is not None:
            raise RuntimeError("payment card must never be invented")
        return CallResult(
            status="waiting_for_human",
            transport="loopback",
            dialed=False,
            venue=request.venue,
            party_size=request.party_size,
            time=request.time,
            notes="host asked for a card hold; no card was given",
            spoken="I cannot give a card number. A person from the group will need to continue.",
        )
    return CallResult(
        status="need_confirm",
        transport="loopback",
        dialed=False,
        venue=request.venue,
        party_size=request.party_size,
        time=request.time,
        notes="still talking to the host",
        spoken=spoken,
    )


def run_loopback(request: ReservationRequest) -> CallResult:
    """Scripted host. Ends waiting for a human if a card is required."""
    host_lines = (
        f"Thanks for calling {request.venue}. How many in the party?",
        "What time works?",
        "Name on the reservation?",
        "I'll need a credit card to hold the table. Can I have the number?",
    )
    result = CallResult(
        status="need_confirm", transport="loopback", dialed=False,
        venue=request.venue, party_size=request.party_size, time=request.time,
        notes="loopback started",
    )
    for line in host_lines:
        result = handle_restaurant_turn(line, request)
        if looks_like_card_number(result.spoken) or looks_like_card_number(result.notes):
            raise RuntimeError("reservation loopback invented a card number")
        if result.status == "waiting_for_human":
            return replace(result, confirmation_id=None)
    return CallResult(
        status="need_confirm",
        transport="loopback",
        dialed=False,
        venue=request.venue,
        party_size=request.party_size,
        time=request.time,
        notes="loopback finished without a real booking",
    )


def finalize_result(result: CallResult) -> CallResult:
    notes = redact_card_digits(result.notes)
    spoken = redact_card_digits(result.spoken)
    status = result.status
    confirmation = result.confirmation_id
    if status == "booked" and (not result.dialed or not confirmation):
        status = "need_confirm" if confirmation or result.dialed else "failed"
        confirmation = confirmation if result.dialed else None
        notes = notes or "no restaurant was reached, so nothing is booked"
    if looks_like_card_number(notes) or looks_like_card_number(spoken):
        notes = "card digits redacted"
        spoken = ""
    return replace(result, status=status, confirmation_id=confirmation,
                   notes=notes, spoken=spoken)


def format_call_status(result: CallResult) -> str:
    if result.transport == "contact":
        return result.notes or "What phone number should I call? I haven't placed a call."
    result = finalize_result(result)
    if result.transport == "restaurant":
        return result.notes or "nothing is booked."
    venue = result.venue or "the restaurant"
    when = f" at {result.time}" if result.time else ""
    party = f" for {result.party_size}" if result.party_size else ""
    if result.transport == "continuity":
        if result.dialed:
            how = result.notes or "Mac Phone app"
            return (f"need confirm — started a call via {how}. "
                    "nothing is booked.")
        extra = result.notes or "Phone.app did not start a call"
        return f"failed — {extra}. nothing is booked."
    if result.transport == "vapi":
        if result.dialed:
            who = result.venue.strip() if result.venue else ""
            if who:
                return f"call started — calling {who}. i'll report when it ends."
            return "call started — i'll report when it ends."
        return f"call not confirmed — {result.notes or 'Vapi call did not start'}."
    if result.status == "booked" and result.dialed and result.confirmation_id:
        return (f"booked {venue}{party}{when}. confirmation {result.confirmation_id}.")
    if result.status == "waiting_for_human":
        extra = result.notes or "the host asked a person to continue"
        return (f"need confirm — {venue}{party}{when}. {extra}. "
                "i did not give a card and nothing is booked.")
    if result.status == "need_confirm":
        if result.dialed:
            return (f"need confirm — spoke with {venue}{party}{when}. "
                    "nothing is booked yet.")
        return (f"need confirm — i did not dial {venue}. nothing is booked. "
                f"{result.notes or 'local voice loopback only'}.")
    return f"failed — could not book {venue}{party}{when}. nothing is booked."


class ReservationCaller:
    def __init__(
        self,
        *,
        plan_store=None,
        dialer=None,
        app_url: str = "",
        callback_number: str = "",
        guest_name: str = "",
        media_base: str = "",
        last_result_hook: Callable[[CallResult], None] | None = None,
        continuity=None,
        voice=None,
        vapi=None,
        owner_name: str = "",
        phone_lookup=None,
        dry_run: bool = False,
        snapshots=None,
        contact_lookup=None,
    ):
        self.plan_store = plan_store
        self.dialer = dialer
        self.app_url = app_url
        self.callback_number = callback_number
        self.guest_name = guest_name
        self.media_base = media_base
        self.last_result_hook = last_result_hook
        self.continuity = continuity
        self.voice = voice
        self.vapi = vapi
        self.owner_name = owner_name or ""
        self.phone_lookup = phone_lookup
        self.dry_run = bool(dry_run)
        self.snapshots = snapshots
        self.contact_lookup = contact_lookup
        self._memory_snapshots = None
        self.last_result: CallResult | None = None
        self.last_request: ReservationRequest | None = None
        self._briefs: dict[str, ReservationRequest] = {}

    def can_dial_pstn(self, request: ReservationRequest | None = None) -> bool:
        from app.voice.telco import can_place_pstn_call
        request = request or self.last_request
        phone = request.destination_phone if request else ""
        return can_place_pstn_call(
            self.dialer, self.app_url or self.media_base, destination_phone=phone)

    def can_dial_continuity(self, request: ReservationRequest | None = None) -> bool:
        request = request or self.last_request
        phone = request.destination_phone if request else ""
        if self.continuity is None or not phone:
            return False
        ready = getattr(self.continuity, "ready", lambda: False)
        allows = getattr(self.continuity, "allows", lambda _: False)
        return bool(ready() and allows(phone))

    def parse(self, text: str, *, chat_id: str = "") -> ReservationRequest:
        plan = None
        proposal = None
        if self.plan_store is not None and chat_id:
            try:
                plan = self.plan_store.get_plan(chat_id)
            except Exception:
                plan = None
            if plan is not None:
                try:
                    proposal = self.plan_store.latest_proposal(plan.id)
                except Exception:
                    proposal = None
        request = parse_reservation_call(
            text, plan=plan, proposal=proposal,
            callback_number=self.callback_number, guest_name=self.guest_name,
            chat_id=chat_id)
        if looks_like_direct_call_request(text) and not looks_like_restaurant_booking(text):
            body = _INVOKE_PREFIX.sub("", text or "", count=1)
            task = re.search(r"\b(?:ask|tell|see|find out|check)\b.*", body, re.I)
            target = direct_call_target(text)
            request = replace(request, venue=target, call_task=task.group(0)[:1000] if task else "")
            if not request.destination_phone:
                try:
                    number = self.contact_lookup(target) if self.contact_lookup else ""
                except ValueError as exc:
                    request = replace(request, contact_note=str(exc))
                except Exception:
                    request = replace(request, contact_note="Local contacts are unavailable; what phone number should I call?")
                else:
                    phone = extract_phone(number)
                    request = replace(request, destination_phone=phone,
                                      contact_note="" if phone else f"What phone number should I call for {target}? I haven't placed a call.")
        return request

    def run(self, text: str, *, chat_id: str = "", parsed_request=None) -> CallResult:
        request = parsed_request if parsed_request is not None else self.parse(text, chat_id=chat_id)
        self.last_request = request
        self._briefs[chat_id or request.venue] = request
        if looks_like_restaurant_booking(text):
            from app.voice.restaurant import advance_restaurant_request
            result = advance_restaurant_request(
                self, text, chat_id=chat_id, message_id="")
            if result is None:
                result = CallResult(
                    status="need_confirm", transport="restaurant", dialed=False,
                    venue=request.venue, notes="nothing is booked.")
            result = finalize_result(result)
            self.last_result = result
            if self.last_result_hook:
                self.last_result_hook(result)
            return result
        if looks_like_direct_call_request(text) and not request.destination_phone:
            result = CallResult(status="waiting_for_human", transport="contact", dialed=False,
                                venue=request.venue, notes=request.contact_note)
        elif self.vapi is not None and request.destination_phone:
            overrides = personal_call_overrides(request, self.owner_name) if request.call_task else None
            result = self._dial_vapi(request, assistant_overrides=overrides)
        elif self.can_dial_pstn(request):
            result = self._dial(request)
        elif self.can_dial_continuity(request):
            result = self._dial_continuity(request)
        elif looks_like_reservation_call_request(text):
            result = run_loopback(request)
        elif looks_like_direct_call_request(text):
            result = CallResult(
                status="failed", transport="continuity", dialed=False,
                venue=request.venue, party_size=request.party_size,
                time=request.time,
                notes="no Continuity dialer or number not allowlisted",
            )
        elif _DIRECT_CALL.search(text) and extract_phone(text):
            result = CallResult(
                status="failed", transport="continuity", dialed=False,
                venue=request.venue, party_size=request.party_size,
                time=request.time,
                notes="refused: will not call restaurants or other numbers",
            )
        else:
            result = run_loopback(request)
        result = finalize_result(result)
        self.last_result = result
        if self.last_result_hook:
            self.last_result_hook(result)
        return result

    def brief(self, chat_id: str) -> ReservationRequest | None:
        return self._briefs.get(chat_id)

    def _dial(self, request: ReservationRequest) -> CallResult:
        from app.voice.telco import twiml_url_for
        try:
            placed = self.dialer.place_call(
                to_number=request.destination_phone,
                twiml_url=twiml_url_for(self.app_url or self.media_base),
            )
        except Exception as exc:
            return CallResult(
                status="failed", transport="twilio", dialed=False,
                venue=request.venue, party_size=request.party_size,
                time=request.time, notes=str(exc)[:200] or "dial failed",
            )
        if not placed.get("sid"):
            return CallResult(
                status="failed", transport="twilio", dialed=False,
                venue=request.venue, party_size=request.party_size,
                time=request.time, notes="twilio did not accept the call",
            )
        return CallResult(
            status="need_confirm",
            transport="twilio",
            dialed=True,
            venue=request.venue,
            party_size=request.party_size,
            time=request.time,
            notes="call placed; waiting for the restaurant to confirm",
        )

    def _dial_vapi(self, request: ReservationRequest, *,
                   assistant_overrides: dict | None = None) -> CallResult:
        allows = getattr(self.vapi, "allows", lambda _: True)
        if not allows(request.destination_phone):
            return CallResult(status="failed", transport="vapi", dialed=False,
                              venue=request.venue, notes="number is not allowlisted for Vapi")
        if not self.vapi.ready():
            return CallResult(status="failed", transport="vapi", dialed=False,
                              venue=request.venue, notes="Vapi is not configured")
        try:
            payload = {"to_number": request.destination_phone}
            if assistant_overrides:
                payload["assistant_overrides"] = assistant_overrides
            placed = self.vapi.place_call(**payload)
        except Exception as exc:
            from app.voice.vapi import VapiError
            note = (str(exc) if isinstance(exc, VapiError) else
                    "Vapi call outcome is unknown; check the dashboard before another attempt")
            return CallResult(status="failed", transport="vapi", dialed=False,
                              venue=request.venue, notes=note)
        return CallResult(status="need_confirm", transport="vapi", dialed=True,
                          venue=request.venue,
                          notes="i'll report when it ends",
                          call_id=placed["id"], provider_status=placed["status"])

    def _dial_continuity(self, request: ReservationRequest) -> CallResult:
        from app.voice.pipeline import run_mac_phone_call
        try:
            placed = run_mac_phone_call(
                to_number=request.destination_phone,
                dialer=self.continuity,
                voice=self.voice,
                brief={
                    "venue": request.venue,
                    "party_size": request.party_size,
                    "time": request.time,
                    "guest_name": request.guest_name,
                    "callback_number": request.callback_number,
                },
            )
        except Exception as exc:
            return CallResult(
                status="failed", transport="continuity", dialed=False,
                venue=request.venue, party_size=request.party_size,
                time=request.time, notes=str(exc)[:200] or "Phone.app dial failed",
            )
        if not placed.get("dialed"):
            return CallResult(
                status="failed", transport="continuity", dialed=False,
                venue=request.venue, party_size=request.party_size,
                time=request.time, notes="Phone.app did not start a call",
            )
        how = "Mac Phone app"
        if placed.get("voice_attached"):
            how = "Mac Phone app + Grok Voice on this computer"
        elif placed.get("voice_reason"):
            how = f"Mac Phone app (voice not attached: {placed['voice_reason']})"
        return CallResult(
            status="need_confirm",
            transport="continuity",
            dialed=True,
            venue=request.venue,
            party_size=request.party_size,
            time=request.time,
            notes=how,
        )


def should_handle_reservation_call(text: str, *, invoked: bool, in_turn: bool) -> bool:
    if not looks_like_call_request(text):
        return False
    return invoked or in_turn or explicitly_addresses_rally(text)
