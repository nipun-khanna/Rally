"""Exact restaurant briefs, same-chat authorization, and Vapi call preparation.

A restaurant booking is not a demo loopback and not an immediate dial. Rally
searches a public page for one verified number, asks for any missing exact
terms, and places a call only after a later yes in the same chat.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.voice.caller import (
    CallResult,
    ReservationRequest,
    extract_phone,
    iter_phones,
    looks_like_card_number,
    looks_like_restaurant_booking,
)


_PERSON = r"([A-Za-z][A-Za-z']*(?:\s+[A-Za-z][A-Za-z']*){0,3}?)"
_GUEST = re.compile(
    rf"\b(?:under|name(?:\s+is)?)\s+{_PERSON}(?=\s+(?:on behalf|callback|at|for|party)\b|[,.]|$)",
    re.I,
)
_OWNER = re.compile(
    rf"\b(?:on behalf of|owner(?:\s+is)?)\s+{_PERSON}(?=\s+(?:callback|under|name|at|for|party)\b|[,.]|$)",
    re.I,
)
_CALLBACK = re.compile(
    r"\b(?:callback(?:\s+number)?(?:\s+is)?|call(?:\s+me)?\s+back at)\s+"
    r"([+().\d][\d\s().+\-]{6,20})",
    re.I,
)
_PARTY = re.compile(r"\b(?:for|party(?:\s+of)?)\s+(\d{1,2})\b", re.I)
_AT_VENUE = re.compile(
    r"\bat\s+(?:the\s+)?([A-Za-z][A-Za-z0-9'&.\-]*(?:\s+[A-Za-z][A-Za-z0-9'&.\-]*){0,4}?)"
    r"(?=\s+(?:for|on|at|under|name|party|callback|friday|saturday|sunday|monday|"
    r"tuesday|wednesday|thursday|tonight|tomorrow)\b|\s+\d|[,.]|$)",
    re.I,
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTH_DATE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b",
    re.I,
)
_MONTH_DAY = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{4})",
    re.I,
)
_RELATIVE_DAY = re.compile(r"\b(tonight|today|tomorrow)\b", re.I)
_CLOCK = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b"
    r"|\b([01]\d|2[0-3]):([0-5]\d)\b",
    re.I,
)
_IANA = re.compile(r"\b([A-Za-z]+(?:/[A-Za-z_]+){1,2})\b")
_AUTHORIZE = re.compile(
    r"(?:yes|yeah|yep|yup|okay|ok)(?:[,.]?\s+please)?[.!]?"
    r"|(?:yes|yeah|yep|yup|okay|ok)[,.]?\s+(?:please\s+)?"
    r"(?:call(?:\s+them)?|place the call|do it|book it|go ahead)"
    r"|(?:please\s+)?(?:place the call|go ahead(?: and call)?|"
    r"authorize(?: the call)?|call them|do it|book it)",
    re.I,
)
_CANCEL = re.compile(
    r"\b(?:don't call|do not call|cancel(?: the (?:call|reservation))?|"
    r"never mind|nevermind)\b",
    re.I,
)
_REJECT = re.compile(
    r"\b(?:don't|do not|never mind|nevermind|cancel|stop|not yet|hold on)\b|\bno\b",
    re.I,
)
_CONFIRM_WORDS = re.compile(
    r"\b(?:confirmation|confirmed|you're booked|you are booked|we have you down|"
    r"reservation is set)\b",
    re.I,
)
_CONFIRM_CODE = re.compile(
    r"\bconfirmation(?:\s+(?:code|number))?\s*(?:is|:)?\s*([A-Za-z0-9-]{2,40})\b",
    re.I,
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ZONE_NAMES = {
    "eastern time": "America/New_York",
    "pacific time": "America/Los_Angeles",
    "central time": "America/Chicago",
    "mountain time": "America/Denver",
    "alaska time": "America/Anchorage",
    "hawaii time": "Pacific/Honolulu",
}
_TERM_KEYS = (
    "venue", "party_size", "date", "time", "timezone", "guest_name",
    "owner_name", "callback_number", "destination_phone", "destination_source",
)
_OPEN = {"collecting", "awaiting_authorization"}
_STATES = _OPEN | {
    "authorized", "dialing", "placed", "confirmed", "unresolved", "failed",
    "unknown", "superseded",
}
_REQUIRED = (
    ("venue", "restaurant name"),
    ("date", "exact date including the year"),
    ("time", "exact time with am/pm or a 24-hour clock"),
    ("timezone", "timezone, such as America/New_York or Eastern Time"),
    ("party_size", "party size"),
    ("guest_name", "reservation name"),
    ("destination_phone", "verified public restaurant phone number"),
    ("owner_name", "owner name to call on behalf of"),
    ("callback_number", "callback number"),
)
_RESTAURANT_MODEL = {"provider": "xai", "model": "grok-4.3"}


def _clean(value: str, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def usable_owner_name(value: str) -> str:
    text = _clean(value, 80)
    if not text or text.casefold() in {"local-imessage-account", "owner", "rally"}:
        return ""
    if any(ch.isdigit() for ch in text):
        return ""
    if not re.fullmatch(r"[A-Za-z][A-Za-z' .,-]{1,79}", text):
        return ""
    return text


def _valid_zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ""
    return name


def _calendar_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _one(values: set[str]) -> str:
    if len(values) == 1:
        return next(iter(values))
    return ""


def empty_terms() -> dict:
    return {key: "" for key in _TERM_KEYS}


def terms_digest(terms: dict) -> str:
    payload = {key: terms.get(key, "") for key in _TERM_KEYS}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


_INVOKE = re.compile(
    r"^\s*(?:(?:hey|hi|hello|yo|ok|okay|ask)[,\s]+)?@?rally\b[\s,.:\-]*",
    re.I,
)


def _body(text: str) -> str:
    return _INVOKE.sub("", text or "", count=1).strip()


def explicit_terms(text: str) -> dict:
    """Fields written in this message. Configured owner and callback are not applied."""
    body = _body(text)
    terms = empty_terms()
    from app.voice.caller import parse_reservation_call
    parsed = parse_reservation_call(body)
    venue = parsed.venue if parsed.venue.lower() not in {"the restaurant", "restaurant"} else ""
    if not venue:
        match = _AT_VENUE.search(body)
        venue = match.group(1).strip(" .,!?") if match else ""
    venue = _clean(venue, 80)
    if venue.casefold() not in {"the restaurant", "restaurant", "them", "it", "a table"}:
        from app.browser.agent import peel_location
        venue, location = peel_location(venue)
        terms["venue"] = venue
        if location:
            terms["location"] = location
    party = _PARTY.search(body)
    if party and 1 <= int(party.group(1)) <= 20:
        terms["party_size"] = int(party.group(1))
    dates = set()
    for match in _ISO_DATE.finditer(body):
        found = _calendar_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found:
            dates.add(found)
    for match in _NUMERIC_DATE.finditer(body):
        found = _calendar_date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        if found:
            dates.add(found)
    for match in _MONTH_DATE.finditer(body):
        month = _MONTHS.get(match.group(1).lower())
        if month:
            found = _calendar_date(int(match.group(3)), month, int(match.group(2)))
            if found:
                dates.add(found)
    terms["date"] = _one(dates)
    clocks = set()
    for match in _CLOCK.finditer(body):
        if match.group(3):
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            ampm = match.group(3).lower().replace(".", "")
            if not 1 <= hour <= 12 or minute > 59:
                continue
            if ampm.startswith("p") and hour != 12:
                hour += 12
            if ampm.startswith("a") and hour == 12:
                hour = 0
            clocks.add(f"{hour:02d}:{minute:02d}")
        elif match.group(4):
            clocks.add(f"{int(match.group(4)):02d}:{int(match.group(5)):02d}")
    terms["time"] = _one(clocks)
    zones = set()
    lowered = body.lower()
    for label, zone in _ZONE_NAMES.items():
        if label in lowered and _valid_zone(zone):
            zones.add(zone)
    for match in _IANA.finditer(body):
        zone = _valid_zone(match.group(1))
        if zone:
            zones.add(zone)
    terms["timezone"] = _one(zones)
    guest = _GUEST.search(body)
    if guest:
        terms["guest_name"] = _clean(guest.group(1), 80)
    owner = _OWNER.search(body)
    if owner:
        terms["owner_name"] = usable_owner_name(owner.group(1))
    callback = _CALLBACK.search(body)
    if callback:
        terms["callback_number"] = extract_phone(callback.group(1))
    return terms


def is_pure_authorization(text: str) -> bool:
    body = _body(text)
    if not body or _REJECT.search(body):
        return False
    explicit = explicit_terms(body)
    if any(explicit.get(key) for key in _TERM_KEYS):
        return False
    return bool(_AUTHORIZE.fullmatch(body))


def is_cancel(text: str) -> bool:
    return bool(text and _CANCEL.search(_body(text)))


def is_restaurant_followup(text: str) -> bool:
    if is_pure_authorization(text) or is_cancel(text):
        return True
    explicit = explicit_terms(text)
    if any(explicit.get(key) for key in _TERM_KEYS):
        return True
    from app.browser.agent import cities_in_text
    return bool(cities_in_text(_body(text)))


def missing_terms(terms: dict) -> list[str]:
    missing = []
    for key, label in _REQUIRED:
        if key == "destination_phone":
            if terms.get("location_options") and not terms.get("destination_phone"):
                missing.append("which location")
                continue
            if not terms.get("destination_phone") or not terms.get("destination_source"):
                missing.append(label)
            continue
        if not terms.get(key):
            missing.append(label)
    return missing


def restaurant_assistant_overrides(terms: dict) -> dict:
    """Per-call Vapi override. The opening does not volunteer an AI label."""
    owner = _clean(str(terms.get("owner_name") or ""), 80)
    guest = _clean(str(terms.get("guest_name") or ""), 80)
    venue = _clean(str(terms.get("venue") or ""), 80)
    when = _clean(str(terms.get("time") or ""), 8)
    day = _clean(str(terms.get("date") or ""), 10)
    zone = _clean(str(terms.get("timezone") or ""), 64)
    party = terms.get("party_size")
    callback = _clean(str(terms.get("callback_number") or ""), 20)
    first = (
        f"I am calling on behalf of {owner}. "
        f"I would like a reservation for {party} on {day} at {when} {zone} "
        f"under {guest}. The callback number is {callback}."
    )
    system = (
        f"You are placing one restaurant reservation call to {venue} on behalf of {owner}. "
        "Say the opening line first. Do not volunteer that you are an AI, a bot, "
        "automated, or an assistant. If someone asks whether you are an AI, a bot, "
        "a recording, automated, or a virtual assistant, answer truthfully that you "
        f"are an automated assistant calling on behalf of {owner}. "
        "Use only these exact terms and do not change them: "
        f"restaurant {venue}; date {day}; time {when}; timezone {zone}; "
        f"party size {party}; name on the reservation {guest}; "
        f"callback number {callback}. "
        "If they confirm these exact terms, ask for a confirmation code and repeat "
        "the date, time, and party size. If they cannot book these exact terms, "
        "say you will check with the group and end the call. If they ask for a "
        "credit card, deposit, or payment number, say a person from the group "
        "will need to continue. Never invent payment details. Do not say the "
        "table is booked unless the restaurant clearly confirms it and gives a "
        "confirmation code."
    )
    values = {key: "" if terms.get(key) is None else str(terms.get(key)) for key in _TERM_KEYS}
    return {
        "firstMessage": first,
        "firstMessageMode": "assistant-speaks-first",
        "variableValues": values,
        "model": {
            **_RESTAURANT_MODEL,
            "messages": [{"role": "system", "content": system}],
        },
        "analysisPlan": {
            "structuredDataPlan": {
                "enabled": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "outcome": {"type": "string", "enum": ["confirmed", "unresolved"]},
                        "confirmationCode": {"type": "string"},
                        "partySize": {"type": "integer"},
                        "date": {"type": "string"},
                        "time": {"type": "string"},
                        "guestName": {"type": "string"},
                        "venue": {"type": "string"},
                    },
                    "required": ["outcome", "confirmationCode", "partySize", "date",
                                 "time", "guestName", "venue"],
                },
            },
        },
    }


def _acceptable_code(code: str) -> bool:
    text = (code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{2,40}", text):
        return False
    if text.casefold() in {
            "yes", "ok", "okay", "booked", "confirmed", "none", "null", "true", "set"}:
        return False
    return not looks_like_card_number(text)


def _time_phrases(hhmm: str) -> list[str]:
    hour, minute = (int(part) for part in hhmm.split(":"))
    suffix = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    phrases = [hhmm, f"{hour12}:{minute:02d}", f"{hour12}:{minute:02d}{suffix}",
               f"{hour12}:{minute:02d} {suffix}"]
    if minute == 0:
        phrases.extend((f"{hour12}{suffix}", f"{hour12} {suffix}"))
    return phrases


def _date_phrases(iso_day: str) -> list[str]:
    year, month, day = (int(part) for part in iso_day.split("-"))
    month_name = date(year, month, day).strftime("%B").lower()
    return [iso_day, f"{month_name} {day}", f"{month_name} {day}, {year}"]


_HOST_ROLES = {"user", "customer", "restaurant", "host", "callee"}
_SPEAKER_TURN = re.compile(
    r"(?im)(?:^|\n)\s*(assistant|bot|ai|system|model|user|customer|restaurant|host|callee)\s*:\s*"
)


def _host_speech(evidence: dict) -> str:
    """Restaurant-side lines only. Assistant narration and unlabeled text do not count."""
    messages = evidence.get("messages")
    if isinstance(messages, list) and messages:
        parts = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").casefold()
            text = item.get("text") if isinstance(item.get("text"), str) else ""
            if not text:
                raw = item.get("message")
                text = raw if isinstance(raw, str) else ""
            if role in _HOST_ROLES and text.strip():
                parts.append(text.strip())
        return "\n".join(parts)
    transcript = evidence.get("transcript") if isinstance(evidence.get("transcript"), str) else ""
    return _labeled_host_transcript(transcript)


def _labeled_host_transcript(transcript: str) -> str:
    if not transcript or not _SPEAKER_TURN.search(transcript):
        return ""
    parts = []
    matches = list(_SPEAKER_TURN.finditer(transcript))
    for index, match in enumerate(matches):
        role = match.group(1).casefold()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(transcript)
        if role in _HOST_ROLES:
            spoken = transcript[start:end].strip()
            if spoken:
                parts.append(spoken)
    return "\n".join(parts)


def _transcript_confirms(transcript: str, terms: dict, code: str) -> bool:
    hay = (transcript or "").casefold()
    if not hay or not _CONFIRM_WORDS.search(hay):
        return False
    if terms["guest_name"].casefold() not in hay or terms["venue"].casefold() not in hay:
        return False
    if not re.search(rf"\b{int(terms['party_size'])}\b", hay):
        return False
    if not any(phrase in hay for phrase in _date_phrases(terms["date"])):
        return False
    if not any(phrase in hay for phrase in _time_phrases(terms["time"])):
        return False
    return code.casefold() in hay


def restaurant_outcome(evidence: dict, terms: dict) -> tuple[str, str]:
    """Confirmed only from restaurant-side speech. Assistant recap is not a booking."""
    if not isinstance(evidence, dict) or evidence.get("status") != "ended":
        return "unresolved", ""
    host = _host_speech(evidence)
    match = _CONFIRM_CODE.search(host)
    spoken = match.group(1) if match else ""
    if _acceptable_code(spoken) and _transcript_confirms(host, terms, spoken):
        return "confirmed", spoken
    return "unresolved", ""


class MemoryRestaurantStore:
    """In-process briefs used when the caller has no SQLite snapshot store."""

    def __init__(self):
        self.rows: list[dict] = []
        self.claims: set[str] = set()
        self.attempts: dict[str, dict] = {}

    def claim(self, message_id: str, chat_id: str, destination: str, *, status: str = "dialing") -> bool:
        if not message_id or message_id in self.claims:
            return False
        self.claims.add(message_id)
        self.attempts[message_id] = {
            "source_message_id": message_id, "chat_id": chat_id,
            "destination": destination, "call_id": None, "status": status,
        }
        return True

    def get(self, message_id: str) -> dict | None:
        row = self.attempts.get(message_id)
        return dict(row) if row else None

    def unidentified_claims(self) -> list[dict]:
        return [dict(row) for row in self.attempts.values()
                if row.get("status") == "dialing" and not row.get("call_id")]

    def abandon_unidentified(self, message_id: str) -> bool:
        row = self.attempts.get(message_id)
        if not row or row.get("status") != "dialing" or row.get("call_id"):
            return False
        row["status"] = "failed"
        return True

    def open_restaurant(self, chat_id: str) -> dict | None:
        for row in reversed(self.rows):
            if row["chat_id"] == chat_id and row["state"] in _OPEN:
                return row
        return None

    def save_restaurant(self, *, chat_id: str, terms: dict, digest: str, state: str,
                        source_message_id: str) -> dict:
        if state not in _STATES:
            raise ValueError("Invalid restaurant snapshot state")
        now = datetime.now().isoformat()
        for row in self.rows:
            if row["chat_id"] == chat_id and row["state"] in _OPEN:
                row["state"] = "superseded"
                row["updated_at"] = now
        row = {
            "id": str(uuid4()), "chat_id": chat_id, "terms": dict(terms),
            "terms_json": json.dumps(terms, sort_keys=True), "terms_digest": digest,
            "state": state, "source_message_id": source_message_id,
            "authorization_message_id": None, "call_id": None,
            "created_at": now, "updated_at": now,
        }
        self.rows.append(row)
        return row

    def update_restaurant(self, snapshot_id: str, **fields) -> dict | None:
        for row in self.rows:
            if row["id"] != snapshot_id:
                continue
            if "state" in fields and fields["state"] not in _STATES:
                raise ValueError("Invalid restaurant snapshot state")
            row.update(fields)
            if "terms_json" in fields:
                row["terms"] = json.loads(fields["terms_json"])
            row["updated_at"] = datetime.now().isoformat()
            return row
        return None

    def restaurant_for_call(self, call_id: str) -> dict | None:
        for row in self.rows:
            if row.get("call_id") == call_id:
                return row
        return None


def _store_for(caller):
    if getattr(caller, "snapshots", None) is not None:
        return caller.snapshots
    if getattr(caller, "_memory_snapshots", None) is None:
        caller._memory_snapshots = MemoryRestaurantStore()
    return caller._memory_snapshots


def _apply_configured(terms: dict, explicit: dict, caller) -> dict:
    merged = dict(terms)
    if not merged.get("owner_name"):
        merged["owner_name"] = usable_owner_name(getattr(caller, "owner_name", "") or "")
    if not explicit.get("callback_number"):
        configured = extract_phone(getattr(caller, "callback_number", "") or "")
        if configured and configured != merged.get("destination_phone"):
            if not merged.get("callback_number"):
                merged["callback_number"] = configured
        elif merged.get("callback_number") == merged.get("destination_phone"):
            merged["callback_number"] = ""
    if explicit.get("callback_number") and explicit["callback_number"] == merged.get("destination_phone"):
        merged["callback_number"] = explicit["callback_number"]
    return merged


def _lookup_phone(caller, venue: str, location: str = "") -> dict:
    finder = getattr(caller, "phone_lookup", None)
    if not finder or not venue:
        return {}
    try:
        try:
            found = finder(venue, location)
        except TypeError:
            found = finder(venue)
    except Exception:
        return {}
    if not isinstance(found, dict):
        return {}
    if found.get("ambiguous_locations"):
        labels = [str(item) for item in found["ambiguous_locations"] if str(item).strip()]
        return {"location_options": ", ".join(labels)}
    number = found.get("number") or ""
    source = found.get("source_url") or ""
    from app.browser.agent import public_http_url
    if extract_phone(number) != number or not public_http_url(source):
        return {}
    result = {"destination_phone": number, "destination_source": public_http_url(source)}
    zone = found.get("timezone") or ""
    if isinstance(zone, str) and zone:
        result["timezone"] = zone
    return result


def _brief_reply(terms: dict, missing: list[str]) -> str:
    venue = terms.get("venue") or "the restaurant"
    if terms.get("location_options") and not terms.get("destination_phone"):
        found = (f"{venue} has more than one published location "
                 f"({terms['location_options']}). Tell me which location. ")
    elif terms.get("destination_phone") and terms.get("destination_source"):
        found = (f"I found {venue} at {terms['destination_phone']} "
                 f"({terms['destination_source']}). ")
    elif terms.get("venue"):
        found = f"I do not have a verified public phone number for {venue} yet. "
    else:
        found = ""
    if missing:
        return (f"{found}I still need {', '.join(missing)}. "
                "I will not guess the owner or a callback number, and I will not "
                "place a call yet.")
    return (
        f"I can call {venue} at {terms['destination_phone']} from "
        f"{terms['destination_source']} for {terms['party_size']} on {terms['date']} "
        f"at {terms['time']} {terms['timezone']} under {terms['guest_name']}, "
        f"on behalf of {terms['owner_name']}, callback {terms['callback_number']}. "
        "Reply yes in this chat to place the call."
    )


def _result(terms: dict, notes: str, *, status: str = "need_confirm",
            dialed: bool = False, transport: str = "restaurant",
            prepared_call: dict | None = None, call_id: str | None = None,
            provider_status: str | None = None) -> CallResult:
    return CallResult(
        status=status, transport=transport, dialed=dialed,
        venue=terms.get("venue") or "", party_size=terms.get("party_size") or None,
        time=terms.get("time") or None, notes=notes, prepared_call=prepared_call,
        call_id=call_id, provider_status=provider_status,
    )


def _claim(store, message_id: str, chat_id: str, destination: str, status: str) -> bool:
    if not message_id:
        return True
    claim = getattr(store, "claim", None)
    if claim is None:
        return True
    return bool(claim(message_id, chat_id, destination, status=status))


def _record_provider(store, message_id: str, result: CallResult) -> None:
    record = getattr(store, "record_result", None)
    if record is None or not message_id:
        return
    provider_status = result.provider_status or "failed"
    stored = "queued" if provider_status == "ended" else provider_status
    if stored not in {"queued", "scheduled", "ringing", "in-progress", "forwarding", "ended", "failed"}:
        stored = "failed"
    record(message_id, call_id=result.call_id, status=stored if result.call_id else "failed")


def _now(caller) -> datetime:
    clock = getattr(caller, "now", None)
    current = clock() if callable(clock) else clock
    if not isinstance(current, datetime):
        current = datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current


def _apply_location(terms: dict, text: str) -> None:
    from app.browser.agent import CITY_TIMEZONES, cities_in_text
    cities = cities_in_text(_body(text))
    zones = {CITY_TIMEZONES[city] for city in cities}
    if len(zones) != 1 or not cities:
        return
    terms["location"] = max(cities, key=len)
    if not terms.get("timezone"):
        terms["timezone"] = next(iter(zones))


def _local_now(terms: dict, caller) -> datetime:
    current = _now(caller)
    zone = terms.get("timezone") or ""
    if not zone:
        return current.astimezone(timezone.utc)
    try:
        return current.astimezone(ZoneInfo(zone))
    except ZoneInfoNotFoundError:
        return current.astimezone(timezone.utc)


def _resolve_date(terms: dict, text: str, caller) -> None:
    """Fill an exact date from tonight, tomorrow, or a month and day without a year."""
    if terms.get("date"):
        terms.pop("relative_day", None)
        return
    body = _body(text)
    relative = {match.group(1).lower() for match in _RELATIVE_DAY.finditer(body)}
    saved = terms.get("relative_day") or ""
    if saved in {"tonight", "today", "tomorrow"}:
        relative.add("tonight" if saved in {"tonight", "today"} else "tomorrow")
    local = _local_now(terms, caller)
    if relative:
        mixed = "tomorrow" in relative and relative - {"tomorrow"}
        if not terms.get("timezone") or mixed:
            if not mixed and relative:
                terms["relative_day"] = "tomorrow" if relative == {"tomorrow"} else "tonight"
            return
        if relative == {"tomorrow"}:
            terms["date"] = (local.date() + timedelta(days=1)).isoformat()
        else:
            terms["date"] = local.date().isoformat()
        terms.pop("relative_day", None)
        return
    days = []
    for match in _MONTH_DAY.finditer(body):
        month = _MONTHS.get(match.group(1).lower())
        if not month:
            continue
        day = int(match.group(2))
        try:
            candidate = date(local.year, month, day)
        except ValueError:
            continue
        if candidate < local.date():
            try:
                candidate = date(local.year + 1, month, day)
            except ValueError:
                continue
        days.append(candidate.isoformat())
    if len(set(days)) == 1:
        terms["date"] = days[0]


def _absorb_lookup(terms: dict, caller, explicit: dict) -> None:
    if not terms.get("venue") or terms.get("destination_phone"):
        return
    found = _lookup_phone(caller, terms["venue"], terms.get("location") or "")
    if found.get("destination_phone"):
        terms["destination_phone"] = found["destination_phone"]
        terms["destination_source"] = found["destination_source"]
        terms.pop("location_options", None)
        if found.get("timezone") and not terms.get("timezone"):
            terms["timezone"] = found["timezone"]
    elif found.get("location_options"):
        terms["location_options"] = found["location_options"]
        terms["destination_phone"] = ""
        terms["destination_source"] = ""
    if (not explicit.get("callback_number")
            and terms.get("callback_number")
            and terms["callback_number"] == terms.get("destination_phone")):
        terms["callback_number"] = ""


def advance_restaurant_request(caller, text: str, *, chat_id: str, message_id: str) -> CallResult | None:
    store = _store_for(caller)
    booking = looks_like_restaurant_booking(text)
    previous = store.open_restaurant(chat_id)
    explicit = explicit_terms(text)
    previous_venue = (previous or {}).get("terms", {}).get("venue") or ""
    venue_changed = bool(
        previous and explicit.get("venue")
        and explicit["venue"].casefold() != previous_venue.casefold()
    )
    if previous and is_cancel(text) and not venue_changed:
        if not _claim(store, message_id, chat_id, "", "noted"):
            return None
        store.update_restaurant(previous["id"], state="superseded")
        venue = previous["terms"].get("venue") or "the restaurant"
        return _result(previous["terms"], f"Cancelled the restaurant call for {venue}.")
    if (previous and previous["state"] == "awaiting_authorization"
            and is_pure_authorization(text) and not booking and not venue_changed):
        return _authorize(caller, store, previous, chat_id, message_id)
    if previous and not venue_changed:
        terms = dict(previous["terms"])
        for key, value in explicit.items():
            if value not in ("", None):
                terms[key] = value
        kept = True
    else:
        terms = dict(explicit)
        kept = False
    previous_location = (previous["terms"].get("location") or "") if kept and previous else ""
    _apply_location(terms, text)
    if kept and terms.get("location") and terms["location"] != previous_location:
        if previous_location or terms.get("location_options"):
            terms["destination_phone"] = ""
            terms["destination_source"] = ""
            terms.pop("location_options", None)
    terms = _apply_configured(terms, explicit, caller)
    _absorb_lookup(terms, caller, explicit)
    _resolve_date(terms, text, caller)
    missing = missing_terms(terms)
    state = "collecting" if missing else "awaiting_authorization"
    destination = terms.get("destination_phone") or ""
    if not _claim(store, message_id, chat_id, destination if state == "awaiting_authorization" else "", "noted"):
        return None
    digest = terms_digest(terms)
    payload = json.dumps(terms, sort_keys=True)
    if kept and previous:
        store.update_restaurant(
            previous["id"], state=state, terms_json=payload, terms_digest=digest)
    else:
        store.save_restaurant(
            chat_id=chat_id, terms=terms, digest=digest, state=state,
            source_message_id=message_id)
    return _result(terms, _brief_reply(terms, missing))


def _authorize(caller, store, row: dict, chat_id: str, message_id: str) -> CallResult | None:
    terms = dict(row["terms"])
    if terms_digest(terms) != row.get("terms_digest") or missing_terms(terms):
        return _result(terms, "The saved reservation brief does not match.")
    overrides = restaurant_assistant_overrides(terms)
    destination = terms["destination_phone"]
    vapi = getattr(caller, "vapi", None)
    ready = bool(vapi is not None and getattr(vapi, "ready", lambda: False)())
    dry_run = bool(getattr(caller, "dry_run", False))
    if dry_run or not ready:
        if not _claim(store, message_id, chat_id, "" if dry_run or not ready else destination,
                      "noted"):
            return None
        body = None
        if vapi is not None and hasattr(vapi, "prepare_call") and ready:
            body = vapi.prepare_call(to_number=destination, assistant_overrides=overrides)
        else:
            body = {"customer": {"number": destination}, "assistantOverrides": overrides}
        if dry_run:
            store.update_restaurant(
                row["id"], state="authorized", authorization_message_id=message_id or None)
            notes = (
                f"Prepared a Vapi call to {destination} for {terms['venue']} on behalf of "
                f"{terms['owner_name']}, for {terms['party_size']} on {terms['date']} at "
                f"{terms['time']} {terms['timezone']} under {terms['guest_name']}. "
                "Dry-run only; the call was not placed."
            )
            return _result(terms, notes, prepared_call=body)
        notes = f"Vapi is not configured, so I did not place the call to {terms['venue']}."
        return _result(terms, notes, prepared_call=body)
    # Claim before POST. Deferring the claim would let a retry place a second call.
    if not _claim(store, message_id, chat_id, destination, "dialing"):
        return _recover_unidentified(store, row, message_id, destination)
    store.update_restaurant(
        row["id"], state="dialing", authorization_message_id=message_id or None)
    request = ReservationRequest(
        venue=terms["venue"], party_size=terms["party_size"], time=terms["time"],
        guest_name=terms["guest_name"], callback_number=terms["callback_number"],
        destination_phone=destination, chat_id=chat_id,
    )
    result = caller._dial_vapi(request, assistant_overrides=overrides)
    body = None
    if hasattr(vapi, "prepare_call"):
        try:
            body = vapi.prepare_call(to_number=destination, assistant_overrides=overrides)
        except Exception:
            body = {"customer": {"number": destination}, "assistantOverrides": overrides}
    from dataclasses import replace
    result = replace(result, prepared_call=body)
    if result.dialed and result.call_id:
        store.update_restaurant(row["id"], state="placed", call_id=result.call_id)
        _record_provider(store, message_id, result)
        return result
    uncertain = "unknown" in (result.notes or "") or "check the dashboard" in (result.notes or "")
    store.update_restaurant(row["id"], state="unknown" if uncertain else "failed")
    if message_id:
        _record_provider(store, message_id, result)
    return replace(result, transport="restaurant",
                   notes=result.notes or "The call did not start.")


def _recover_unidentified(store, row: dict, message_id: str, destination: str) -> CallResult | None:
    """A dialing claim with no provider id is unknown. Never place that call again."""
    existing = store.get(message_id) if hasattr(store, "get") else None
    if not existing or existing.get("call_id") or existing.get("status") != "dialing":
        return None
    abandon = getattr(store, "abandon_unidentified", None)
    if abandon is not None and not abandon(message_id):
        return None
    store.update_restaurant(row["id"], state="unknown")
    return _result(row["terms"],
                   f"The call to {destination} was claimed but has no provider id. "
                   "Check Vapi manually. I did not redial.")
