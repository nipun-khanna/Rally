"""In-chat commands that share the hosted group archive, not the local admin desk."""

import re
from urllib.parse import urlsplit


_DASHBOARD = re.compile(
    r"\b(?:admin\s+dashboard|"
    r"(?:send(?:\s+me)?|open|share)\s+(?:the\s+)?(?:admin\s+)?dashboard|"
    r"(?:the\s+)?dashboard(?:\s+link)?)\b",
    re.I,
)
_ADMIN_ASK = re.compile(r"\badmin\s+dashboard\b", re.I)
_UNPUBLISHED = ("hosted page isn't live yet. "
                "the admin desk stays on the Mac that runs Rally.")


def hosted_page_reply(url: str, *, admin: bool = False) -> str:
    """Casual archive pointer. Never attach a token or chat GUID."""
    lead = f"here's the group page: {url}"
    if admin:
        return (f"{lead} the admin desk stays on the Mac that runs Rally — "
                f"i will not drop the token in this chat.")
    return lead


def _hosted_origin(app_url: str | None) -> str | None:
    if not isinstance(app_url, str) or not app_url.strip():
        return None
    origin = app_url.strip().rstrip("/")
    host = (urlsplit(origin).hostname or "").casefold()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return None
    return origin


def admin_dashboard_reply(message, portal_store, app_url: str | None) -> str | None:
    """Reply with the public archive URL. Never include an admin token or chat GUID."""
    if not _DASHBOARD.search(getattr(message, "text", None) or ""):
        return None
    chat_id = getattr(message, "chat_id", None)
    if not isinstance(chat_id, str) or ";+;" not in chat_id:
        return None
    origin = _hosted_origin(app_url)
    if origin is None or portal_store is None:
        return _UNPUBLISHED
    public_id = portal_store.ensure_group(chat_id)
    url = f"{origin}/{public_id}"
    if _ADMIN_ASK.search(message.text or ""):
        return hosted_page_reply(url, admin=True)
    return hosted_page_reply(url)
