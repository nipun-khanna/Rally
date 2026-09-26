"""Connect conversation state, agent decisions, scheduler, and approved actions."""

import logging
from datetime import date, datetime, time as clock_time, timedelta, timezone
from threading import Lock, RLock
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agent import GrokProviderError
from app.availability import AvailabilityWindow, choose_slot, looks_like_availability, parse_availability
from app.bluebubbles import DeliveryUncertainError
from app.models import ChatMessage, Plan, PlanFacts, Proposal
from app.message_text import remove_rally_signature
from app.policy import (eligible_for_intervention, explicitly_addresses_rally,
                        valid_approval, valid_calendar_approval)
from app.places import PlacesError
from app.reservations import create_reservation
from app.store import Store
from app.web import should_search_web
from app.tone import group_tone
from app.adaptive.handler import should_use_adaptive


logger = logging.getLogger(__name__)


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
                 availability_fn=None, time_zone: str = "America/New_York"):
        self.store = store
        self.agent = agent
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
        self._chat_locks_guard = Lock()
        self._chat_locks = {}

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

    def receive(self, message: ChatMessage) -> bool:
        if not self._chat_allowed(message.chat_id):
            return False
        with self._chat_lock(message.chat_id):
            return self._receive(message)

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
        if explicitly_addresses_rally(message.text) and not self.store.has_message(
                "direct_reply", message.message_id):
            portal_answer = self.portal_handler(message) if self.portal_handler else None
            answer = portal_answer
            if portal_answer is None and self.adaptive_handler and should_use_adaptive(message.text):
                try:
                    answer = self.adaptive_handler.answer(message)
                except Exception as exc:
                    _log_scheduled_failure("adaptive answer", exc)
                    answer = "I couldn't finish that request. Please try again later."
                self._queue_and_send(message.chat_id, f"Rally: {answer}",
                                     "direct_reply", message.message_id)
                self.store.mark_processed(message.message_id)
                return True
            if portal_answer is None and self.web_answer_fn and should_search_web(message.text):
                try:
                    answer = self.web_answer_fn(message.text, tone=group_tone(messages))
                except Exception as exc:
                    _log_scheduled_failure("web answer", exc)
                    answer = "Web search isn't available right now, so I can't verify current options. Try again later."
                self._queue_and_send(message.chat_id, f"Rally: {answer}",
                                     "direct_reply", message.message_id)
                self.store.mark_processed(message.message_id)
                return True
            if portal_answer is None:
                answer = self.agent.answer_direct(message.text, plan.facts if plan else None, messages)
            self._queue_and_send(message.chat_id, f"Rally: {answer}",
                                 "direct_reply", message.message_id)
            if portal_answer is not None:
                self.store.mark_processed(message.message_id)
                return True
        try:
            facts = self.extractor.extract(messages, plan.facts if plan else None)
        except Exception as exc:
            self._record_extraction_failure([message.message_id], exc)
            raise
        if facts.activity:
            if not plan or plan.state not in ("DONE", "ABANDONED") or (
                    facts.activity, facts.goal, facts.date) != (
                    plan.facts.activity, plan.facts.goal, plan.facts.date):
                plan = self.store.save_plan(message.chat_id, facts, message.sent_at)
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

    def _tick(self, now: datetime | None = None) -> int:
        return self.tick(now)

    def evaluate(self, chat_id: str, now: datetime | None = None) -> bool:
        """Demo trigger that uses the same eligibility and action path as tick."""
        if not self._chat_allowed(chat_id):
            return False
        with self._chat_lock(chat_id):
            return self._evaluate(chat_id, now)

    def _evaluate(self, chat_id: str, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if not self._chat_allowed(chat_id):
            return False
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

    def _queue_and_send(self, chat_id: str, text: str, kind: str, ref_id: str):
        self.store.queue_message(chat_id, remove_rally_signature(text), kind, ref_id)
        self.deliver_pending(chat_id)

    def deliver_pending(self, chat_id: str | None = None):
        self._deliver_pending(chat_id)

    def _deliver_pending(self, chat_id: str | None = None):
        for item in self.store.pending_messages():
            current_chat_id = item["chat_id"]
            if (chat_id is not None and current_chat_id != chat_id) or not self._chat_allowed(current_chat_id):
                continue
            with self._chat_lock(current_chat_id):
                try:
                    self.send_fn(current_chat_id, remove_rally_signature(item["text"]))
                except DeliveryUncertainError:
                    self.store.set_delivery(item["id"], "uncertain", "Inspect the iMessage thread before retrying")
                    continue
                except Exception:
                    self.store.set_delivery(item["id"], "failed", "Message delivery failed")
                    continue
                self.store.set_delivery(item["id"], "sent")
                if item["kind"] == "final" and item["ref_id"]:
                    proposal = self.store.get_proposal(item["ref_id"])
                    if proposal:
                        self.store.set_state(proposal.plan_id, "DONE")
