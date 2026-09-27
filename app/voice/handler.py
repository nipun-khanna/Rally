"""Allowlisted-chat inbound path for restaurant reservation calls."""

from __future__ import annotations

from app.bluebubbles import normalize_webhook
from app.message_text import add_rally_signature
from app.policy import explicitly_addresses_rally
from app.voice.caller import format_call_status, looks_like_call_request


class ReservationCallInbound:
    def __init__(self, caller, send_fn, allowed_chat_ids=None, group_turns=None):
        self.caller = caller
        self.send_fn = send_fn
        self.allowed_chat_ids = (
            None if allowed_chat_ids is None else frozenset(allowed_chat_ids)
        )
        self.group_turns = group_turns
        self._seen: set[str] = set()

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
        if not looks_like_call_request(incoming.text):
            return None
        invoked = explicitly_addresses_rally(incoming.text)
        if not invoked and not self._in_turn(incoming):
            return None
        self._seen.add(incoming.message_id)
        if self.group_turns is not None:
            self.group_turns.mark_relevant(
                incoming.chat_id, incoming.message_id, incoming.sent_at, incoming.text)
        try:
            result = self.caller.run(incoming.text, chat_id=incoming.chat_id)
            body = format_call_status(result)
        except Exception:
            body = "failed — the reservation call did not start. nothing is booked."
        self.send_fn(incoming.chat_id, add_rally_signature(body))
        return True
