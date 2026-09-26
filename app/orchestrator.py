"""Connect conversation state, agent decisions, scheduler, and approved actions."""

from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from app.bluebubbles import DeliveryUncertainError
from app.models import ChatMessage, Plan, PlanFacts, Proposal
from app.policy import (eligible_for_intervention, explicitly_addresses_rally,
                        valid_approval, valid_calendar_approval)
from app.places import PlacesError
from app.reservations import create_reservation
from app.store import Store


class RallyService:
    def __init__(self, store: Store, agent, search_fn, send_fn, stall_minutes: int = 30,
                 extractor=None, calendar_fn=None, allowed_chat_ids: set[str] | frozenset[str] | None = None,
                 portal_handler=None):
        self.store = store
        self.agent = agent
        self.extractor = extractor or agent
        self.calendar_fn = calendar_fn
        self.search_fn = search_fn
        self.send_fn = send_fn
        self.stall_minutes = stall_minutes
        self.allowed_chat_ids = None if allowed_chat_ids is None else frozenset(allowed_chat_ids)
        self.portal_handler = portal_handler
        self._lock = RLock()

    def _chat_allowed(self, chat_id: str) -> bool:
        return self.allowed_chat_ids is None or chat_id in self.allowed_chat_ids

    def receive(self, message: ChatMessage) -> bool:
        with self._lock:
            return self._receive(message)

    def _receive(self, message: ChatMessage) -> bool:
        if not self._chat_allowed(message.chat_id) or message.is_from_rally or not message.text.strip():
            return False
        if not self.store.add_message(message) and self.store.is_processed(message.message_id):
            return False
        plan = self.store.get_plan(message.chat_id)
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
            if portal_answer is None:
                answer = self.agent.answer_direct(message.text, plan.facts if plan else None, messages)
            self._queue_and_send(message.chat_id, f"Rally: {answer}",
                                 "direct_reply", message.message_id)
            if portal_answer is not None:
                self.store.mark_processed(message.message_id)
                return True
        facts = self.extractor.extract(messages, plan.facts if plan else None)
        if facts.activity:
            if not plan or plan.state not in ("DONE", "ABANDONED") or (
                    facts.activity, facts.goal, facts.date) != (
                    plan.facts.activity, plan.facts.goal, plan.facts.date):
                plan = self.store.save_plan(message.chat_id, facts, message.sent_at)
        self.store.mark_processed(message.message_id)
        return True

    def tick(self, now: datetime | None = None) -> int:
        with self._lock:
            return self._tick(now)

    def _tick(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        for plan in self.store.active_plans():
            if not self._chat_allowed(plan.chat_id):
                continue
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
        self.deliver_pending()
        count = 0
        for plan in self.store.active_plans():
            if not self._chat_allowed(plan.chat_id):
                continue
            if eligible_for_intervention(plan, now, self.stall_minutes):
                self._intervene(plan, now)
                count += 1
        return count

    def evaluate(self, chat_id: str, now: datetime | None = None) -> bool:
        """Demo trigger that uses the same eligibility and action path as tick."""
        with self._lock:
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
        if decision.confidence < 0.6 or decision.action == "WAIT":
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        if decision.action == "ASK" or not facts.location or not facts.date:
            if not facts.location:
                question = f"Which city or area should I use for {facts.goal or facts.activity}?"
            elif not facts.date:
                question = f"Which date works for {facts.goal or facts.activity}?"
            else:
                question = f"Could you clarify {facts.blockers[0]}?" if facts.blockers else "What detail should I use?"
            self._queue_and_send(plan.chat_id, f"Rally: {question}", "ask", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        if decision.action not in ("PROPOSE", "NUDGE") or decision.tool != "search_places":
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
        time = self._proposal_time(facts)
        if not time:
            self._queue_and_send(plan.chat_id, "Rally: What time works for everyone?", "ask", plan.id)
            self.store.mark_intervened(plan.id, plan.version, now)
            return
        proposal = Proposal(str(uuid4()), plan.id, plan.version, venue.id, venue.name,
                            venue.address, facts.date, time,
                            facts.party_size or len(set(facts.participants)),
                            created_at=now.isoformat())
        self.store.save_proposal(proposal)
        display_time = self._display_time(time)
        attribution = (" Venue data: Geoapify (https://www.geoapify.com/), "
                       "© OpenStreetMap contributors (https://www.openstreetmap.org/copyright)."
                       if venue.source == "geoapify" else " Demo venue data.")
        approval_prompt = (" Reply 'Book it' for the demo reservation, or 'Book it and add a calendar event' for both."
                           if self.calendar_fn else " Want me to make a demo reservation?")
        text = (f"Rally: {facts.goal or facts.activity} could work at {venue.name}, "
                f"{venue.address}, on {facts.date} at {display_time} for {proposal.party_size}. "
                f"{approval_prompt.strip()}{attribution}")
        self._queue_and_send(plan.chat_id, text, "proposal", proposal.id)
        self.store.mark_intervened(plan.id, plan.version, now)

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
            self.deliver_pending()

    def _queue_and_send(self, chat_id: str, text: str, kind: str, ref_id: str):
        self.store.queue_message(chat_id, text, kind, ref_id)
        self.deliver_pending()

    def deliver_pending(self):
        with self._lock:
            self._deliver_pending()

    def _deliver_pending(self):
        for item in self.store.pending_messages():
            if not self._chat_allowed(item["chat_id"]):
                continue
            try:
                self.send_fn(item["chat_id"], item["text"])
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
