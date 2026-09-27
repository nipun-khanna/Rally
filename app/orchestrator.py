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
from app.policy import (eligible_for_intervention, explicitly_addresses_rally,
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
    r"\b(recap|what'?s the plan|next step|what people said|what did .+ say)\b",
    re.I,
)
_PICK_ASK = re.compile(r"\b(pick|lock|choose|decide)\b", re.I)


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


def _savage_option_why(picked: str, facts, options) -> str:
    losers = [item for item in options if item.casefold() != picked.casefold()]
    loser = losers[0] if losers else "the other option"
    place = facts.location if facts and facts.location else "this crew"
    return (f"{picked}. {place} already named the lanes — {loser} is the timid-ass hedge, "
            f"{picked} slaps harder. lock it and stop splitting the damn vote.")


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
                 defer_heavy_work: bool = False, history_fn=None):
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
        self._thread_hydrated: set[str] = set()
        self._chat_locks_guard = Lock()
        self._chat_locks = {}
        self._heavy_inflight: set[str] = set()
        self._decision_inflight: set[str] = set()
        self._remembered_ids: set[str] = set()
        self._pool: ThreadPoolExecutor | None = None

    def _chat_lock(self, chat_id: str) -> RLock:
        with self._chat_locks_guard:
            lock = self._chat_locks.get(chat_id)
            if lock is None:
                lock = RLock()
                self._chat_locks[chat_id] = lock
            return lock

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
        """Load BlueBubbles messages from before Rally was invoked into this chat's store."""
        if not self.history_fn or message.chat_id in self._thread_hydrated:
            return
        try:
            prior = self.history_fn(message.chat_id, 50)
        except Exception as exc:
            _log_scheduled_failure("thread hydrate", exc)
            self._thread_hydrated.add(message.chat_id)
            return
        self._thread_hydrated.add(message.chat_id)
        if not prior:
            return
        for item in prior:
            if (not isinstance(item, ChatMessage) or item.chat_id != message.chat_id
                    or item.message_id == message.message_id):
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
        self._heavy_inflight.add(message.message_id)
        if self.defer_heavy_work:
            self._executor().submit(self._run_heavy, message)
            return True
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

    def _extract_and_learn(self, message: ChatMessage) -> bool:
        already_replied = self.store.has_message("direct_reply", message.message_id)
        plan = self.store.get_plan(message.chat_id)
        messages = self.store.recent_messages(message.chat_id)
        extract_started = time.perf_counter()
        try:
            facts = self.extractor.extract(messages, plan.facts if plan else None)
        except Exception as exc:
            self._log_latency("extract", extract_started)
            record_latency("extraction", time.perf_counter() - extract_started)
            self._record_extraction_failure([message.message_id], exc)
            if already_replied:
                self.store.mark_processed(message.message_id)
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
                self.store.save_plan(message.chat_id, facts, message.sent_at)
        learn_started = time.perf_counter()
        self._learn_from_chat(message, messages)
        self._log_latency("learn", learn_started)
        self.store.mark_processed(message.message_id)
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
                        self._intervene(plan, now)
                    except Exception as exc:
                        _log_scheduled_failure("intervention", exc)
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
        coalesced = bool(self.group_turns and self.group_turns.should_coalesce(
            message.chat_id, message.text, message.sent_at))
        if not coalesced:
            self._react(message, SEEN_REACTION)
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
        if direct_call and self._has_local_reply(message, plan):
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
                if direct_call:
                    text = self._local_decision_reply(
                        plan, messages, memory_context, request=message.text)
                    self._send_group_reply(message, text, allow_flood=True)
                    self._finish_reaction(message, delivered=self.store.sent_message("direct_reply", message.message_id))
                elif self.group_turns:
                    self.group_turns.close(message.chat_id)
                    self._react(message, None)
                return False
            self._log_latency("decision", started)
            record_latency("direct_model", time.perf_counter() - started)
            if self.store.has_message("direct_reply", message.message_id):
                return False
            if followup and not direct_call and not decision.relevant:
                if self.group_turns:
                    self.group_turns.close(message.chat_id)
                self._react(message, None)
                return False
            refuse = decision.safety == "refuse"
            text = (decision.message or refusal_text()) if refuse else decision.message
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
                return "couldn't finish that shit. try me again in a minute.", False
        if self.web_answer_fn and should_search_web(message.text):
            try:
                return self.web_answer_fn(message.text, tone=group_tone(messages)), False
            except Exception as exc:
                _log_scheduled_failure("web answer", exc)
                return ("web search is dead right now so i can't verify shit. try later."), False
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
        if _RECAP_ASK.search(message.text or ""):
            return True
        facts = plan.facts if plan else None
        return _named_option_pick(message.text or "", facts) is not None

    def _local_decision_reply(self, plan, messages, memory_context: str = "",
                             request: str = "") -> str:
        facts = plan.facts if plan else None
        picked = _named_option_pick(request, facts)
        if picked:
            options = list(getattr(facts, "preferred_cuisines", None) or [])
            return _savage_option_why(picked, facts, options)
        parts = []
        if facts and facts.activity:
            parts.append(facts.activity)
        if facts and facts.date:
            parts.append(facts.date)
        if facts and facts.time:
            parts.append(f"at {_casual_clock(facts.time)}")
        if facts and facts.party_size:
            parts.append(f"for {facts.party_size}")
        if facts and facts.location:
            parts.append(f"near {facts.location}")
        if facts and facts.preferred_cuisines:
            parts.append(" or ".join(facts.preferred_cuisines))
        if facts and facts.blockers:
            parts.append(f"({facts.blockers[0]})")
        priors = [m.text.strip() for m in messages
                  if not m.is_from_rally and m.text.strip()
                  and not explicitly_addresses_rally(m.text)]
        if not parts:
            for line in (memory_context or "").splitlines():
                fact = line.lstrip("- ").strip()
                if fact:
                    parts.append(fact)
                if len(parts) >= 2:
                    break
        if not parts and priors:
            parts.extend(priors[-6:])
        elif priors:
            gist = "; ".join(priors[-4:])
            if gist and gist.casefold() not in " ".join(parts).casefold():
                parts.append(gist)
        if not parts:
            return ("nothing's locked, you're just vibing in the damn void. "
                    "spit the one call — time, place, or who — and i'll ride with it.")
        if facts and facts.location and not facts.time:
            nxt = "lock a time"
        elif facts and facts.time and not facts.location:
            nxt = "pick a damn place"
        else:
            nxt = "pick one walking-distance spot"
        return (f"locked-in chaos: {', '.join(parts)}. y'all are stalling like cowards — "
                f"{nxt} or i'm calling this shit mid in the thread. "
                "i still won't fake a damn restaurant.")

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
            text = "i don't have shit saved for this group."
        elif target == "":
            removed = self.group_memory.forget(message.chat_id)
            text = ("fine, i forgot that group crap."
                    if removed else "i don't have shit saved for this group.")
        else:
            removed = self.group_memory.forget(message.chat_id, target)
            if not removed:
                phrase = forget_phrase(message.text)
                if phrase and phrase.casefold() != target:
                    removed = self.group_memory.forget_fact(message.chat_id, phrase)
            text = "okay, i forgot that." if removed else "i don't have that saved."
        self._send_group_reply(message, text, allow_flood=True)
        self._finish_reaction(message, delivered=self.store.sent_message("direct_reply", message.message_id))
        self._note_turn(message)

    def _send_group_reply(self, message: ChatMessage, text: str, *, allow_flood: bool) -> bool:
        if not text or not text.strip():
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
                    self.send_fn(current_chat_id, remove_rally_signature(item["text"]))
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
