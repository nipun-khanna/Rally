"""BlueBubbles tapback transport.

BlueBubbles v1.9.9's reaction route accepts ``chatGuid``,
``selectedMessageGuid``, ``reaction``, and ``partIndex``. Tapbacks require its
Private API helper. See the upstream message router:
https://github.com/BlueBubblesApp/bluebubbles-server/blob/v1.9.9/packages/server/src/server/api/http/api/v1/routers/messageRouter.ts
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ReactionKind = Literal["love", "like", "dislike", "laugh", "emphasize", "question", "👀"]
ReactionStatus = Literal["sent", "unsupported", "unavailable", "uncertain"]
REACTION_KINDS = frozenset(("love", "like", "dislike", "laugh", "emphasize", "question"))
SEEN_REACTION = "👀"
DONE_REACTION = "like"
_ALIASES = {
    "haha": "laugh", "ha": "laugh", "lol": "laugh", "lmao": "laugh",
    "heart": "love", "love": "love",
    "thumbs-up": "like", "thumbsup": "like", "+1": "like", "like": "like",
    "thumbs-down": "dislike", "thumbsdown": "dislike", "-1": "dislike", "dislike": "dislike",
    "exclaim": "emphasize", "emphasize": "emphasize", "!!": "emphasize", "!": "emphasize",
    "question": "question", "?": "question", "??": "question",
}
_ALLOWED_REACTIONS = REACTION_KINDS | {SEEN_REACTION} | {f"-{kind}" for kind in REACTION_KINDS | {SEEN_REACTION}}


def completion_reaction(value: str | None) -> str | None:
    """Map a model or alias tapback onto a BlueBubbles kind, or None."""
    if not isinstance(value, str) or not value.strip() or value.strip() == SEEN_REACTION:
        return None
    key = value.strip().casefold()
    mapped = _ALIASES.get(key, key if key in REACTION_KINDS else None)
    return mapped


# BlueBubbles allowlist IDs are live `any;+;…` or classic `iMessage;+;…` groups.
_GROUP_GUID = re.compile(r"^[^;\s]+;\+;\S+$")
_MESSAGE_GUID = re.compile(r"^[^\s\x00-\x1f\x7f]+$")
_PREFLIGHT_TTL = 15.0


@dataclass(frozen=True)
class ReactionResult:
    status: ReactionStatus
    reason: str
    provider_message_guid: str | None = None


_preflight_cache: dict[tuple[str, str], tuple[float, ReactionResult]] = {}


def clear_helper_cache() -> None:
    _preflight_cache.clear()


def _url(base_url: str, password: str, path: str) -> str:
    if not isinstance(base_url, str):
        raise ValueError("Invalid BlueBubbles base URL")
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Invalid BlueBubbles base URL")
    if not isinstance(password, str) or not password:
        raise ValueError("BlueBubbles password is required")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + path,
                       urlencode({"password": password}), ""))


def helper_status(
    base_url: str,
    password: str,
    *,
    opener: Callable[..., Any] = urlopen,
    wait: bool = True,
) -> ReactionResult:
    """Return whether the Private API helper is connected, with a short TTL cache."""
    key = (base_url.rstrip("/"), password)
    now = time.monotonic()
    cached = _preflight_cache.get(key)
    if cached and now - cached[0] < _PREFLIGHT_TTL:
        return cached[1]
    if not wait:
        return ReactionResult("unsupported", "BlueBubbles Private API status is not cached")
    info_url = _url(base_url, password, "/api/v1/server/info")
    try:
        with opener(Request(info_url, method="GET"), timeout=5) as response:
            info = json.load(response)
    except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError):
        result = ReactionResult("unavailable", "BlueBubbles Private API status could not be checked")
        _preflight_cache[key] = (now, result)
        return result
    if not isinstance(info, dict) or info.get("status") != 200 or not isinstance(info.get("data"), dict):
        result = ReactionResult("unavailable", "BlueBubbles Private API status could not be checked")
    elif info["data"].get("private_api") is not True or info["data"].get("helper_connected") is not True:
        result = ReactionResult("unsupported", "BlueBubbles Private API helper is not connected")
    else:
        result = ReactionResult("sent", "BlueBubbles Private API helper is connected")
    _preflight_cache[key] = (now, result)
    return result


def set_typing(
    base_url: str,
    password: str,
    chat_id: str,
    typing: bool,
    *,
    opener: Callable[..., Any] = urlopen,
    wait_for_helper: bool = True,
) -> ReactionResult:
    """Start or stop a typing indicator. Requires the Private API helper."""
    if not isinstance(chat_id, str) or not _GROUP_GUID.fullmatch(chat_id):
        raise ValueError("A BlueBubbles iMessage group chat GUID is required")
    ready = helper_status(base_url, password, opener=opener, wait=wait_for_helper)
    if ready.status != "sent":
        return ready
    path = "/api/v1/chat/" + quote(chat_id, safe="") + "/typing"
    request = Request(_url(base_url, password, path), method="POST" if typing else "DELETE")
    try:
        with opener(request, timeout=5) as response:
            json.load(response)
    except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError):
        return ReactionResult("uncertain", "BlueBubbles typing indicator outcome is uncertain")
    return ReactionResult("sent", "BlueBubbles accepted the typing indicator")


def send_reaction(
    base_url: str,
    password: str,
    chat_id: str,
    message_id: str,
    reaction: str,
    *,
    opener: Callable[..., Any] = urlopen,
    wait_for_helper: bool = True,
) -> ReactionResult:
    """Send one tapback, after confirming the Private API helper is connected.

    A failed POST may already have been accepted by BlueBubbles, so callers
    must not retry an ``uncertain`` result automatically.
    """
    if not isinstance(chat_id, str) or not _GROUP_GUID.fullmatch(chat_id):
        raise ValueError("A BlueBubbles iMessage group chat GUID is required")
    if not isinstance(message_id, str) or not _MESSAGE_GUID.fullmatch(message_id):
        raise ValueError("A target message GUID is required")
    if not isinstance(reaction, str) or reaction not in _ALLOWED_REACTIONS:
        raise ValueError("Unsupported reaction kind")

    ready = helper_status(base_url, password, opener=opener, wait=wait_for_helper)
    if ready.status != "sent":
        return ready

    reaction_url = _url(base_url, password, "/api/v1/message/react")
    body = json.dumps({
        "chatGuid": chat_id,
        "selectedMessageGuid": message_id,
        "reaction": reaction,
        "partIndex": 0,
    }).encode("utf-8")
    request = Request(reaction_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener(request, timeout=15) as response:
            result = json.load(response)
    except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError):
        return ReactionResult("uncertain", "BlueBubbles reaction delivery outcome is uncertain")
    if not isinstance(result, dict) or result.get("status") != 200:
        return ReactionResult("uncertain", "BlueBubbles reaction delivery outcome is uncertain")
    data = result.get("data")
    guid = data.get("guid") if isinstance(data, dict) else None
    if not isinstance(guid, str) or not guid:
        return ReactionResult("uncertain", "BlueBubbles reaction acknowledgement was incomplete")
    return ReactionResult("sent", "BlueBubbles accepted the reaction", guid)
