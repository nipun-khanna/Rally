"""Read-only operational snapshot for one allowlisted group chat.

This module never reads relationship-DM tables and never returns secret values.
"""

from datetime import datetime, timezone
from urllib.parse import quote

from app.group_turns import REPLY_WINDOW


_SECRET_KEYS = frozenset({
    "webhook_token", "admin_token", "bluebubbles_password", "xai_api_key",
    "google_client_secret", "google_refresh_token", "browser_admin_token",
    "meta_model_api_key", "geoapify_api_key",
})


def _is_group_chat(chat_id: str) -> bool:
    return isinstance(chat_id, str) and ";+;" in chat_id


def _allowed_groups(service, excluded_chat_ids) -> frozenset[str]:
    excluded = excluded_chat_ids or frozenset()
    if callable(excluded):
        excluded = excluded()
    allowed = service.allowed_chat_ids or frozenset()
    return frozenset(chat_id for chat_id in allowed
                     if _is_group_chat(chat_id) and chat_id not in excluded)


def _title(chat_id: str, portal_group: dict | None) -> str:
    if portal_group and portal_group.get("title"):
        return str(portal_group["title"])
    return chat_id.rsplit(";", 1)[-1] or chat_id


def _mask_identity(raw: dict | None) -> dict:
    identity = {}
    for key, value in (raw or {}).items():
        if key in _SECRET_KEYS:
            identity[key] = "configured" if value and value not in ("missing", False) else "missing"
        else:
            identity[key] = value
    return identity


def _portal_identity(portal_store, chat_id: str) -> dict:
    if portal_store is None:
        return {}
    group = portal_store.group_for_chat(chat_id)
    if group is None:
        return {}
    state = portal_store.import_state(chat_id)
    return {
        "portal_public_id": group.get("public_id") or "",
        "portal_title": group.get("title") or "",
        "portal_theme": group.get("theme") or "",
        "portal_sections": dict(group.get("sections") or {}),
        "history_import": {
            "status": state.get("status"),
            "imported_count": state.get("imported_count") or 0,
            "error": state.get("error"),
        },
    }


def _turn_snapshot(group_turns, chat_id: str, now: datetime) -> dict:
    if group_turns is None:
        return {"available": False, "active": False, "opened_by_message_id": "",
                "last_relevant_at": "", "closed": False, "replies_in_window": 0}
    snapshot = {
        "available": True,
        "active": bool(group_turns.active(chat_id, now)),
        "opened_by_message_id": "",
        "last_relevant_at": "",
        "closed": False,
        "replies_in_window": 0,
    }
    try:
        with group_turns._db() as db:
            row = db.execute("SELECT * FROM group_turns WHERE chat_id=?", (chat_id,)).fetchone()
            if row:
                snapshot.update({
                    "opened_by_message_id": row["opened_by_message_id"] or "",
                    "last_relevant_at": row["last_relevant_at"] or "",
                    "closed": bool(row["closed"]),
                })
            cutoff = (now - REPLY_WINDOW).astimezone(timezone.utc).isoformat()
            snapshot["replies_in_window"] = db.execute(
                "SELECT COUNT(*) AS n FROM group_turn_replies WHERE chat_id=? AND sent_at >= ?",
                (chat_id, cutoff),
            ).fetchone()["n"]
    except Exception:
        pass
    return snapshot


def list_admin_groups(service, portal_store=None, *, excluded_chat_ids=frozenset()) -> list[dict]:
    """Return allowlisted group chats Rally may operate in."""
    groups = []
    for chat_id in _allowed_groups(service, excluded_chat_ids):
        portal_group = portal_store.group_for_chat(chat_id) if portal_store else None
        plan = service.store.get_plan(chat_id)
        groups.append({
            "chat_id": chat_id,
            "title": _title(chat_id, portal_group),
            "plan_state": plan.state if plan else "",
            "pending": service.store.pending_count(chat_id),
            "href": "/admin/groups/" + quote(chat_id, safe=""),
        })
    groups.sort(key=lambda item: (item["title"].casefold(), item["chat_id"]))
    return groups


def build_group_admin(service, chat_id: str, *, portal_store=None,
                      excluded_chat_ids=frozenset(), identity=None,
                      now: datetime | None = None) -> dict | None:
    """Assemble one group's operational truth, or None when the chat is off-limits."""
    if chat_id not in _allowed_groups(service, excluded_chat_ids):
        return None
    now = now or datetime.now(timezone.utc)
    portal_group = portal_store.group_for_chat(chat_id) if portal_store else None
    turns = service.group_turns
    messages = []
    for message in service.store.recent_messages(chat_id, limit=40):
        if message.chat_id != chat_id:
            continue
        reaction = turns.last_reaction(message.message_id) if turns else None
        messages.append({
            "message_id": message.message_id,
            "sender_id": message.sender_id,
            "text": message.text,
            "sent_at": message.sent_at.isoformat(),
            "is_from_rally": bool(message.is_from_rally),
            "reaction": reaction or "",
        })
    plan = service.store.get_plan(chat_id)
    plan_view = None
    proposal_view = None
    approval_view = None
    reservation_view = None
    if plan and plan.chat_id == chat_id:
        facts = plan.facts
        plan_view = {
            "id": plan.id, "state": plan.state, "version": plan.version,
            "goal": facts.goal, "activity": facts.activity,
            "date": facts.date, "time": facts.time, "earliest_time": facts.earliest_time,
            "location": facts.location, "participants": list(facts.participants),
            "party_size": facts.party_size, "blockers": list(facts.blockers),
            "confidence": facts.confidence,
            "last_human_at": plan.last_human_at.isoformat(),
            "pending_proposal_id": plan.pending_proposal_id or "",
        }
        proposal = service.store.latest_proposal(plan.id)
        if proposal:
            proposal_view = {
                "id": proposal.id, "venue_name": proposal.venue_name,
                "venue_address": proposal.venue_address, "status": proposal.status,
                "date": proposal.date, "time": proposal.time,
                "party_size": proposal.party_size,
            }
            approval = service.store.approval(proposal.id)
            if approval:
                approval_view = {
                    "sender_id": approval["sender_id"],
                    "message_id": approval["message_id"],
                    "includes_calendar": bool(approval["includes_calendar"]),
                }
            reservation = service.store.reservation(proposal.id)
            if reservation:
                reservation_view = {
                    "confirmation_id": reservation.confirmation_id,
                    "status": reservation.status,
                }
    memory = []
    if service.group_memory is not None:
        try:
            memory = [{
                "key": fact.key, "fact": fact.fact,
                "source_message_id": fact.source_message_id,
                "updated_at": fact.updated_at.isoformat(),
            } for fact in service.group_memory.list_facts(chat_id)]
        except ValueError:
            memory = []
    diagnostics = service.store.pending_diagnostics(chat_id)
    identity_view = {
        "allowlisted": True,
        "chat_id": chat_id,
        **_portal_identity(portal_store, chat_id),
        **_mask_identity(identity),
    }
    return {
        "chat_id": chat_id,
        "title": _title(chat_id, portal_group),
        "identity": identity_view,
        "messages": messages,
        "plan": plan_view,
        "proposal": proposal_view,
        "approval": approval_view,
        "reservation": reservation_view,
        "memory": memory,
        "turn": _turn_snapshot(turns, chat_id, now),
        "reactions": {
            "transport": "configured" if service.react_fn else "missing",
            "recent": [{"message_id": item["message_id"], "reaction": item["reaction"]}
                       for item in messages if item["reaction"]],
        },
        "processing": diagnostics,
        "outbound": service.store.actions_for_chat(chat_id, limit=40),
    }
