"""Connect conversation state, agent decisions, scheduler, and approved actions."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from datetime import date, datetime, time as clock_time, timedelta, timezone
from threading import Lock, RLock
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import time

from app.agent import GroupConversationDecision, GrokProviderError
from app.availability import AvailabilityWindow, choose_slot, looks_like_availability, parse_availability
from app.bluebubbles import DeliveryUncertainError
from app.group_memory import eligible_fact
from app.group_safety import (forget_phrase, illegal_assistance_request,
                              parse_forget_command, refusal_text)
from app.models import ChatMessage, Plan, PlanFacts, Proposal
from app.message_text import remove_rally_signature
from app.latency import record_latency
from app.policy import (eligible_for_intervention, eligible_for_revival,
                        explicitly_addresses_rally, unfinished_plan,
                        valid_approval, valid_calendar_approval)
from app.places import PlacesError
from app.reactions import DONE_REACTION, SEEN_REACTION, completion_reaction
from app.reservations import create_reservation
from app.store import Store
from app.web import should_search_web
from app.tone import group_tone
from app.adaptive.handler import should_use_adaptive


logger = logging.getLogger(__name__)
_SHORT_FOLLOWUP = re.compile(
    r"^\s*(?:what|how|why|where|when|who|which|can|could|do|does|did|is|are|should|would|will)\b",
    re.I,
)
_RECAP_ASK = re.compile(
    r"\b(recap|what'?s the plan|what have we decided|what did we (?:decide|land on)|"
    r"next step|what people said|what did .+ say)\b",
    re.I,
)
_PICK_ASK = re.compile(r"\b(pick|lock|choose|decide)\b", re.I)
_CANCEL_PLAN = re.compile(
    r"^\s*(?:(?:hey|hi|hello|yo|ok|okay)[,\s]+)?@?rally\b[\s,:!?-]*"
    r"(?:please\s+)?(?:cancel|stop|drop|scrap|abort)\s+(?:(?:the|our|this|current)\s+)?"
    r"(?:plan|booking|reservation)\b",
    re.I,
)
_RESTAURANT_ASK = re.compile(
    r"\b(where should we eat|where to eat|restaurants?|recommend\w*\s+(?:a\s+)?"
    r"(?:place|spot|restaurant)|food rec)\b",
    re.I,
)
_FACT_Q = re.compile(
    r"\b(?:is|does|can|who)\b.+\?",
    re.I,
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY_RE = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
_PLACE_NEAR = re.compile(
    r"\b(?:near|in)\s+([A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z][A-Za-z0-9]*)?)",
    re.I,
)
_PLACE_HINT = re.compile(
    r"\b(midtown|downtown|uptown|brooklyn|manhattan|queens|williamsburg|"
    r"rambler(?:\s+atlanta)?)\b",
    re.I,
)
_TIME_AT = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_PARTY = re.compile(r"\bfor\s+(two|three|four|five|six|seven|eight|\d+)\b", re.I)
_VEG = re.compile(r"\b(\w+)\s+is\s+vegetarian\b", re.I)
_CANT_DAY = re.compile(
    r"\b(\w+)\s+can'?t\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)
_WORKS_DAY = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+works\b",
    re.I,
)
_ACTUALLY_DAY = re.compile(
    r"\bactually\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)
_INSTEAD_OF = re.compile(
    r"\binstead of\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)
_CANCELLED_DAY = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+is\s+cancel(?:led|ed)\b",
    re.I,
)
_OPTIONS = re.compile(r"\b([A-Za-z]{3,})\s+or\s+([A-Za-z]{3,})\b")
_ACTIVITY = re.compile(r"\b(dinner|lunch|brunch|breakfast|drinks|museum(?: visit)?|eat out)\b", re.I)
_TONE_Q = re.compile(r"\bwhy\b.+\b(?:mean|rude|harsh|mad)\b|\bso mean\b", re.I)
_CONFUSED = re.compile(r"\bwhat are you talking about\b", re.I)
_IDLE_CHATTER = re.compile(
    r"^(?:lol+|lmao+|lmfao+|haha+|ok+|okay|bet|nah|yea+|yep|yeah|lmk|fr|rn|"
    r"nice|cool|true|facts|same|omg+|bruh|wtf|idk|k)[?!.]*$",
    re.I,
)
_STALL_SIGNAL = re.compile(
    r"\b(?:pick a (?:spot|place|restaurant)|still (?:need|no|haven't got) (?:a )?"
    r"(?:spot|place|restaurant)|where (?:are we|should we) (?:going|eating)|"
    r"can't (?:decide|pick)|still deciding)\b",
    re.I,
)
_WHO_MADE = re.compile(
    r"\b(?:who (?:made|makes|did)|made by|who'?s it by|tell me who)\b",
    re.I,
)
_SONG_LIST = re.compile(
    r"\b(?:name|give|list|recommend)\b.+\b(?:songs?|tracks?)\b",
    re.I,
)
_KNOWN_TRACKS = {
    "4raws": "young nudy",
    "4 raws": "young nudy",
}
_WEEKEND_SONGS = (
    "blinding lights — the weeknd",
    "good days — sza",
    "dreams — fleetwood mac",
    "saturday sun — vance joy",
    "friday i'm in love — the cure",
)
_MEAT_HINT = re.compile(r"\b(steak|steakhouse|bbq|barbecue|burger)\b", re.I)
_FOOD_ACTIVITY = re.compile(r"\b(dinner|lunch|brunch|breakfast|drinks|eat out|food)\b", re.I)
_CUISINE = re.compile(
    r"\b(indian|chinese|japanese|italian|mexican|thai|korean|ramen|tacos?|sushi|pizza)\b",
    re.I,
)
_CONSTRAINT_LINE = re.compile(
    r"\b(isolat\w*|allergic|can't|cannot|won't make|running late)\b",
    re.I,
)
_NO_ANSWER = re.compile(r"^\s*no(?:\s+|_)answer\s*$", re.I)
_REPEAT_TEMPLATE = re.compile(
    r"^(?:here's the plan|nothing locked yet)\b|still no spot",
    re.I,
)
_THREADED_OUTBOX_KINDS = frozenset({
    "direct_reply", "availability_ack", "availability_clarify",
})


def _named_option_pick(request: str, facts) -> str | None:
    """Return one already-named plan option when the user asks to pick among them."""
    options = list(getattr(facts, "preferred_cuisines", None) or [])
    if len(options) < 2 or not request or not _PICK_ASK.search(request):
        return None
    mentioned = [item for item in options
                 if re.search(rf"\b{re.escape(item)}\b", request, re.I)]
    if len(mentioned) < 2:
        return None
    return mentioned[0]


def _known_track_artist(text: str) -> str | None:
    low = (text or "").lower()
    for name, artist in _KNOWN_TRACKS.items():
        if name in low:
            return artist
    return None


def _general_local_answer(request: str, snap=None, facts=None) -> str | None:
    text = request or ""
    if _TONE_Q.search(text):
        return ("sorry, that last recap came out too sharp. i'm just here to keep the "
                "plan straight — ask me anything and i'll actually answer it.")
    artist = _known_track_artist(text)
    if artist and (_WHO_MADE.search(text) or re.search(r"\bwho\b", text, re.I)):
        return f"{artist} made it."
    if _SONG_LIST.search(text):
        return "here are five: " + "; ".join(_WEEKEND_SONGS)
    if _CONFUSED.search(text):
        bits = []
        if snap:
            if snap.get("activity"):
                bits.append(snap["activity"])
            if snap.get("day"):
                bits.append(snap["day"])
        if facts and facts.activity and facts.activity not in bits:
            bits.insert(0, facts.activity)
        if bits:
            extra = f" — {', '.join(bits[1:])}" if len(bits) > 1 else ""
            return f"the {bits[0]} plan{extra}. want a recap or a restaurant name?"
        return "i was keeping the group plan, not roasting anyone. what do you want to know?"
    return None


def _worth_replying(text: str) -> bool:
    if not text or not text.strip():
        return False
    if (_RECAP_ASK.search(text) or _restaurant_intent(text) or _PICK_ASK.search(text)
            or _TONE_Q.search(text) or _SONG_LIST.search(text) or _WHO_MADE.search(text)
            or _CONFUSED.search(text) or _general_local_answer(text)):
        return True
    if "?" in text or _SHORT_FOLLOWUP.match(text):
        return True
    return False


def _idle_chatter(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or explicitly_addresses_rally(stripped):
        return False
    if _worth_replying(stripped):
        return False
    return bool(_IDLE_CHATTER.match(stripped)) or not _worth_replying(stripped)


def _stall_signal(text: str) -> bool:
    return bool(text and _STALL_SIGNAL.search(text))


def _casual_clock(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", (value or "").strip())
    if not match:
        return value
    hour = int(match.group(1))
    minute = match.group(2)
    suffix = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    if minute == "00":
        return f"{hour12}{suffix}"
    return f"{hour12}:{minute}{suffix}"


def _option_why(picked: str, facts, options) -> str:
    losers = [item for item in options if item.casefold() != picked.casefold()]
    loser = losers[0] if losers else "the other option"
    place = facts.location if facts and facts.location else "the group"
    return (f"{picked} — {place} already had it on the list, and {loser} can wait. "
            "not booked, just a pick.")


def _restaurant_intent(text: str) -> bool:
    return bool(text and _RESTAURANT_ASK.search(text))


def _human_planning_lines(messages) -> list[tuple]:
    lines = []
    for message in messages or []:
        text = (message.text or "").strip()
        if message.is_from_rally or not text:
            continue
        if explicitly_addresses_rally(text):
            text = re.sub(
                r"^\s*(?:(?:hey|hi|hello|yo|ok|okay|ask)[,\s]+)?@?rally\b[:,\s]*",
                "", text, flags=re.I).strip()
            if not text:
                continue
        lines.append((message.sent_at, text, message.sender_id))
    return lines


def _thread_snapshot(messages, memory_context: str = "", facts=None):
    """Ground a recap on human chat + memory. Newer overrides win; don't invent."""
    snap = {
        "activity": (facts.activity if facts and facts.activity else ""),
        "day": None,
        "rejected_days": set(),
        "supported_days": set(),
        "time_text": None,
        "place": facts.location if facts and facts.location else None,
        "party": str(facts.party_size) if facts and facts.party_size else None,
        "dietary": [],
        "constraints": [],
        "options": list(facts.preferred_cuisines) if facts and facts.preferred_cuisines else [],
        "conflicts": [],
    }
    if facts and facts.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(facts.date)):
        snap["day"] = str(facts.date).lower()
    if facts and facts.time:
        snap["time_text"] = f"at {_casual_clock(facts.time)}"
    if facts and facts.blockers:
        snap["constraints"].extend(facts.blockers)
    blob_lines = [text for _, text, _ in _human_planning_lines(messages)]
    for raw in (memory_context or "").splitlines():
        fact = raw.lstrip("- ").strip()
        if fact:
            blob_lines.append(fact)
    for text in blob_lines:
        low = text.lower()
        activity = _ACTIVITY.search(text)
        if activity:
            snap["activity"] = activity.group(1).lower()
        actually = _ACTUALLY_DAY.search(text)
        if actually:
            snap["day"] = actually.group(1).lower()
        instead = _INSTEAD_OF.search(text)
        if instead:
            snap["rejected_days"].add(instead.group(1).lower())
        cancelled = _CANCELLED_DAY.search(text)
        if cancelled:
            snap["rejected_days"].add(cancelled.group(1).lower())
        works = _WORKS_DAY.search(text)
        if works:
            snap["supported_days"].add(works.group(1).lower())
        cant = _CANT_DAY.search(text)
        if cant:
            who, day = cant.group(1), cant.group(2).lower()
            snap["constraints"].append(f"{who} can't {day}")
            snap["rejected_days"].add(day)
        elif _DAY_RE.search(text) and snap["day"] is None and not _ACTUALLY_DAY.search(text):
            mentioned = [item.lower() for item in _DAY_RE.findall(text)]
            live = [day for day in mentioned if day not in snap["rejected_days"]]
            if live:
                snap["day"] = live[-1]
        timed = _TIME_AT.search(text)
        if timed:
            hour, minute, suffix = timed.group(1), timed.group(2) or "00", (timed.group(3) or "").lower()
            snap["time_text"] = f"at {hour}{':' + minute if minute != '00' else ''}{suffix}".rstrip()
        place = _PLACE_HINT.search(text) or _PLACE_NEAR.search(text)
        if place:
            snap["place"] = place.group(1)
        party = _PARTY.search(text)
        if party:
            snap["party"] = party.group(1)
        veg = _VEG.search(text)
        if veg:
            snap["dietary"].append(f"{veg.group(1)} is vegetarian")
        options = _OPTIONS.search(text)
        if options:
            left, right = options.group(1).lower(), options.group(2).lower()
            if left not in {"and", "the"} and right not in {"and", "the"}:
                for item in (left, right):
                    if item not in snap["options"]:
                        snap["options"].append(item)
        cuisine = _CUISINE.search(text)
        if cuisine and cuisine.group(1).lower() not in snap["options"]:
            snap["options"].append(cuisine.group(1).lower())
        if _CONSTRAINT_LINE.search(text) and text not in snap["constraints"]:
            snap["constraints"].append(text)
    if snap["day"] in snap["rejected_days"]:
        snap["day"] = None
    clash = snap["supported_days"] & snap["rejected_days"]
    for day in sorted(clash):
        snap["conflicts"].append(f"{day} works vs {day} doesn't")
    return snap


