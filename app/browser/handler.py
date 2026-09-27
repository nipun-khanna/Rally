"""Owner-chat inbound path for browser tasks and approval codes."""

from __future__ import annotations

import re

from app.bluebubbles import normalize_webhook
from app.browser.agent import ToolContext, looks_like_browser_request


_APPROVAL = re.compile(r"^\s*(approve|cancel)\s+([A-Za-z0-9]{6,8})\s*$", re.I)


def format_browser_result(result: dict) -> str:
    status = result.get("status")
    if status == "awaiting_approval":
        code = result["code"]
        return (f"I need your approval to {result.get('summary') or 'continue'}. "
                f"Reply approve {code} or cancel {code}.")
    answer = result.get("answer") or "The browser could not finish that request."
    url = result.get("url")
    if status == "complete" and url:
        return f"{answer}\n\nSource: {url}"
    if status == "uncertain":
        return answer or "The action may have started. I did not retry it."
    if status == "blocked":
        return answer or "That browser action was blocked."
    if status == "stale":
        return answer or "The page or values changed. Approval is no longer valid."
    return answer


class BrowserInbound:
    def __init__(self, owner_chat_id: str, owner_sender_id: str, task_service, send_fn):
        self.owner_chat_id = owner_chat_id
        self.owner_sender_id = owner_sender_id
        self.task_service = task_service
        self.send_fn = send_fn

    def try_receive(self, payload) -> bool | None:
        incoming = normalize_webhook(payload, allowed_direct_chat_ids={self.owner_chat_id})
        if incoming is None or incoming.chat_id != self.owner_chat_id:
            return None
        approval = _APPROVAL.match(incoming.text)
        browser_intent = looks_like_browser_request(incoming.text)
        if incoming.sender_id != self.owner_sender_id:
            if approval or browser_intent:
                return False
            return None
        if approval:
            result = self.task_service.resolve_approval(
                ToolContext(incoming.chat_id, incoming.sender_id, incoming.message_id,
                            incoming.text),
                approval.group(2), approval.group(1).lower() == "approve")
            if result is None:
                return False
            self.send_fn(incoming.chat_id, format_browser_result(result))
            return True
        if not browser_intent:
            return None
        result = self.task_service.run(
            ToolContext(incoming.chat_id, incoming.sender_id, incoming.message_id,
                        incoming.text),
            incoming.text)
        self.send_fn(incoming.chat_id, format_browser_result(result))
        return True
