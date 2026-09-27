"""BlueBubbles webhook and text-message transport for Rally.

BlueBubbles posts ``new-message`` events with the message in ``data``.
The chat GUID in that event is reused when sending a reply, preserving the
original group conversation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    chat_id: str
    sender_id: str
    text: str
    sent_at: datetime
    is_from_rally: bool = False


class DeliveryUncertainError(RuntimeError):
    """BlueBubbles may have accepted a message despite a failed response."""


def normalize_webhook(payload: Any, *, allowed_direct_chat_ids=frozenset()) -> IncomingMessage | None:
    """Return a usable human group message, or ``None`` for other events."""
    if not isinstance(payload, dict) or payload.get("type") != "new-message":
        return None
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("isFromMe"), bool):
        return None
    if data.get("associatedMessageType"):
        return None

    message_id = data.get("guid")
    text = data.get("text")
    handle = data.get("handle")
    chats = data.get("chats")
    sent_at_ms = data.get("dateCreated")
    if (
        not isinstance(message_id, str)
        or not message_id.strip()
        or not isinstance(text, str)
        or not text.strip()
        or (not data["isFromMe"] and not isinstance(handle, dict))
        or not isinstance(chats, list)
        or isinstance(sent_at_ms, bool)
        or not isinstance(sent_at_ms, (int, float))
    ):
        return None

    if data["isFromMe"] and re.match(r"^\s*Rally\s*:", text, re.I):
        return None
    sender_id = "local-imessage-account" if data["isFromMe"] else handle.get("address")
    if not isinstance(sender_id, str) or not sender_id.strip():
        return None

    for chat in chats:
        if not isinstance(chat, dict):
            continue
        chat_id = chat.get("guid")
        if not isinstance(chat_id, str) or not chat_id.strip():
            continue
        if ";+;" not in chat_id and chat_id not in allowed_direct_chat_ids:
            continue
        try:
            sent_at = datetime.fromtimestamp(sent_at_ms / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return IncomingMessage(
            message_id=message_id,
            chat_id=chat_id,
            sender_id=sender_id,
            text=text,
            sent_at=sent_at,
        )
    return None


def send_message(
    base_url: str,
    password: str,
    chat_id: str,
    text: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Send text to a BlueBubbles chat and return its JSON response.

    Failures use fixed messages because HTTP exceptions may contain the URL,
    including its password query parameter.
    """
    if not all(isinstance(value, str) and value for value in (password, chat_id, text)):
        raise ValueError("BlueBubbles password, chat ID, and text are required")
    if not isinstance(base_url, str):
        raise ValueError("Invalid BlueBubbles base URL")
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Invalid BlueBubbles base URL")

    path = parsed.path.rstrip("/") + "/api/v1/message/text"
    url = urlunsplit((parsed.scheme, parsed.netloc, path, urlencode({"password": password}), ""))
    body = json.dumps(
        {"chatGuid": chat_id, "message": text, "tempGuid": str(uuid4())}
    ).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with opener(request, timeout=45) as response:
            result = json.load(response)
    except (HTTPError, URLError, OSError):
        raise DeliveryUncertainError("BlueBubbles delivery outcome is uncertain") from None
    except (UnicodeError, json.JSONDecodeError):
        raise DeliveryUncertainError("BlueBubbles delivery outcome is uncertain") from None

    if not isinstance(result, dict):
        raise DeliveryUncertainError("BlueBubbles delivery outcome is uncertain")
    if result.get("status") != 200:
        raise DeliveryUncertainError("BlueBubbles rejected the message; delivery outcome is uncertain")
    return result