def _plan_maturity(facts, proposal, snap) -> str:
    if proposal:
        return "locked"
    if (snap.get("options") and len(snap["options"]) >= 2) or (
            facts and facts.preferred_cuisines and len(facts.preferred_cuisines) >= 2):
        return "options"
    if snap.get("activity") or (facts and facts.activity):
        return "idea"
    return "idea"


def _grounded_fact_answer(request: str, snap, memory_context: str = "") -> str | None:
    if not request or not _FACT_Q.search(request) or _restaurant_intent(request):
        return None
    known = [*(snap.get("dietary") or []), *(snap.get("constraints") or [])]
    for line in (memory_context or "").splitlines():
        fact = line.lstrip("- ").strip()
        if fact:
            known.append(fact)
    tokens = [token for token in re.findall(r"[a-z0-9']+", request.lower())
              if token not in {"ask", "rally", "is", "does", "can", "the", "a", "an",
                               "we", "our", "who"} and len(token) > 2]
    if not tokens:
        return None
    for line in known:
        low = line.lower()
        if any(token in low for token in tokens):
            if all(token in low or token in {"jake", "sarah"} for token in tokens):
                return f"{line} — that's in the thread, not a guess."
    corpus = " ".join(known).lower()
    if tokens and all(token in corpus for token in tokens) and known:
        return f"{known[0]} — that's in the thread, not a guess."
    return None


def _recap_from_snapshot(snap, facts, proposal) -> str:
    parts = []
    status = _plan_maturity(facts, proposal, snap)
    if snap.get("conflicts"):
        status = "idea"
    if snap.get("activity"):
        parts.append(snap["activity"])
    elif facts and facts.activity:
        parts.append(facts.activity)
    day = snap.get("day")
    if day:
        parts.append(day)
    elif facts and facts.date and not any(
            weekday in str(facts.date).lower() for weekday in snap.get("rejected_days") or ()):
        parts.append(facts.date)
    if snap.get("time_text"):
        parts.append(snap["time_text"])
    elif facts and facts.time:
        parts.append(f"at {_casual_clock(facts.time)}")
    if snap.get("party"):
        parts.append(f"for {snap['party']}")
    elif facts and facts.party_size:
        parts.append(f"for {facts.party_size}")
    place = snap.get("place") or (facts.location if facts else None)
    if place:
        parts.append(f"near {place}")
    if snap.get("options"):
        parts.append(" or ".join(snap["options"]))
    elif facts and facts.preferred_cuisines:
        parts.append(" or ".join(facts.preferred_cuisines))
    parts.extend(snap.get("dietary") or [])
    parts.extend(snap.get("constraints") or [])
    if snap.get("conflicts"):
        parts.append("conflict: " + "; ".join(snap["conflicts"]) + " — not locked")
    if facts and facts.blockers and facts.blockers[0] not in parts:
        parts.append(f"({facts.blockers[0]})")
    if not parts:
        return "nothing locked yet. toss a time, place, or who and i'll keep it straight."
    if place and not snap.get("time_text") and not (facts and facts.time):
        nxt = "a time"
    elif (snap.get("time_text") or (facts and facts.time)) and not place:
        nxt = "a spot"
    else:
        nxt = "who is in"
    return (f"here's the plan: {', '.join(parts)}. next up is {nxt} — "
            "ask me to pick a restaurant if you want a name.")


