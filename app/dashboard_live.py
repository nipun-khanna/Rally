"""Mint a chat-scoped public dashboard from the live plan and thread.

The public id is an opaque bearer link. Generation never reads another chat's
rows, and it never includes admin tokens.
"""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlsplit

from app.portal_data import build_portal_data


def vercel_project_from_url(app_url: str | None) -> str | None:
    """Vercel CLI project name is the first label of *.vercel.app."""
    if not isinstance(app_url, str) or not app_url.strip():
        return None
    host = (urlsplit(app_url.strip()).hostname or "").casefold()
    suffix = ".vercel.app"
    if not host.endswith(suffix):
        return None
    name = host[: -len(suffix)]
    if not name or "." in name:
        return None
    return name


def _hosted_origin(app_url: str | None) -> str:
    if not isinstance(app_url, str) or not app_url.strip():
        raise ValueError("Hosted archive URL is required")
    origin = app_url.strip().rstrip("/")
    host = (urlsplit(origin).hostname or "").casefold()
    if host in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Hosted archive URL is required")
    return origin


def sync_live_context(store, portal_store, chat_id: str) -> str:
    """Copy this chat's current thread into the public archive tables."""
    public_id = portal_store.ensure_group(chat_id)
    rows = []
    for message in store.recent_messages(chat_id, 100):
        sender = message.sender_id or "unknown"
        portal_store.set_member(chat_id, sender, sender)
        rows.append({
            "message_id": message.message_id,
            "sender_id": sender,
            "text": message.text or "",
            "sent_at": message.sent_at,
            "is_from_me": sender == "local-imessage-account",
        })
    if rows:
        portal_store.upsert_messages(chat_id, rows)
    return public_id


def lookup_dashboard(store, portal_store, public_id: str) -> dict | None:
    """Return the live snapshot for an exact public id, or None."""
    if not isinstance(public_id, str) or not public_id or public_id != public_id.strip():
        return None
    group = portal_store.get_group(public_id)
    if group is None:
        return None
    service = SimpleNamespace(store=store)
    snapshot = build_portal_data(service, portal_store, group)
    snapshot["public_id"] = public_id
    snapshot["chat_id"] = group["chat_id"]
    return snapshot


def generate_dashboard(store, portal_store, chat_id: str, *, app_url: str,
                       allowed_chat_ids, excluded_chat_ids=(), publisher=None) -> dict:
    """Upsert this chat's live plan/thread, then return the hosted URL."""
    allowed = frozenset(allowed_chat_ids or ())
    excluded = set(excluded_chat_ids or ())
    if not isinstance(chat_id, str) or chat_id not in allowed or chat_id in excluded:
        raise PermissionError("Chat is not allowed to publish a dashboard")
    origin = _hosted_origin(app_url)
    public_id = sync_live_context(store, portal_store, chat_id)
    if publisher is not None:
        publisher(chat_id)
    snapshot = lookup_dashboard(store, portal_store, public_id)
    return {"public_id": public_id, "url": f"{origin}/{public_id}", "snapshot": snapshot}
