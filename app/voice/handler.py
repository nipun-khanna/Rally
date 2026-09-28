"""Allowlisted-chat inbound path for restaurant reservation calls."""

from __future__ import annotations

from datetime import datetime, timezone

from app.bluebubbles import normalize_webhook
from app.message_text import add_rally_signature
from app.policy import explicitly_addresses_rally
from app.voice.caller import (extract_phone, format_call_status,
                              looks_like_call_request, looks_like_direct_call_request,
                              looks_like_restaurant_booking)
from app.voice.personal import callee_followup


class ReservationCallInbound:
    def __init__(self, caller, send_fn, allowed_chat_ids=None, group_turns=None,
                 call_store=None):
        self.caller = caller
        self.send_fn = send_fn
        self.allowed_chat_ids = (
            None if allowed_chat_ids is None else frozenset(allowed_chat_ids)
        )
        self.group_turns = group_turns
        self.call_store = call_store
        if call_store is not None:
            self.caller.snapshots = call_store
        self._seen: set[str] = set()

    def _snapshot_store(self):
        return (getattr(self.caller, "snapshots", None)
                or getattr(self.caller, "_memory_snapshots", None))

    def _should_advance_restaurant(self, incoming) -> bool:
        text = incoming.text
        if not (explicitly_addresses_rally(text) or self._in_turn(incoming)):
            return False
        if looks_like_restaurant_booking(text):
            return True
        if looks_like_direct_call_request(text):
            return False
        store = self._snapshot_store()
        if store is None or store.open_restaurant(incoming.chat_id) is None:
            return False
        from app.voice.restaurant import is_restaurant_followup
        return is_restaurant_followup(text)

    def _allowed(self, chat_id: str) -> bool:
        if self.allowed_chat_ids is None:
            return True
        return chat_id in self.allowed_chat_ids

    def _in_turn(self, incoming) -> bool:
        if self.group_turns is None:
            return False
        return bool(self.group_turns.active(incoming.chat_id, incoming.sent_at))

    def try_receive(self, payload) -> bool | None:
        incoming = normalize_webhook(
            payload, allowed_direct_chat_ids=self.allowed_chat_ids or frozenset())
        if incoming is None or not self._allowed(incoming.chat_id):
            return None
        if incoming.message_id in self._seen:
            return True
        if self._should_advance_restaurant(incoming):
            self._seen.add(incoming.message_id)
            if self.group_turns is not None:
                self.group_turns.mark_relevant(
                    incoming.chat_id, incoming.message_id, incoming.sent_at, incoming.text)
            try:
                from app.voice.restaurant import advance_restaurant_request
                result = advance_restaurant_request(
                    self.caller, incoming.text, chat_id=incoming.chat_id,
                    message_id=incoming.message_id)
            except Exception:
                body = "failed — the reservation call did not start."
            else:
                if result is None:
                    return True
                body = format_call_status(result)
            self.send_fn(incoming.chat_id, add_rally_signature(body))
            return True
        if not looks_like_call_request(incoming.text):
            return None
        invoked = explicitly_addresses_rally(incoming.text)
        if extract_phone(incoming.text) and not looks_like_direct_call_request(incoming.text):
            return None
        if looks_like_direct_call_request(incoming.text) and not invoked:
            return None
        if not invoked and not self._in_turn(incoming):
            return None
        if self.call_store is not None and self.call_store.get(incoming.message_id) is not None:
            return True
        request = self.caller.parse(incoming.text, chat_id=incoming.chat_id)
        if self.call_store is not None:
            if not self.call_store.claim(
                    incoming.message_id, incoming.chat_id,
                    request.destination_phone,
                    status="dialing" if request.destination_phone else "noted",
                    purpose=request.call_task, contact_name=request.venue):
                return True
        self._seen.add(incoming.message_id)
        if self.group_turns is not None:
            self.group_turns.mark_relevant(
                incoming.chat_id, incoming.message_id, incoming.sent_at, incoming.text)
        try:
            result = self.caller.run(incoming.text, chat_id=incoming.chat_id, parsed_request=request)
            if self.call_store is not None:
                self.call_store.record_result(
                    incoming.message_id, call_id=result.call_id,
                    status=("queued" if result.provider_status == "ended" else result.provider_status)
                    if result.call_id else "failed")
            body = format_call_status(result)
        except Exception:
            body = "failed — the call did not start."
        self.send_fn(incoming.chat_id, add_rally_signature(body))
        return True

    def _recover_unidentified_claims(self) -> int:
        """A claim with no provider id stays unknown. Do not dial it."""
        if self.call_store is None:
            return 0
        claims = getattr(self.call_store, "unidentified_claims", None)
        abandon = getattr(self.call_store, "abandon_unidentified", None)
        queue = getattr(self.call_store, "queue_notice", None)
        if claims is None or abandon is None or queue is None:
            return 0
        recovered = 0
        for attempt in claims():
            if not abandon(attempt["source_message_id"]):
                continue
            destination = attempt.get("destination") or "the restaurant"
            queue(attempt["chat_id"],
                  f"Rally: the call to {destination} was claimed but has no provider id. "
                  "Check Vapi manually. I did not redial.",
                  attempt["source_message_id"])
            finder = getattr(self.call_store, "restaurant_for_claim", None)
            snapshot = finder(attempt["source_message_id"], attempt["chat_id"]) if finder else None
            if snapshot is not None and snapshot.get("state") in {
                    "collecting", "awaiting_authorization", "dialing"}:
                self.call_store.update_restaurant(snapshot["id"], state="unknown")
            recovered += 1
        return recovered

    def reconcile_calls(self) -> int:
        """Poll a bounded set of saved Vapi calls and queue one terminal report."""
        recovered = self._recover_unidentified_claims()
        vapi = getattr(self.caller, "vapi", None)
        if self.call_store is None or vapi is None:
            return recovered
        finished = 0
        now = datetime.now(timezone.utc)
        for attempt in self.call_store.pending():
            age = (now - datetime.fromisoformat(attempt["created_at"])).total_seconds()
            if age > 86400:
                status = "timed_out"
            else:
                try:
                    status = vapi.get_call(attempt["call_id"])["status"]
                except Exception:
                    continue
            if status in {"ended", "timed_out"}:
                evidence = {"status": status, "structured": None, "transcript": ""}
                if status == "ended":
                    evidence_fn = getattr(vapi, "get_call_evidence", None)
                    if evidence_fn is not None:
                        try:
                            loaded = evidence_fn(attempt["call_id"])
                        except Exception:
                            loaded = None
                        if isinstance(loaded, dict):
                            evidence = loaded
                            evidence["status"] = status
                snapshot = None
                finder = getattr(self.call_store, "restaurant_for_call", None)
                if finder is not None:
                    snapshot = finder(attempt["call_id"])
                if snapshot is not None:
                    from app.voice.restaurant import restaurant_outcome
                    outcome, code = restaurant_outcome(evidence, snapshot["terms"])
                    terms = snapshot["terms"]
                    if outcome == "confirmed":
                        body = (
                            f"Rally: booked {terms['venue']} for {terms['party_size']} "
                            f"on {terms['date']} at {terms['time']} {terms['timezone']} "
                            f"under {terms['guest_name']}. confirmation {code}."
                        )
                        self.call_store.update_restaurant(snapshot["id"], state="confirmed")
                    else:
                        body = (
                            f"Rally: unresolved — the call to {attempt['destination']} ended "
                            "and the restaurant did not confirm the reservation."
                        )
                        self.call_store.update_restaurant(snapshot["id"], state="unresolved")
                else:
                    if status == "ended":
                        body, facts = callee_followup(
                            evidence,
                            name=attempt.get("contact_name") or "",
                            purpose=attempt.get("purpose") or "",
                        )
                        plan_store = getattr(self.caller, "plan_store", None)
                        if (facts is not None and facts.activity and plan_store is not None
                                and hasattr(plan_store, "save_plan")):
                            try:
                                plan_store.save_plan(
                                    attempt["chat_id"], facts, now)
                            except Exception:
                                pass
                    else:
                        who = attempt.get("contact_name") or "them"
                        body = (
                            f"The call with {who} has no confirmed outcome after 24 hours. "
                            "Check Vapi for details."
                        )
                if self.call_store.finish_and_queue(
                        attempt["source_message_id"], status, body):
                    finished += 1
            else:
                self.call_store.record_status(attempt["source_message_id"], status)
        return finished + recovered