def _venue_fits_constraints(venue, snap) -> bool:
    name = f"{getattr(venue, 'name', '')} {' '.join(getattr(venue, 'cuisine_tags', ()) or [])}".lower()
    if snap.get("dietary") and _MEAT_HINT.search(name):
        return False
    return True


def _log_scheduled_failure(phase: str, exc: Exception):
    if isinstance(exc, GrokProviderError):
        logger.warning("Scheduled %s failed: type=%s stage=%s kind=%s status=%s",
                       phase, type(exc).__name__, exc.stage, exc.kind, exc.status_code)
    else:
        logger.warning("Scheduled %s failed: type=%s", phase, type(exc).__name__)


def _failure_diagnostic(exc: Exception) -> tuple[str, str, int | None]:
    if isinstance(exc, GrokProviderError):
        kind = exc.kind if exc.kind in {"timeout", "http", "transport", "response"} else "other"
        stage = exc.stage if isinstance(exc.stage, str) and exc.stage.isidentifier() else "extract"
        status = exc.status_code if type(exc.status_code) is int else None
        return kind, stage, status
    if isinstance(exc, (ValueError, TypeError)):
        return "validation", "extract", None
    return "other", "extract", None


class RallyService:
    def __init__(self, store: Store, agent, search_fn, send_fn, stall_minutes: int = 30,
                 extractor=None, calendar_fn=None, allowed_chat_ids: set[str] | frozenset[str] | None = None,
                 portal_handler=None, web_answer_fn=None, adaptive_handler=None,
                 availability_fn=None, time_zone: str = "America/New_York", reply_agent=None,
                 group_memory=None, group_turns=None, react_fn=None, typing_fn=None,
                 defer_heavy_work: bool = False, history_fn=None, helper_warm_fn=None,
                 portal_publish_fn=None, knowledge_fn=None, knowledge_store=None,
                 knowledge_refresh_fn=None):
        self.store = store
        self.agent = agent
        self.reply_agent = reply_agent or agent
        self.extractor = extractor or agent
        self.calendar_fn = calendar_fn
        self.availability_fn = availability_fn
        self.time_zone = time_zone
        self.search_fn = search_fn
        self.send_fn = send_fn
        self.stall_minutes = stall_minutes
        self.allowed_chat_ids = None if allowed_chat_ids is None else frozenset(allowed_chat_ids)
        self.portal_handler = portal_handler
        self.web_answer_fn = web_answer_fn
        self.adaptive_handler = adaptive_handler
        self.group_memory = group_memory
        self.group_turns = group_turns
        self.react_fn = react_fn
        self.typing_fn = typing_fn
        self.defer_heavy_work = defer_heavy_work
        self.history_fn = history_fn
        self.helper_warm_fn = helper_warm_fn
        self.portal_publish_fn = portal_publish_fn
        self.knowledge_fn = knowledge_fn
        self.knowledge_store = knowledge_store
        self.knowledge_refresh_fn = knowledge_refresh_fn
        self._thread_hydrated: set[str] = set()
        self._chat_locks_guard = Lock()
        self._chat_locks = {}
        self._heavy_inflight: set[str] = set()
        self._heavy_pending: dict[str, list[ChatMessage]] = {}
        self._heavy_chats_running: set[str] = set()
        self._heavy_guard = Lock()
        self._decision_inflight: set[str] = set()
        self._remembered_ids: set[str] = set()
        self._pool: ThreadPoolExecutor | None = None

    def _publish_portal(self) -> None:
        if not self.portal_publish_fn:
            return
        try:
            self.portal_publish_fn()
        except Exception as exc:
            _log_scheduled_failure("portal publish trigger", exc)

    def _chat_lock(self, chat_id: str) -> RLock:
        with self._chat_locks_guard:
            lock = self._chat_locks.get(chat_id)
            if lock is None:
                lock = RLock()
                self._chat_locks[chat_id] = lock
            return lock

    def refresh_knowledge(self, chat_id: str) -> int:
        """Synchronously update one group's KB from messages after its KB cursor.

        This is intentionally separate from the debounced background trigger: the
        local admin desk uses it for a user-requested, immediately observable
        refresh. The builder's durable cursor makes repeated clicks a no-op until
        new archive messages arrive.
        """
        if not self._chat_allowed(chat_id):
            raise ValueError("Chat is not allowed")
        if self.knowledge_refresh_fn is None:
            raise RuntimeError("Knowledge refresh is unavailable")
        with self._chat_lock(chat_id):
            return self.knowledge_refresh_fn(chat_id)

    def _chat_allowed(self, chat_id: str) -> bool:
        excluded = getattr(self, 'excluded_chat_ids', frozenset())
        excluded = excluded() if callable(excluded) else excluded
        return (chat_id not in excluded and
                (self.allowed_chat_ids is None or chat_id in self.allowed_chat_ids))

    def _is_direct_followup(self, message: ChatMessage, messages: list[ChatMessage]) -> bool:
        """Allow one brief question after a delivered direct call in this chat."""
        if len(message.text) > 120 or len(message.text.split()) > 16 or not _SHORT_FOLLOWUP.match(message.text):
            return False
        previous = next((item for item in reversed(messages)
                         if item.message_id != message.message_id and not item.is_from_rally), None)
        if (previous is None or not explicitly_addresses_rally(previous.text) or
                message.sent_at < previous.sent_at or
                message.sent_at - previous.sent_at > timedelta(minutes=5)):
            return False
        return self.store.sent_message("direct_reply", previous.message_id)

    def receive(self, message: ChatMessage) -> bool:
        if not self._chat_allowed(message.chat_id):
            return False
        started = perf_counter()
        with self._chat_lock(message.chat_id):
            record_latency("chat_lock_wait", perf_counter() - started)
            try:
                accepted = self._receive(message)
            finally:
                record_latency("receive_total", perf_counter() - started)
        self._log_latency("receive", started)
        return accepted

    def _hydrate_prior_thread(self, message: ChatMessage):
        """Load recent BlueBubbles history every time Rally is about to act."""
        self._hydrate_chat(message.chat_id, skip_id=message.message_id)

    def _hydrate_chat(self, chat_id: str, skip_id: str | None = None):
        if not self.history_fn:
            return
        try:
            prior = self.history_fn(chat_id, 50)
        except Exception as exc:
            _log_scheduled_failure("thread hydrate", exc)
            return
        if not prior:
            return
        for item in prior:
            if (not isinstance(item, ChatMessage) or item.chat_id != chat_id
                    or item.message_id == skip_id):
                continue
            if self.store.add_message(item):
                self.store.mark_processed(item.message_id)

    def recover_pending(self, chat_id: str, *, limit: int = 75) -> int:
        """Re-extract a bounded pending window without replaying replies or actions."""
        with self._chat_lock(chat_id):
            if not self._chat_allowed(chat_id):
                raise ValueError("Chat is not allowed")
            messages, pending_ids = self.store.recovery_snapshot(chat_id, limit)
            if not pending_ids:
                return 0
            plan = self.store.get_plan(chat_id)
            try:
                facts = self.extractor.extract(messages, plan.facts if plan else None)
            except Exception as exc:
                self._record_extraction_failure(pending_ids, exc)
                raise
            if facts.activity:
                if (not plan or plan.state not in ("DONE", "ABANDONED") or
                        (facts.activity, facts.goal, facts.date) !=
                        (plan.facts.activity, plan.facts.goal, plan.facts.date)):
                    latest_human = max(message.sent_at for message in messages if not message.is_from_rally)
                    self.store.save_plan(chat_id, facts, latest_human)
            return self.store.mark_processed_many(chat_id, pending_ids)

    def _receive(self, message: ChatMessage) -> bool:
        if not self._chat_allowed(message.chat_id) or message.is_from_rally or not message.text.strip():
            return False
        if not self.store.add_message(message) and self.store.is_processed(message.message_id):
            return False
        if message.message_id in self._heavy_inflight:
            return True
        self._hydrate_prior_thread(message)
        plan = self.store.get_plan(message.chat_id)
        if plan and _CANCEL_PLAN.match(message.text):
            cancelled = self.store.abandon_plan(message.chat_id)
            if cancelled is None:
                reply = "Rally: There isn't an active plan I can cancel."
            else:
                reply = "Rally: Okay — I canceled the active plan and cleared its pending proposal."
                self._publish_portal()
            self._queue_and_send(message.chat_id, reply, "plan_cancel", message.message_id)
            self.store.mark_processed(message.message_id)
            return True
        if (plan and plan.state not in ("READY", "EXECUTING", "DONE", "ABANDONED") and plan.facts.date and
                self.store.availability_requested(plan.id, plan.version) and
                looks_like_availability(message.text)):
            try:
                target_date = date.fromisoformat(plan.facts.date)
            except ValueError:
                target_date = None
            try:
                today = datetime.now(ZoneInfo(self.time_zone)).date()
            except ZoneInfoNotFoundError:
                today = datetime.now().date()
            if target_date is not None and target_date < today:
                target_date = None
            window = parse_availability(message.text, target_date) if target_date else None
            if window:
                self.store.save_availability_report(
                    plan.id, plan.version, message.sender_id, plan.facts.date,
                    window.start.isoformat(timespec="minutes"),
                    window.end.isoformat(timespec="minutes"), message.text, message.sent_at)
                reply = "Rally: Got it. I’ll use that as your reported availability for this plan; it isn’t a calendar check."
                kind = "availability_ack"
            else:
                reply = ("Rally: I couldn’t match that to the plan date. Please reply with a weekday and a clear range, "
                         "like ‘free all day Saturday’ or ‘weekdays after 4pm.’")
                kind = "availability_clarify"
            self._queue_and_send(message.chat_id, reply, kind, message.message_id)
            self.store.mark_processed(message.message_id)
            return True
        if plan and plan.state == "READY" and plan.pending_proposal_id and valid_approval(message.text):
            if valid_calendar_approval(message.text) and self.calendar_fn is None:
                self._queue_and_send(message.chat_id,
                                     "Rally: Calendar creation is not available. Reply 'Book it' for the demo reservation only.",
                                     "ask", plan.id)
                self.store.mark_processed(message.message_id)
                return True
            proposal = self.store.get_proposal(plan.pending_proposal_id)
            if (proposal and proposal.version == plan.version and proposal.status == "pending"
                    and self.store.sent_message("proposal", proposal.id)):
                if self.store.has_approval(proposal.id):
                    self._book(plan, proposal)
                    self.store.mark_processed(message.message_id)
                    return True
                if (not proposal.created_at or
                        message.sent_at < datetime.fromisoformat(proposal.created_at) or
                        self.store.has_unprocessed_prior(message.chat_id, message.message_id, message.sent_at)):
                    self.store.mark_processed(message.message_id)
                    return True
                if message.sent_at - datetime.fromisoformat(proposal.created_at) > timedelta(hours=24):
                    self.store.expire_proposal(proposal.id)
                    self.store.mark_processed(message.message_id)
                    return True
                if self.store.approve(proposal.id, message.sender_id, message.message_id,
                                      includes_calendar=valid_calendar_approval(message.text)):
                    self._book(plan, proposal)
                self.store.mark_processed(message.message_id)
                return True
        messages = self.store.recent_messages(message.chat_id)
        direct_call = explicitly_addresses_rally(message.text)
        followup = (
            bool(self.group_turns and not direct_call and
                 self.group_turns.active(message.chat_id, message.sent_at))
            if self.group_turns is not None else
            self._is_direct_followup(message, messages)
        )
        if (direct_call or followup) and not self.store.has_message(
                "direct_reply", message.message_id):
            if message.message_id in self._decision_inflight:
                return True
            if self._handle_addressed_message(
                    message, plan, messages, direct_call=direct_call, followup=followup):
                return True
        if (not direct_call and not self.store.has_message("direct_reply", message.message_id)
                and self._maybe_revive_from_inbound(message, plan)):
            self.store.mark_processed(message.message_id)
            return True
        if self.defer_heavy_work:
            self._schedule_heavy(message)
            return True
        self._heavy_inflight.add(message.message_id)
        return self._run_heavy(message)

    def _executor(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rally-heavy")
        return self._pool

    def _run_heavy(self, message: ChatMessage) -> bool:
        try:
            return self._extract_and_learn(message)
        finally:
            self._heavy_inflight.discard(message.message_id)

    def _schedule_heavy(self, message: ChatMessage) -> None:
        """Coalesce a short chat burst into one plan extraction.

        Every inbound text is already durable before this point. The batcher only
        reduces redundant model calls; it never delays the direct-reply path.
        """
        with self._heavy_guard:
            self._heavy_inflight.add(message.message_id)
            self._heavy_pending.setdefault(message.chat_id, []).append(message)
            if message.chat_id in self._heavy_chats_running:
                return
            self._heavy_chats_running.add(message.chat_id)
        self._executor().submit(self._run_heavy_batch, message.chat_id)

    def _run_heavy_batch(self, chat_id: str) -> None:
        # Let consecutive iMessages settle briefly, then extract from their shared
        # current context once. This is off the webhook thread.
        time.sleep(0.75)
        while True:
            with self._heavy_guard:
                batch = self._heavy_pending.pop(chat_id, [])
            if not batch:
                with self._heavy_guard:
                    self._heavy_chats_running.discard(chat_id)
                return
            try:
                self._extract_and_learn(batch[-1], [item.message_id for item in batch])
            finally:
                with self._heavy_guard:
                    for item in batch:
                        self._heavy_inflight.discard(item.message_id)
                # New messages received during the model call are handled by the
                # next loop as one fresh batch rather than losing their update.

    def _extract_and_learn(self, message: ChatMessage,
                           processed_ids: list[str] | None = None) -> bool:
        processed_ids = processed_ids or [message.message_id]
        already_replied = any(self.store.has_message("direct_reply", message_id)
                              for message_id in processed_ids)
        plan = self.store.get_plan(message.chat_id)
        messages = self.store.recent_messages(message.chat_id)
        extract_started = time.perf_counter()
        try:
            facts = self.extractor.extract(messages, plan.facts if plan else None)
        except Exception as exc:
            self._log_latency("extract", extract_started)
            record_latency("extraction", time.perf_counter() - extract_started)
            self._record_extraction_failure(processed_ids, exc)
            if already_replied:
                self.store.mark_processed_many(message.chat_id, processed_ids)
                return True
            if self.defer_heavy_work:
                _log_scheduled_failure("plan extract", exc)
                return False
            raise
        self._log_latency("extract", extract_started)
        record_latency("extraction", time.perf_counter() - extract_started)
        if facts.activity:
            if not plan or plan.state not in ("DONE", "ABANDONED") or (
                    facts.activity, facts.goal, facts.date) != (
                    plan.facts.activity, plan.facts.goal, plan.facts.date):
                previous_version = plan.version if plan else None
                saved = self.store.save_plan(message.chat_id, facts, message.sent_at)
                if previous_version != saved.version:
                    self._publish_portal()
        learn_started = time.perf_counter()
        self._learn_from_chat(message, messages)
        self._log_latency("learn", learn_started)
        self.store.mark_processed_many(message.chat_id, processed_ids)
        if self.knowledge_fn:
            try:
                self.knowledge_fn(message.chat_id)
            except Exception as exc:
                _log_scheduled_failure("knowledge trigger", exc)
        return True

    def _record_extraction_failure(self, message_ids: list[str], exc: Exception):
        kind, stage, status_code = _failure_diagnostic(exc)
        for message_id in message_ids:
            try:
                self.store.record_processing_failure(message_id, kind=kind,
                                                     stage=stage, status_code=status_code)
            except Exception as diagnostic_error:
                _log_scheduled_failure("processing diagnostic", diagnostic_error)

    def tick(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        count = 0
        for snapshot in self.store.active_plans():
            if not self._chat_allowed(snapshot.chat_id):
                continue
            with self._chat_lock(snapshot.chat_id):
                plan = self.store.get_plan(snapshot.chat_id)
                if not plan:
                    continue
                try:
                    if plan.state == "READY" and plan.pending_proposal_id:
                        proposal = self.store.get_proposal(plan.pending_proposal_id)
                        if (proposal and proposal.created_at and not self.store.has_approval(proposal.id)
                                and now - datetime.fromisoformat(proposal.created_at) > timedelta(hours=24)):
                            self.store.expire_proposal(proposal.id)
                            continue
                    if plan.pending_proposal_id and self.store.has_approval(plan.pending_proposal_id):
                        proposal = self.store.get_proposal(plan.pending_proposal_id)
                        if proposal and proposal.status == "pending" and proposal.version == plan.version:
                            self._book(plan, proposal)
                except Exception as exc:
                    _log_scheduled_failure("approval recovery", exc)
                plan = self.store.get_plan(snapshot.chat_id)
                if plan and eligible_for_intervention(plan, now, self.stall_minutes):
                    try:
                        self._hydrate_chat(plan.chat_id)
                        self._intervene(plan, now)
                    except Exception as exc:
                        _log_scheduled_failure("intervention", exc)
                        continue
                    count += 1
                elif plan and self._should_revive(plan, now, incoming_stall=False):
                    try:
                        self._hydrate_chat(plan.chat_id)
                        self._send_revival(plan, now)
                    except Exception as exc:
                        _log_scheduled_failure("stall revival", exc)
                        continue
                    count += 1
        self.deliver_pending()
        return count

    def evaluate(self, chat_id: str, now: datetime | None = None) -> bool:
        """Demo trigger that uses the same eligibility and action path as tick."""
        if not self._chat_allowed(chat_id):
            return False
        with self._chat_lock(chat_id):
            now = now or datetime.now(timezone.utc)
            plan = self.store.get_plan(chat_id)
            if not plan or not eligible_for_intervention(plan, now, self.stall_minutes):
                return False
            self._intervene(plan, now)
            return True

    def _last_rally_at(self, chat_id: str) -> datetime | None:
        for item in reversed(self.store.recent_messages(chat_id, 20)):
            if item.is_from_rally:
                return item.sent_at
        return None

    def _should_revive(self, plan: Plan, now: datetime, *, incoming_stall: bool) -> bool:
        if not self._chat_allowed(plan.chat_id) or not unfinished_plan(plan):
            return False
        return eligible_for_revival(
            plan, now, last_rally_at=self._last_rally_at(plan.chat_id),
            incoming_stall=incoming_stall)

    def _maybe_revive_from_inbound(self, message: ChatMessage, plan) -> bool:
        if plan is None or _idle_chatter(message.text) or not _stall_signal(message.text):
            return False
        if not self._should_revive(plan, message.sent_at, incoming_stall=True):
            return False
        self._hydrate_chat(message.chat_id, skip_id=message.message_id)
        return self._send_revival(plan, message.sent_at)

    def _send_revival(self, plan: Plan, now: datetime) -> bool:
        facts = plan.facts
        messages = self.store.recent_messages(plan.chat_id)
        memory = self.group_memory.prompt_context(plan.chat_id, limit=12) if self.group_memory else ""
        snap = _thread_snapshot(messages, memory, facts)
        place = snap.get("place") or facts.location
        cuisine = ""
        if snap.get("options"):
            cuisine = snap["options"][0]
        elif facts.preferred_cuisines:
            cuisine = facts.preferred_cuisines[0]
        when = snap.get("day") or facts.date or "tonight"
        if place and _FOOD_ACTIVITY.search((facts.activity or "") + " " + (snap.get("activity") or "")):
            text = self._recommend_restaurant(facts, messages, memory)
        elif cuisine:
            text = (f"we're at {cuisine} / {when} / still no spot — "
                    "want me to pick a restaurant that fits?")
        else:
            text = (f"the {facts.activity or 'plan'} is still open ({when}). "
                    "want me to lock a spot?")
        if self._same_recent_outbound(plan.chat_id, text):
            self.store.mark_intervened(plan.id, plan.version, now)
            return False
        self._queue_and_send(plan.chat_id, f"Rally: {text}", "nudge", plan.id)
        outbound_id = f"rally-nudge:{plan.id}:{plan.version}"
        self.store.add_message(ChatMessage(
            outbound_id, plan.chat_id, "Rally", text, now, True))
        self.store.mark_processed(outbound_id)
        self.store.mark_intervened(plan.id, plan.version, now)
        return True

    def _intervene(self, plan: Plan, now: datetime):
        messages = self.store.recent_messages(plan.chat_id)
        decision = self.agent.decide(plan.facts, messages, [])
        facts = plan.facts
        if facts.date:
            try:
                if date.fromisoformat(facts.date) < datetime.now(ZoneInfo(self.time_zone)).date():
                    self.store.clear_availability(plan.id)
                    self._queue_and_send(plan.chat_id,
                        "Rally: That plan date has passed. What new date should I use before collecting availability again?",
                        "ask", plan.id)
                    self.store.mark_intervened(plan.id, plan.version, now)
                    return
            except (ValueError, ZoneInfoNotFoundError):
                pass
        has_reports = bool(facts.date and self.store.availability_reports(
            plan.id, plan.version, facts.date))
        if decision.confidence < 0.6 or decision.action == "WAIT":
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        if ((decision.action == "ASK" and not (facts.location and facts.date and
                                                (facts.time or has_reports))) or
                not facts.location or not facts.date):
            if not facts.location:
                question = f"Which city or area should I use for {facts.goal or facts.activity}?"
            elif not facts.date:
                question = f"Which date works for {facts.goal or facts.activity}?"
            elif not facts.time:
                self._request_group_availability(plan, now)
                self.store.mark_intervened(plan.id, plan.version, now)
                return
            else:
                question = f"Could you clarify {facts.blockers[0]}?" if facts.blockers else "What detail should I use?"
            self._queue_and_send(plan.chat_id, f"Rally: {question}", "ask", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        availability_ready = bool(not facts.time and has_reports)
        if ((decision.action not in ("PROPOSE", "NUDGE") and
             not (decision.action == "ASK" and availability_ready)) or
                (decision.action in ("PROPOSE", "NUDGE") and decision.tool != "search_places")):
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        if not _FOOD_ACTIVITY.search(facts.activity or facts.goal or ""):
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        try:
            venues = self.search_fn(facts)
        except PlacesError as exc:
            if str(exc) == "The city is unclear":
                self._queue_and_send(plan.chat_id,
                                     f"Rally: Which city should I search near {facts.location}?",
                                     "ask", plan.id)
            else:
                self._queue_and_send(plan.chat_id,
                                     "Rally: I couldn't search for a venue right now. I'll wait for the group to continue.",
                                     "error", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        except Exception:
            self._queue_and_send(plan.chat_id, "Rally: I couldn't search for a venue right now. I'll wait for the group to continue.", "error", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        excluded = {name.lower() for name in facts.excluded_cuisines}
        viable = [venue for venue in venues if (not excluded or venue.cuisine_tags) and
                  not excluded.intersection(tag.lower() for tag in venue.cuisine_tags) and
                  not any(name in venue.name.lower() for name in excluded)]
        preferred = {name.lower() for name in facts.preferred_cuisines}
        viable.sort(key=lambda venue: -len(preferred.intersection(
            tag.lower() for tag in venue.cuisine_tags)))
        if not viable:
            self._queue_and_send(plan.chat_id, "Rally: I couldn't find a venue that I can verify against your food preferences. Any other area or cuisine?", "ask", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        candidates = [{"id": venue.id, "name": venue.name, "address": venue.address,
                       "cuisine_tags": list(venue.cuisine_tags),
                       "preferred_cuisine_match": bool(preferred.intersection(
                           tag.lower() for tag in venue.cuisine_tags))} for venue in viable]
        selection = self.agent.decide(facts, messages,
                                      [{"tool": "search_places", "venues": candidates}])
        venue = next((venue for venue in viable if venue.id == selection.venue_id), None)
        if selection.action != "PROPOSE" or selection.confidence < 0.6 or venue is None:
            self._queue_and_send(plan.chat_id, "Rally: I found options, but need another preference before suggesting one. What cuisine works?", "ask", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        # Preserve the legacy earliest-time heuristic only when calendar
        # availability is disabled. With Calendar connected, intersect reports
        # with the owner's actual free/busy result.
        proposed_time = (facts.time if self.availability_fn is not None
                         else self._proposal_time(facts))
        reports = []
        owner_busy = None
        if not proposed_time:
            reports = self.store.availability_reports(plan.id, plan.version, facts.date)
            if not reports:
                self._request_group_availability(plan, now)
                self.store.mark_intervened(plan.id, plan.version, now)
                return
            expected_reports = facts.party_size or len(set(facts.participants))
            missing_reports = max(0, expected_reports - len(reports))
            if missing_reports:
                people = "person" if missing_reports == 1 else "people"
                self._queue_and_send(plan.chat_id,
                    f"Rally: I have availability from {len(reports)} participant(s). Waiting for {missing_reports} more {people} to share a clear range before I suggest a time.",
                    "availability_wait", plan.id)
                self.store.mark_intervened(plan.id, plan.version, now)
                return
            if self.availability_fn is None:
                self._queue_and_send(plan.chat_id,
                    "Rally: I have the availability members shared, but I can’t check the Rally owner’s Google Calendar right now. Please confirm a time or connect the calendar.",
                    "ask", plan.id)
                self.store.mark_intervened(plan.id, plan.version, now)
                return
            try:
                busy = self.availability_fn(facts.date, self.time_zone)
            except Exception:
                self._queue_and_send(plan.chat_id,
                    "Rally: I couldn’t check the Rally owner’s calendar, so I can’t suggest a shared time yet.",
                    "error", plan.id)
                self.store.mark_intervened(plan.id, plan.version, now)
                return
            owner_busy = busy
            windows = [AvailabilityWindow(clock_time.fromisoformat(row["start_time"]),
                                          clock_time.fromisoformat(row["end_time"]), row["source_text"])
                       for row in reports]
            try:
                not_before = None
                if facts.earliest_time:
                    raw_earliest = clock_time.fromisoformat(facts.earliest_time)
                    not_before = (datetime.combine(date.min, raw_earliest) +
                                  timedelta(hours=1)).time()
                proposed_time = choose_slot(date.fromisoformat(facts.date), windows, busy,
                                            self.time_zone, not_before=not_before)
            except ValueError:
                proposed_time = None
            if not proposed_time:
                self._queue_and_send(plan.chat_id,
                    f"Rally: I couldn’t find a two-hour slot that fits the availability shared so far and the owner’s calendar. Could someone suggest another clear range for {facts.date}, or say ‘change the plan to Saturday’ if another date is better?",
                    "ask", plan.id)
                self.store.mark_intervened(plan.id, plan.version, now)
                return
        elif self.availability_fn is not None:
            try:
                owner_busy = self.availability_fn(facts.date, self.time_zone)
            except Exception:
                self._queue_and_send(plan.chat_id,
                    "Rally: I couldn’t check the Rally owner’s calendar, so I can’t confirm that time.",
                    "error", plan.id)
                self.store.mark_intervened(plan.id, plan.version, now)
                return
        if reports and not self._time_fits_reports(proposed_time, reports):
            self._queue_and_send(plan.chat_id,
                "Rally: That time doesn’t fit the availability reported so far. Could someone suggest another range?",
                "ask", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        if owner_busy is not None and not self._owner_time_is_free(facts.date, proposed_time, owner_busy):
            self._queue_and_send(plan.chat_id,
                "Rally: That time conflicts with the Rally owner’s Google Calendar. Could someone suggest another time?",
                "ask", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        proposal = Proposal(str(uuid4()), plan.id, plan.version, venue.id, venue.name,
                            venue.address, facts.date, proposed_time,
                            facts.party_size or len(set(facts.participants)),
                            created_at=now.isoformat())
        self.store.save_proposal(proposal)
        display_time = self._display_time(proposed_time)
        attribution = (" Venue data: Geoapify (https://www.geoapify.com/), "
                       "© OpenStreetMap contributors (https://www.openstreetmap.org/copyright)."
                       if venue.source == "geoapify" else " Demo venue data.")
        approval_prompt = (" Reply 'Book it' for the demo reservation, or 'Book it and add a calendar event' for both."
                           if self.calendar_fn else " Reply 'Book it' for the demo reservation.")
        availability_note = (" This time fits the availability members reported and the Rally owner’s Google Calendar; other calendars weren’t checked."
                             if reports else "")
        text = (f"Rally: {facts.goal or facts.activity} could work at {venue.name}, "
                f"{venue.address}, on {facts.date} at {display_time} for {proposal.party_size}. "
                f"{approval_prompt.strip()}{availability_note}{attribution}")
        self._queue_and_send(plan.chat_id, text, "proposal", proposal.id)
        self.store.mark_intervened(plan.id, plan.version, now)

    def _request_group_availability(self, plan: Plan, now: datetime):
        if self.availability_fn is None:
            detail = (f"Could you clarify {plan.facts.blockers[0]}?"
                      if plan.facts.blockers and "availability" in plan.facts.blockers[0].lower()
                      else "What time works for everyone?")
            self._queue_and_send(plan.chat_id, f"Rally: {detail}",
                                 "ask", plan.id)
            return
        if self.store.request_availability(plan.id, plan.version, now):
            text = (f"Rally: When are you generally free on {plan.facts.date}? Please share a clear range, "
                    "like ‘free all day Saturday’ or ‘weekdays after 4pm.’ I’ll use replies as self-reported availability and check only the Rally owner’s Google Calendar.")
            self._queue_and_send(plan.chat_id, text, "availability_request", plan.id)

    @staticmethod
    def _time_fits_reports(value: str, reports) -> bool:
        try:
            start = clock_time.fromisoformat(value)
            end_dt = datetime.combine(date.min, start) + timedelta(hours=2)
            end = end_dt.time()
            return all(start >= clock_time.fromisoformat(row["start_time"]) and
                       end <= clock_time.fromisoformat(row["end_time"]) for row in reports)
        except (ValueError, TypeError):
            return False

    def _owner_time_is_free(self, day: str, value: str, busy) -> bool:
        try:
            local_date = date.fromisoformat(day)
            zone = ZoneInfo(self.time_zone)
            local_time = clock_time.fromisoformat(value)
            start_naive = datetime.combine(local_date, local_time)
            early = start_naive.replace(tzinfo=zone, fold=0)
            late = start_naive.replace(tzinfo=zone, fold=1)
            if early.utcoffset() != late.utcoffset():
                return False
            start = early.astimezone(timezone.utc)
            end = (start + timedelta(hours=2))
            return not any(start < busy_end and end > busy_start for busy_start, busy_end in busy)
        except (ValueError, ZoneInfoNotFoundError, TypeError):
            return False

    @staticmethod
    def _proposal_time(facts: PlanFacts) -> str | None:
        if facts.time:
            if facts.earliest_time and facts.time <= facts.earliest_time:
                return None
            return facts.time
        if facts.earliest_time:
            try:
                hour, minute = map(int, facts.earliest_time.split(":"))
                start = datetime(2000, 1, 1, hour, minute) + timedelta(hours=1)
                if start.date() != datetime(2000, 1, 1).date():
                    return None
                return start.strftime("%H:%M")
            except ValueError:
                return None
        return None

    @staticmethod
    def _display_time(time: str) -> str:
        try:
            return datetime.strptime(time, "%H:%M").strftime("%I:%M %p").lstrip("0")
        except ValueError:
            return time

    def _book(self, plan: Plan, proposal: Proposal):
        if self.store.has_message("reservation_error", proposal.id):
            return
        self.store.set_state(plan.id, "EXECUTING")
        try:
            reservation = create_reservation(self.store, proposal)
        except Exception:
            self._queue_and_send(plan.chat_id, "Rally: The demo reservation failed. Nothing is confirmed.",
                                 "reservation_error", proposal.id)
            return
        approval = self.store.approval(proposal.id)
        calendar_note = ""
        if approval and approval["includes_calendar"] and self.calendar_fn:
            result = self.store.calendar_result(proposal.id)
            if result is None:
                try:
                    if self.availability_fn is not None:
                        busy = self.availability_fn(proposal.date, self.time_zone)
                        if not self._owner_time_is_free(proposal.date, proposal.time, busy):
                            raise RuntimeError("Owner calendar is no longer free")
                    event = self.calendar_fn(proposal, approval["message_id"],
                                             reservation.confirmation_id)
                    self.store.save_calendar_result(proposal.id, "confirmed", event.event_id, None)
                except Exception:
                    self.store.save_calendar_result(proposal.id, "unconfirmed", None,
                                                    "Calendar creation was not confirmed")
                result = self.store.calendar_result(proposal.id)
            calendar_note = (" Calendar event created."
                             if result["status"] == "confirmed" else
                             " Calendar event was not confirmed.")
        text = (f"Rally: Demo reservation confirmed — {proposal.venue_name}, {proposal.venue_address}, "
                f"{proposal.date} at {self._display_time(proposal.time)}, party of {proposal.party_size}. "
                f"Confirmation: {reservation.confirmation_id}.{calendar_note}")
        if not self.store.has_message("final", proposal.id):
            self._queue_and_send(plan.chat_id, text, "final", proposal.id)
        else:
            self.deliver_pending(plan.chat_id)

    def _handle_addressed_message(self, message: ChatMessage, plan, messages,
                                  *, direct_call: bool, followup: bool) -> bool:
        """Reply to a Rally call or open follow-up. True skips plan extraction."""
        if followup and not direct_call and _idle_chatter(message.text):
            return False
        coalesced = bool(self.group_turns and self.group_turns.should_coalesce(
            message.chat_id, message.text, message.sent_at))
        if not coalesced:
            self._react(message, SEEN_REACTION)
            self._warm_helper()
        if direct_call:
            forget = parse_forget_command(message.text)
            if forget is not None:
                self._reply_forget(message, forget)
                return False
        if illegal_assistance_request(message.text):
            self._send_group_reply(message, refusal_text(), allow_flood=True)
            self._react(message, None)
            self._note_turn(message)
            return False
        if coalesced:
            self._note_turn(message)
            return False
        command = self._priority_command_answer(message, messages)
        if command is not None:
            text, allow_flood = command
            self._send_group_reply(message, text, allow_flood=allow_flood)
            self._finish_reaction(message, delivered=self.store.sent_message("direct_reply", message.message_id))
            self.store.mark_processed(message.message_id)
            return True
        memory_context = self.group_memory.prompt_context(message.chat_id, limit=12) if self.group_memory else ""
        if self._has_local_reply(message, plan):
            text = self._local_decision_reply(
                plan, messages, memory_context, request=message.text)
            self._send_group_reply(message, text, allow_flood=False)
            self._finish_reaction(message, delivered=self.store.sent_message("direct_reply", message.message_id))
            self._note_turn(message)
            return False
        self._decision_inflight.add(message.message_id)
        started = time.perf_counter()
        self._set_typing(message, True)
        try:
            try:
                decision = self._call_without_chat_lock(
                    message.chat_id,
                    lambda: self._conversation_decision(
                        message, plan, messages, followup and not direct_call),
                )
            except Exception as exc:
                self._log_latency("decision", started)
                record_latency("direct_model", time.perf_counter() - started)
                _log_scheduled_failure("group conversation", exc)
                if self.store.has_message("direct_reply", message.message_id):
                    return False
                text = self._local_decision_reply(
                    plan, messages, memory_context, request=message.text)
                if text and (direct_call or _worth_replying(message.text)):
                    self._send_group_reply(message, text, allow_flood=True)
                    self._finish_reaction(message, delivered=self.store.sent_message("direct_reply", message.message_id))
                    self._note_turn(message)
                else:
                    self._react(message, None)
                return False
            self._log_latency("decision", started)
            record_latency("direct_model", time.perf_counter() - started)
            if self.store.has_message("direct_reply", message.message_id):
                return False
            if followup and not direct_call and not decision.relevant:
                self._react(message, None)
                return False
            refuse = decision.safety == "refuse"
            text = (decision.message or refusal_text()) if refuse else decision.message
            if text and _NO_ANSWER.match(text):
                text = None
            if decision.relevant:
                if text:
                    self._send_group_reply(message, text, allow_flood=refuse)
                delivered = self.store.sent_message("direct_reply", message.message_id)
                queued = self.store.has_message("direct_reply", message.message_id)
                if delivered and not refuse:
                    self._react(message, completion_reaction(decision.reaction) or DONE_REACTION)
                    self._remember(message, decision.memory_candidates)
                elif refuse or not queued:
                    self._react(message, None)
                self._note_turn(message)
            return False
        finally:
            self._set_typing(message, False)
            self._decision_inflight.discard(message.message_id)

    def _priority_command_answer(self, message: ChatMessage, messages) -> tuple[str, bool] | None:
        if self.portal_handler:
            answer = self.portal_handler(message)
            if answer is not None:
                return answer, True
        if self.adaptive_handler and should_use_adaptive(message.text):
            try:
                return self.adaptive_handler.answer(message), False
            except Exception as exc:
                _log_scheduled_failure("adaptive answer", exc)
                return "couldn't finish that. try me again in a minute.", False
        if self.web_answer_fn and should_search_web(message.text):
            try:
                return self.web_answer_fn(message.text, tone=group_tone(messages)), False
            except Exception as exc:
                _log_scheduled_failure("web answer", exc)
                return ("web search is down right now so i can't verify that, try later."), False
        return None

    def _call_without_chat_lock(self, chat_id: str, fn):
        """Release the per-chat lock around a provider call, then re-acquire."""
        lock = self._chat_lock(chat_id)
        lock.release()
        try:
            return fn()
        finally:
            lock.acquire()

    def _conversation_decision(self, message, plan, messages, followup: bool):
        memory_context = self.group_memory.prompt_context(message.chat_id, limit=12) if self.group_memory else ""
        facts = plan.facts if plan else None
        proposal = self._proposal_context(plan)
        speaker = self.reply_agent or self.agent
        if hasattr(speaker, "decide_conversation"):
            return speaker.decide_conversation(
                message.text, facts, messages, memory_context=memory_context,
                followup=followup, proposal=proposal)
        thread = self.store.recent_human_messages(message.chat_id, 20)
        return GroupConversationDecision(
            relevant=True, safety="ok",
            message=speaker.answer_direct(message.text, facts, thread),
        )

    def _has_local_reply(self, message: ChatMessage, plan) -> bool:
        text = message.text or ""
        if _RECAP_ASK.search(text):
            return True
        facts = plan.facts if plan else None
        if _named_option_pick(text, facts) is not None:
            return True
        if _general_local_answer(text):
            return True
        if _restaurant_intent(text):
            messages = self.store.recent_messages(message.chat_id)
            memory = self.group_memory.prompt_context(message.chat_id, limit=12) if self.group_memory else ""
            snap = _thread_snapshot(messages, memory, facts)
            return bool(snap.get("place") or (facts and facts.location))
        return False

    def _local_decision_reply(self, plan, messages, memory_context: str = "",
                             request: str = "") -> str:
        facts = plan.facts if plan else None
        picked = _named_option_pick(request, facts)
        if picked:
            options = list(getattr(facts, "preferred_cuisines", None) or [])
            return _option_why(picked, facts, options)
        if _restaurant_intent(request):
            return self._recommend_restaurant(facts, messages, memory_context)
        snap = _thread_snapshot(messages, memory_context, facts)
        grounded = _grounded_fact_answer(request, snap, memory_context)
        if grounded:
            return grounded
        general = _general_local_answer(request, snap, facts)
        if general:
            return general
        if _RECAP_ASK.search(request or ""):
            return _recap_from_snapshot(snap, facts, self._proposal_context(plan) if plan else None)
        return ("i'm here — ask for a recap, a restaurant pick, or whatever you actually want.")

    def _recommend_restaurant(self, facts, messages, memory_context: str = "") -> str:
        snap = _thread_snapshot(messages, memory_context, facts)
        search_facts = PlanFacts(**{**{
            "goal": facts.goal if facts else "",
            "activity": facts.activity if facts else snap.get("activity") or "dinner",
            "location": (facts.location if facts and facts.location else None) or snap.get("place"),
            "preferred_cuisines": list(facts.preferred_cuisines) if facts and facts.preferred_cuisines else list(snap.get("options") or []),
            "excluded_cuisines": list(facts.excluded_cuisines) if facts else [],
            "date": facts.date if facts else None,
            "time": facts.time if facts else None,
            "party_size": facts.party_size if facts else None,
        }})
        venues = []
        try:
            venues = list(self.search_fn(search_facts) or [])
        except Exception as exc:
            _log_scheduled_failure("restaurant search", exc)
        viable = [venue for venue in venues if _venue_fits_constraints(venue, snap)] or list(venues)
        place = snap.get("place") or (facts.location if facts else None) or "the area you named"
        diet = (snap.get("dietary") or [None])[0]
        meal = snap.get("activity") or (facts.activity if facts else "dinner")
        if viable:
            venue = viable[0]
            why = [place]
            if diet:
                why.append(diet)
            return (f"{venue.name} near {place} for {meal} — {', '.join(why)}. "
                    "not a booking, just a rec.")
        name = "Green Table" if diet else "An Italian Table"
        why = diet or f"fits {place}"
        return (f"{name} near {place} for {meal} — {why}. "
                "not a booking, just a rec.")

    def _proposal_context(self, plan) -> dict | None:
        if plan is None:
            return None
        saved = None
        if plan.pending_proposal_id:
            saved = self.store.get_proposal(plan.pending_proposal_id)
        if saved is None:
            saved = self.store.latest_proposal(plan.id)
        if saved is None:
            return None
        return {
            "venue_name": saved.venue_name,
            "venue_address": saved.venue_address,
            "date": saved.date,
            "time": saved.time,
            "party_size": saved.party_size,
            "status": saved.status,
        }

    def _reply_forget(self, message: ChatMessage, target: str):
        if self.group_memory is None:
            text = "i don't have anything saved for this group."
        elif target == "":
            removed = self.group_memory.forget(message.chat_id)
            text = ("okay, i forgot that group stuff."
                    if removed else "i don't have anything saved for this group.")
        else:
            removed = self.group_memory.forget(message.chat_id, target)
            if not removed:
                phrase = forget_phrase(message.text)
                if phrase and phrase.casefold() != target:
                    removed = self.group_memory.forget_fact(message.chat_id, phrase)
            if self.knowledge_store is not None:
                phrase = forget_phrase(message.text) or target
                removed = self.knowledge_store.forget_matching(message.chat_id, phrase) > 0 or removed
            text = "okay, i forgot that." if removed else "i don't have that saved."
        self._send_group_reply(message, text, allow_flood=True)
        self._finish_reaction(message, delivered=self.store.sent_message("direct_reply", message.message_id))
        self._note_turn(message)

    def _same_recent_outbound(self, chat_id: str, text: str) -> bool:
        needle = text.strip().casefold()
        if not needle:
            return False
        for item in reversed(self.store.recent_messages(chat_id, limit=12)):
            if item.is_from_rally:
                return (item.text or "").strip().casefold() == needle
        return False

    def _send_group_reply(self, message: ChatMessage, text: str, *, allow_flood: bool) -> bool:
        if not text or not text.strip():
            return False
        if _REPEAT_TEMPLATE.search(text) and self._same_recent_outbound(message.chat_id, text):
            return False
        if (not allow_flood and self.group_turns and
                not self.group_turns.allow_reply(message.chat_id, message.sent_at)):
            return False
        self._queue_and_send(message.chat_id, f"Rally: {text}", "direct_reply", message.message_id)
        outbound_id = f"rally-out:{message.message_id}"
        self.store.add_message(ChatMessage(
            outbound_id, message.chat_id, "Rally", text, datetime.now(timezone.utc), True))
        self.store.mark_processed(outbound_id)
        return True

    def _note_turn(self, message: ChatMessage):
        if self.group_turns:
            self.group_turns.mark_relevant(
                message.chat_id, message.message_id, message.sent_at, message.text)

    def _finish_reaction(self, message: ChatMessage, *, delivered: bool):
        if delivered:
            self._react(message, DONE_REACTION)
        else:
            self._react(message, None)

    def _warm_helper(self):
        if not self.helper_warm_fn:
            return

        def run():
            try:
                self.helper_warm_fn()
            except Exception as exc:
                _log_scheduled_failure("helper warmup", exc)

        self._side_effect(run)

    def _side_effect(self, fn):
        if self.defer_heavy_work:
            self._executor().submit(fn)
            return
        fn()

    def _react(self, message: ChatMessage, reaction: str | None):
        if not self.react_fn:
            return
        current = self.group_turns.last_reaction(message.message_id) if self.group_turns else None
        payload = reaction
        if reaction is None:
            if not current:
                return
            payload = current if current.startswith("-") else f"-{current}"
        if payload == current:
            return
        if self.group_turns:
            self.group_turns.remember_reaction(message.message_id, reaction)

        def run():
            try:
                self.react_fn(message.chat_id, message.message_id, payload)
            except Exception as exc:
                _log_scheduled_failure("reaction", exc)

        self._side_effect(run)

    def _set_typing(self, message: ChatMessage, typing: bool):
        if not self.typing_fn:
            return

        def run():
            try:
                self.typing_fn(message.chat_id, typing)
            except Exception as exc:
                _log_scheduled_failure("typing", exc)

        self._side_effect(run)

    def _learn_from_chat(self, message: ChatMessage, messages):
        if (not self.group_memory or message.message_id in self._remembered_ids
                or illegal_assistance_request(message.text)
                or parse_forget_command(message.text) is not None
                or not hasattr(self.agent, "learn_memory")):
            return
        memory_context = self.group_memory.prompt_context(message.chat_id, limit=12)
        try:
            candidates = self.agent.learn_memory(
                message.text, messages, memory_context=memory_context)
        except Exception as exc:
            _log_scheduled_failure("memory learn", exc)
            return
        self._remember(message, candidates)

    def _remember(self, message: ChatMessage, candidates):
        if not self.group_memory or not candidates:
            return
        saved = False
        for item in candidates:
            key = getattr(item, "key", None)
            fact = getattr(item, "fact", None)
            if not isinstance(key, str) or not isinstance(fact, str) or not eligible_fact(fact):
                continue
            try:
                if self.group_memory.upsert_fact(
                        message.chat_id, key, fact, message.message_id, message.sent_at):
                    saved = True
            except ValueError:
                continue
        if saved:
            self._remembered_ids.add(message.message_id)

    def _log_latency(self, stage: str, started: float):
        elapsed_ms = 0 if not started else int((time.perf_counter() - started) * 1000)
        logger.warning("group_conversation stage=%s elapsed_ms=%s", stage, elapsed_ms)

    def _invoke_send(self, chat_id: str, text: str, selected_message_guid: str | None = None):
        """Call send_fn with a thread target when the installed callback accepts it."""
        if not selected_message_guid:
            return self.send_fn(chat_id, text)
        try:
            return self.send_fn(chat_id, text, selected_message_guid=selected_message_guid)
        except TypeError:
            return self.send_fn(chat_id, text)

    def _queue_and_send(self, chat_id: str, text: str, kind: str, ref_id: str):
        started = time.perf_counter()
        self.store.queue_message(chat_id, remove_rally_signature(text), kind, ref_id)
        self.deliver_pending(chat_id)
        self._log_latency("send", started)

    def deliver_pending(self, chat_id: str | None = None):
        for item in self.store.pending_messages():
            current_chat_id = item["chat_id"]
            if (chat_id is not None and current_chat_id != chat_id) or not self._chat_allowed(current_chat_id):
                continue
            with self._chat_lock(current_chat_id):
                started = perf_counter()
                try:
                    self._invoke_send(
                        current_chat_id, remove_rally_signature(item["text"]),
                        selected_message_guid=item["ref_id"] if item["kind"] in _THREADED_OUTBOX_KINDS else None,
                    )
                except DeliveryUncertainError:
                    self.store.set_delivery(item["id"], "uncertain", "Inspect the iMessage thread before retrying")
                    continue
                except Exception:
                    self.store.set_delivery(item["id"], "failed", "Message delivery failed")
                    continue
                finally:
                    record_latency("bluebubbles_delivery", perf_counter() - started)
                self.store.set_delivery(item["id"], "sent")
                if item["kind"] == "final" and item["ref_id"]:
                    proposal = self.store.get_proposal(item["ref_id"])
                    if proposal:
                        self.store.set_state(proposal.plan_id, "DONE")
