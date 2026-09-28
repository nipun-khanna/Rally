"""Allowlisted-chat inbound path for browser tasks and approval codes."""

from __future__ import annotations

import re

from app.bluebubbles import is_private_direct_chat, normalize_webhook
from app.browser.agent import ToolContext, looks_like_browser_request
from app.browser.log import chat_label, logger
from app.message_text import add_rally_signature
from app.policy import explicitly_addresses_rally
from app.web import is_score_request, should_search_web
from app.voice.caller import looks_like_restaurant_booking


_APPROVAL = re.compile(r"^\s*(approve|cancel)\s+([A-Za-z0-9]{6,8})\s*$", re.I)


def _signed(body: str) -> str:
    return add_rally_signature(body)


def format_browser_result(result: dict) -> str:
    status = result.get("status")
    if status == "awaiting_approval":
        code = result["code"]
        return (f"I need your approval to {result.get('summary') or 'continue'}. "
                f"Reply approve {code} or cancel {code}.")
    if status == "awaiting_human":
        body = result.get("answer") or (
            "I'm on the reservation page — sign in / confirm on the Mac.")
        return _signed(body)
    answer = result.get("answer") or "The browser could not finish that request."
    url = result.get("url")
    if status == "complete" and url:
        return _signed(f"{answer}\n\nSource: {url}")
    if status == "uncertain":
        return _signed(answer or "The action may have started. I did not retry it.")
    if status == "blocked":
        return _signed(answer or "That browser action was blocked.")
    if status == "stale":
        return _signed(answer or "The page or values changed. Approval is no longer valid.")
    return _signed(answer)


class BrowserInbound:
    def __init__(self, owner_chat_id: str, owner_sender_id: str, task_service, send_fn,
                 allowed_chat_ids=None, group_turns=None):
        self.owner_chat_id = owner_chat_id
        self.owner_sender_id = owner_sender_id
        self.task_service = task_service
        self.send_fn = send_fn
        allowed = set(allowed_chat_ids or ())
        if owner_chat_id:
            allowed.add(owner_chat_id)
        self.allowed_chat_ids = frozenset(allowed)
        self.group_turns = group_turns

    def _in_turn(self, incoming) -> bool:
        if self.group_turns is None:
            return False
        return bool(self.group_turns.active(incoming.chat_id, incoming.sent_at))

    def try_receive(self, payload) -> bool | None:
        incoming = normalize_webhook(
            payload, allowed_direct_chat_ids=self.allowed_chat_ids)
        if incoming is None or incoming.chat_id not in self.allowed_chat_ids:
            return None
        approval = _APPROVAL.match(incoming.text)
        browser_intent = looks_like_browser_request(incoming.text)
        invoked = explicitly_addresses_rally(incoming.text)
        owner = incoming.chat_id == self.owner_chat_id
        logger.debug(
            "webhook inbound %s owner=%s private=%s group=%s intent=%s "
            "addressed=%s approval=%s sender=%s",
            chat_label(incoming.chat_id), owner,
            is_private_direct_chat(incoming.chat_id), ";+;" in incoming.chat_id,
            browser_intent, invoked, bool(approval),
            "local" if incoming.sender_id == "local-imessage-account" else "other")
        if approval:
            result = self.task_service.resolve_approval(
                ToolContext(incoming.chat_id, incoming.sender_id, incoming.message_id,
                            incoming.text),
                approval.group(2), approval.group(1).lower() == "approve")
            if result is None:
                return False
            self.send_fn(incoming.chat_id, format_browser_result(result))
            return True
        # Grounded xAI web search owns lookups. Explicit page control
        # (open a URL, click, fill) still uses the browser.
        if looks_like_restaurant_booking(incoming.text):
            return None
        if not looks_like_browser_request(incoming.text) and (
                is_score_request(incoming.text) or should_search_web(incoming.text)):
            return None
        if not browser_intent or not (invoked or self._in_turn(incoming)):
            return None
        try:
            result = self.task_service.run(
                ToolContext(incoming.chat_id, incoming.sender_id, incoming.message_id,
                            incoming.text),
                incoming.text)
        except Exception:
            logger.exception("task run crashed %s", chat_label(incoming.chat_id))
            result = {"status": "failed",
                      "answer": "The browser request failed. Ask Rally again."}
        if result.get("status") == "duplicate":
            return True
        self.send_fn(incoming.chat_id, format_browser_result(result))
        return True
