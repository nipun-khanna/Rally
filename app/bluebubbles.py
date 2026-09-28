"""BlueBubbles webhook and text-message transport for Rally.

BlueBubbles posts ``new-message`` events with the message in ``data``.
The chat GUID in that event is reused when sending a reply. v1.9.9
``POST /api/v1/message/text`` also accepts ``selectedMessageGuid`` and
``partIndex`` so a reply can sit in that inbound message's iMessage thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from app.message_text import remove_rally_signature


def is_private_direct_chat(chat_id: str) -> bool:
    """True for a 1:1 ``{service};-;{id}`` thread. Groups use ``;+;``."""
    if not isinstance(chat_id, str) or ";+;" in chat_id:
        return False
    service, sep, rest = chat_id.partition(";-;")
    return bool(sep) and bool(service) and bool(rest)


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


_ECHO_ID_TTL_SECONDS = 6 * 60 * 60
_ECHO_TEXT_TTL_SECONDS = 60
_ECHO_MAX = 400


class _OutboundEchoes:
    """Remember this process's sends so their iMessage echoes are not new mail.

    Confirmed and temporary message ids stay remembered for hours. Identical
    text is only a short fallback for an echo that arrives before those ids are
    known. A later owner message with the same words and a new id is accepted.
    The file stores ids and hashes only, not message text.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._ids: dict[str, float] = {}
        self._prints: dict[str, float] = {}

    def configure(self, path: Path | None) -> None:
        with self._lock:
            self._path = path
            self._ids.clear()
            self._prints.clear()
            self._load_locked()

    def clear(self) -> None:
        self.configure(None)

    def remember(self, chat_id: str, text: str, *ids: str, clear_text: bool = False) -> None:
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            if chat_id and text:
                key = _fingerprint(chat_id, text)
                if clear_text:
                    self._prints.pop(key, None)
                else:
                    self._prints[key] = now + _ECHO_TEXT_TTL_SECONDS
            for ident in ids:
                if isinstance(ident, str) and ident.strip():
                    self._ids[ident] = now + _ECHO_ID_TTL_SECONDS
            self._trim_locked()
            self._save_locked()

    def matches(self, chat_id: str, text: str, *ids: str) -> bool:
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            for ident in ids:
                if isinstance(ident, str) and ident in self._ids and self._ids[ident] >= now:
                    return True
            if chat_id and text:
                stamp = self._prints.get(_fingerprint(chat_id, text))
                if stamp is not None and stamp >= now:
                    return True
        return False

    def _prune_locked(self, now: float) -> None:
        self._ids = {key: stamp for key, stamp in self._ids.items() if stamp >= now}
        self._prints = {key: stamp for key, stamp in self._prints.items() if stamp >= now}

    def _trim_locked(self) -> None:
        if len(self._ids) > _ECHO_MAX:
            for key in sorted(self._ids, key=self._ids.get)[: len(self._ids) - _ECHO_MAX]:
                self._ids.pop(key, None)
        if len(self._prints) > _ECHO_MAX:
            for key in sorted(self._prints, key=self._prints.get)[: len(self._prints) - _ECHO_MAX]:
                self._prints.pop(key, None)

    def _load_locked(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            payload = json.loads(self._path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        now = time.time()
        ids = payload.get("ids")
        prints = payload.get("prints")
        if isinstance(ids, dict):
            self._ids = {key: stamp for key, stamp in ids.items()
                         if isinstance(key, str) and isinstance(stamp, (int, float)) and stamp >= now}
        if isinstance(prints, dict):
            self._prints = {key: stamp for key, stamp in prints.items()
                            if isinstance(key, str) and isinstance(stamp, (int, float)) and stamp >= now}

    def _save_locked(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({"ids": self._ids, "prints": self._prints}))
            temporary.replace(self._path)
        except OSError:
            return


_echoes = _OutboundEchoes()


def configure_outbound_echoes(path: Path | None) -> None:
    """Load remembered send ids from ``path``. ``None`` keeps memory only."""
    _echoes.configure(path)


def reset_outbound_echoes() -> None:
    """Drop remembered sends. Tests use this so cases do not share echoes."""
    _echoes.clear()


def _fingerprint(chat_id: str, text: str) -> str:
    return hashlib.sha256(f"{chat_id}\n{text}".encode("utf-8")).hexdigest()


def _message_ids(data: dict) -> list[str]:
    found = []
    for key in ("guid", "tempGuid"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value)
    return found


def normalize_webhook(payload: Any, *, allowed_direct_chat_ids=frozenset()) -> IncomingMessage | None:
    """Return a usable human group message, or ``None`` for other events."""
    if not isinstance(payload, dict) or payload.get("type") not in {
            "new-message", "updated-message", "message-updated"}:
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

    echo_ids = _message_ids(data)
    if data["isFromMe"] and _echoes.matches("", "", *echo_ids):
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
        if data["isFromMe"] and _echoes.matches(chat_id, text):
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


# BlueBubbles v1.9.9 sendText accepts selectedMessageGuid + partIndex to reply
# in that message's iMessage thread. That field forces Private API. Invalid
# GUIDs are omitted so unthreaded text still sends.
_MESSAGE_GUID = re.compile(r"^[^\s\x00-\x1f\x7f]+$")


def send_message(
    base_url: str,
    password: str,
    chat_id: str,
    text: str,
    opener: Callable[..., Any] = urlopen,
    *,
    selected_message_guid: str | None = None,
) -> dict[str, Any]:
    """Send text to a BlueBubbles chat and return its JSON response.

    Failures use fixed messages because HTTP exceptions may contain the URL,
    including its password query parameter. When ``selected_message_guid`` is a
    usable message GUID, the payload includes ``selectedMessageGuid`` so the
    reply lands in that inbound message's thread.
    """
    if isinstance(text, str):
        text = remove_rally_signature(text)
    if not all(isinstance(value, str) and value for value in (password, chat_id, text)):
        raise ValueError("BlueBubbles password, chat ID, and text are required")
    if not isinstance(base_url, str):
        raise ValueError("Invalid BlueBubbles base URL")
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Invalid BlueBubbles base URL")

    path = parsed.path.rstrip("/") + "/api/v1/message/text"
    url = urlunsplit((parsed.scheme, parsed.netloc, path, urlencode({"password": password}), ""))
    temp_guid = str(uuid4())
    _echoes.remember(chat_id, text, temp_guid)
    payload = {"chatGuid": chat_id, "message": text, "tempGuid": temp_guid}
    if isinstance(selected_message_guid, str) and _MESSAGE_GUID.fullmatch(selected_message_guid):
        payload["selectedMessageGuid"] = selected_message_guid
        payload["partIndex"] = 0
    body = json.dumps(payload).encode("utf-8")
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
    sent = result.get("data")
    if isinstance(sent, dict):
        confirmed = [
            value for key in ("guid", "tempGuid")
            if isinstance(value := sent.get(key), str) and value.strip()
        ]
        if confirmed:
            _echoes.remember(chat_id, text, *confirmed, clear_text=True)
    return result


def attachment_chat_guid(chat_id: str) -> str:
    """BlueBubbles attachment send wants a bare DM address, not service;-;id."""
    if is_private_direct_chat(chat_id):
        return chat_id.partition(";-;")[2]
    return chat_id


def _multipart(fields: dict[str, str], filename: str, data: bytes, mime_type: str) -> tuple[bytes, str]:
    boundary = uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n".encode("utf-8")
        )
    safe_name = filename.replace('"', "")
    chunks.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"attachment\"; "
        f"filename=\"{safe_name}\"\r\nContent-Type: {mime_type}\r\n\r\n".encode("utf-8")
    )
    chunks.append(data)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def send_attachment(
    base_url: str,
    password: str,
    chat_id: str,
    file_path: str | Path,
    opener: Callable[..., Any] = urlopen,
    *,
    name: str | None = None,
    mime_type: str | None = None,
) -> dict[str, Any]:
    """Send a local file to a BlueBubbles chat. Never leak the password on failure."""
    if not all(isinstance(value, str) and value for value in (password, chat_id)):
        raise ValueError("BlueBubbles password and chat ID are required")
    if not isinstance(base_url, str):
        raise ValueError("Invalid BlueBubbles base URL")
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Invalid BlueBubbles base URL")
    path = Path(file_path)
    try:
        data = path.read_bytes()
    except OSError:
        raise ValueError("Attachment file is required") from None
    if not data:
        raise ValueError("Attachment file is required")
    filename = name or path.name or "rally.bin"
    if "/" in filename or "\\" in filename or "\x00" in filename:
        filename = "rally.bin"
    mime_type = mime_type or "application/octet-stream"
    target = attachment_chat_guid(chat_id)
    if not target:
        raise ValueError("BlueBubbles password and chat ID are required")

    api_path = parsed.path.rstrip("/") + "/api/v1/message/attachment"
    url = urlunsplit((parsed.scheme, parsed.netloc, api_path, urlencode({"password": password}), ""))
    body, content_type = _multipart(
        {"chatGuid": target, "tempGuid": str(uuid4()), "name": filename},
        filename, data, mime_type,
    )
    request = Request(url, data=body, headers={"Content-Type": content_type}, method="POST")

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
