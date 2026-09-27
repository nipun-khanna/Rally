"""Content-safe debug logging for the local Playwright browser."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit, urlunsplit

from app.bluebubbles import is_private_direct_chat


logger = logging.getLogger("rally.browser")
_CONFIGURED = False


def configure_browser_logging(enabled: bool | None = None) -> logging.Logger:
    """Attach a stream handler. DEBUG when RALLY_BROWSER_DEBUG=1."""
    global _CONFIGURED
    if enabled is None:
        enabled = os.environ.get("RALLY_BROWSER_DEBUG", "0") == "1"
    logger.setLevel(logging.DEBUG if enabled else logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    _CONFIGURED = True
    return logger


def chat_label(chat_id: str) -> str:
    """self-DM vs group plus last 6 chars — never a full GUID."""
    if not isinstance(chat_id, str) or not chat_id.strip():
        return "kind=none tail=none"
    if ";+;" in chat_id:
        kind = "group"
    elif is_private_direct_chat(chat_id):
        kind = "self-dm"
    else:
        kind = "other"
    tail = chat_id[-6:] if len(chat_id) >= 6 else "short"
    return f"kind={kind} tail=…{tail}"


def safe_url(url: str | None) -> str:
    """Host + path only. Drop userinfo and query (tokens, search text)."""
    if not isinstance(url, str) or not url.strip():
        return ""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return parsed.scheme or "invalid"
    return urlunsplit((parsed.scheme, parsed.hostname, parsed.path or "/", "", ""))


def action_summary(action: dict | None) -> str:
    """Log tool name and URL/role, never fill text or secrets."""
    if not isinstance(action, dict):
        return "action=none"
    kind = action.get("action") or "unknown"
    parts = [f"action={kind}"]
    if action.get("url"):
        parts.append(f"url={safe_url(action.get('url'))}")
    if action.get("query"):
        parts.append(f"query_len={len(str(action.get('query')))}")
    if action.get("role"):
        parts.append(f"role={action.get('role')}")
    if action.get("name"):
        parts.append(f"name={str(action.get('name'))[:80]}")
    if action.get("direction"):
        parts.append(f"direction={action.get('direction')}")
    if "text" in action:
        parts.append("text=redacted")
    return " ".join(parts)


configure_browser_logging()
