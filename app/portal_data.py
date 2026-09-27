"""Assemble one authorized group portal page from Rally and archive records."""

import logging
from datetime import datetime, timezone
from urllib.parse import quote

from app.portal_search import find_historical_plans


logger = logging.getLogger(__name__)


def build_portal_data(service, portal_store, group: dict, *, before: str | None = None,
                      old_plan_query: str | None = None) -> dict:
    chat_id = group["chat_id"]
    group_id = group["public_id"]
    raw_messages = portal_store.list_messages(chat_id, before=before, limit=100)
    labels = {m["sender_id"]: m["display_name"] for m in portal_store.members(chat_id)}
    labels.setdefault("local-imessage-account", "You")
    messages = [{"sender": labels.get(m["sender_id"], m["sender_id"]),
                 "timestamp": m["sent_at"], "text": m["text"],
                 "reactions": [{"sender": labels.get(r["sender_id"], r["sender_id"]),
                                "type": r["reaction_type"]} for r in m["reactions"]],
                 "attachments": [{"name": a["filename"],
                    "url": f"/{quote(group_id)}/media/{quote(a['attachment_id'], safe='')}",
                    "available": a["status"] == "available", "mime": a["mime_type"]}
                    for a in m["attachments"]]} for m in reversed(raw_messages)]
    plans = []
    for plan in service.store.plans_for_chat(chat_id):
        details = []
        facts = plan.facts
        if facts.location:
            details.append(f"Near {facts.location}.")
        if facts.preferred_cuisines:
            details.append("Looking for " + ", ".join(facts.preferred_cuisines) + ".")
        if facts.time:
            details.append(f"At {facts.time}.")
        if facts.party_size:
            details.append(f"Party of {facts.party_size}.")
        proposal = service.store.latest_proposal(plan.id)
        if proposal:
            details.append(f"Proposed {proposal.venue_name} for {proposal.date} at {proposal.time} ({proposal.status}).")
            reservation = service.store.reservation(proposal.id)
            if reservation:
                details.append(f"Demo reservation {reservation.status}: {reservation.confirmation_id}.")
            calendar = service.store.calendar_result(proposal.id)
            if calendar:
                details.append(f"Calendar {calendar['status']}.")
        plans.append({"title": plan.facts.goal or plan.facts.activity or "Group plan",
                      "state": plan.state, "date": plan.facts.date or "",
                      "details": details})
    actions = service.store.actions_for_chat(chat_id)
    counts = portal_store.analytics(chat_id)
    analytics = {"Messages": counts["message_count"],
                 "Shared media": counts["attachment_count"]}
    for sender in counts["by_member"]:
        name = labels.get(sender["sender_id"], sender["display_name"])
        labels[sender["sender_id"]] = name
        analytics[f"{name} texts"] = sender["message_count"]
    if counts["by_member"]:
        analytics["Most texts"] = labels[counts["by_member"][0]["sender_id"]]
        analytics["Fewest texts"] = labels[counts["by_member"][-1]["sender_id"]]
    if counts["laughs_received"]:
        winner = counts["laughs_received"][0]
        analytics["Funniest (by laughs)"] = labels.get(winner["sender_id"], winner["sender_id"])
    else:
        analytics["Funniest (by laughs)"] = "No laugh reactions yet"
    historical_results = []
    historical_error = None
    if old_plan_query and group["sections"].get("plans", True) and group["sections"].get("history", True):
        try:
            query = old_plan_query.strip().lower()
            if not 3 <= len(query) <= 200:
                historical_error = "Ask a question between 3 and 200 characters."
            else:
                cached = portal_store.cached_historical_search(chat_id, query)
                if cached is not None:
                    historical_results = cached
                elif not portal_store.consume_search_quota(
                        chat_id, datetime.now(timezone.utc).date().isoformat()):
                    historical_error = "Past plan search has reached today's group limit."
                else:
                    candidates = portal_store.historical_candidates(chat_id, query)
                    historical_results = find_historical_plans(query, candidates)
                    portal_store.save_historical_search(chat_id, query, historical_results)
        except Exception:
            logger.exception("Historical plan search failed")
            historical_error = "Past plan search is unavailable right now."
    status = portal_store.import_state(chat_id)
    older_url = None
    if len(raw_messages) == 100:
        cursor = raw_messages[-1]["sent_at"] + "|" + raw_messages[-1]["message_id"]
        older_url = f"/{quote(group_id)}?before={quote(cursor, safe='')}"
    return {"title": group["title"] or "Group chat", "members": list(labels.values()),
            "theme": group["theme"], "messages": messages, "plans": plans,
            "analytics": analytics, "actions": actions,
            "import_status": {"state": status["status"], "imported": status["imported_count"]},
            "settings": group["sections"], "historical_results": historical_results,
            "historical_query": old_plan_query, "historical_error": historical_error,
            "older_url": older_url}
