"""Assemble one authorized group portal page from Rally and archive records."""

import logging
from datetime import datetime, timezone
from urllib.parse import quote

from app.portal_search import find_historical_plans


logger = logging.getLogger(__name__)

_STATE_LABELS = {"SPARK": "", "INTEREST": "",
                 "ALIGNMENT": "Picking details", "BLOCKED": "Needs input",
                 "READY": "Ready to book", "EXECUTING": "Booking", "DONE": "Confirmed",
                 "ABANDONED": "Canceled"}


def _human_date(date_str: str, today: "datetime.date") -> str:
    if not date_str:
        return ""
    try:
        value = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return date_str
    delta = (value - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if 0 < delta < 7:
        return value.strftime("%A")
    return value.strftime("%b %-d")


def _human_time(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        return value
    return parsed.strftime("%-I:%M %p")


def build_portal_data(service, portal_store, group: dict, *, before: str | None = None,
                      old_plan_query: str | None = None, owner_name: str = "") -> dict:
    chat_id = group["chat_id"]
    group_id = group["public_id"]
    raw_messages = portal_store.list_messages(chat_id, before=before, limit=100)
    labels = {m["sender_id"]: m["display_name"] for m in portal_store.members(chat_id)}
    labels.setdefault("local-imessage-account", owner_name.strip() or "You")
    messages = [{"sender": labels.get(m["sender_id"], m["sender_id"]),
                 "timestamp": m["sent_at"], "text": m["text"],
                 "reactions": [{"sender": labels.get(r["sender_id"], r["sender_id"]),
                                "type": r["reaction_type"]} for r in m["reactions"]],
                 "attachments": [{"name": a["filename"],
                    "url": f"/{quote(group_id)}/media/{quote(a['attachment_id'], safe='')}",
                    "available": a["status"] == "available", "mime": a["mime_type"]}
                    for a in m["attachments"]]} for m in reversed(raw_messages)]
    plans = []
    today = datetime.now(timezone.utc).date().isoformat()
    for plan in service.store.plans_for_chat(chat_id):
        if plan.facts.date and plan.facts.date < today and plan.state == "DONE":
            continue
        details = []
        if plan.state == "ABANDONED":
            details.append("Canceled in the group chat.")
        proposal = service.store.latest_proposal(plan.id)
        venue = None
        if proposal:
            venue = proposal.venue_name
            details.append(f"Proposed {proposal.venue_name} for {proposal.date} at {proposal.time} ({proposal.status}).")
            reservation = service.store.reservation(proposal.id)
            if reservation:
                details.append(f"Demo reservation {reservation.status}: {reservation.confirmation_id}.")
            calendar = service.store.calendar_result(proposal.id)
            if calendar:
                details.append(f"Calendar {calendar['status']}.")
        needs = []
        if not plan.facts.time:
            needs.append("a time")
        if not (venue or plan.facts.location):
            needs.append("a place")
        today_date = datetime.now(timezone.utc).date()
        plans.append({"title": plan.facts.goal or plan.facts.activity or "Group plan",
                      "state": _STATE_LABELS.get(plan.state, plan.state.title()),
                      "date": plan.facts.date or "", "date_label": _human_date(plan.facts.date or "", today_date),
                      "time": plan.facts.time or "", "time_label": _human_time(plan.facts.time or ""),
                      "location": venue or plan.facts.location or "",
                      "party_size": plan.facts.party_size,
                      "needs": " and ".join(needs), "details": details})
    plans.sort(key=lambda item: (item["date"] == "", item["date"]))
    actions = service.store.actions_for_chat(chat_id)
    counts = portal_store.analytics(chat_id)
    for sender in counts["by_member"]:
        name = labels.get(sender["sender_id"], sender["display_name"])
        labels[sender["sender_id"]] = name
    top_count = counts["by_member"][0]["message_count"] if counts["by_member"] else 0
    member_stats = [{"name": labels.get(m["sender_id"], m["display_name"]),
                     "count": m["message_count"],
                     "pct": round(100 * m["message_count"] / top_count) if top_count else 0}
                    for m in counts["by_member"]]
    highlights = {"Total messages": counts["message_count"],
                  "Shared media": counts["attachment_count"]}
    if counts["by_member"]:
        highlights["Most talkative"] = labels.get(counts["by_member"][0]["sender_id"], counts["by_member"][0]["display_name"])
        highlights["Quietest"] = labels.get(counts["by_member"][-1]["sender_id"], counts["by_member"][-1]["display_name"])
    if counts["laughs_received"]:
        winner = counts["laughs_received"][0]
        highlights["Funniest"] = labels.get(winner["sender_id"], winner["sender_id"])
    if counts["reactions_received"]:
        winner = counts["reactions_received"][0]
        highlights["Most reactions"] = labels.get(winner["sender_id"], winner["sender_id"])
    if counts["busiest_day"]:
        try:
            day = datetime.strptime(counts["busiest_day"]["day"], "%Y-%m-%d")
            highlights["Busiest day"] = day.strftime("%b %-d")
        except ValueError:
            pass
    analytics = highlights
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
    return {"title": group["title"] or "Group chat", "group_id": group_id, "members": list(labels.values()),
            "theme": group["theme"], "messages": messages, "plans": plans,
            "analytics": analytics, "member_stats": member_stats, "actions": actions,
            "import_status": {"state": status["status"], "imported": status["imported_count"]},
            "settings": group["sections"], "historical_results": historical_results,
            "historical_query": old_plan_query, "historical_error": historical_error,
            "older_url": older_url}


_CATEGORY_LABELS = {"food": "Food", "dietary": "Dietary", "activities": "Activities",
                    "personality": "Personality", "dates": "Dates", "places": "Places",
                    "gifts": "Gift ideas", "likes": "Likes", "dislikes": "Not into",
                    "other": "Other"}


def build_knowledge_data(portal_store, knowledge_store, group: dict, *, owner_name: str = "",
                         overview: dict | None = None) -> dict:
    """People-first view of the group KB. Never includes message ids or phone numbers."""
    from app.knowledge import CATEGORIES, GROUP_SUBJECT
    chat_id = group["chat_id"]
    names = {m["sender_id"]: m["display_name"] for m in portal_store.members(chat_id)}
    names.setdefault("local-imessage-account", owner_name.strip() or "You")
    by_subject: dict[str, dict[str, list[str]]] = {}
    for fact in knowledge_store.facts(chat_id):
        by_subject.setdefault(fact["subject_id"], {}).setdefault(fact["category"], []).append(fact["fact"])

    def grouped(subject: str) -> list[dict]:
        cats = by_subject.get(subject, {})
        return [{"label": _CATEGORY_LABELS[c], "facts": cats[c]} for c in CATEGORIES if cats.get(c)]

    people = [{"name": names[s], "sections": grouped(s)}
              for s in sorted((s for s in by_subject if s in names), key=lambda s: names[s].casefold())]
    links = [{"a": names.get(l["member_a"]), "b": names.get(l["member_b"]), "shared": l["shared"]}
             for l in knowledge_store.links(chat_id)
             if l["member_a"] in names and l["member_b"] in names]
    overview = overview or {}
    return {"title": group["title"] or "Group chat", "group_id": group["public_id"],
            "people": people, "group": grouped(GROUP_SUBJECT), "links": links,
            "members": sorted(set(names.values()), key=str.casefold),
            "analytics": overview.get("analytics") or {},
            "plans": [{k: p.get(k) for k in ("title", "date_label", "time_label", "location")}
                      for p in overview.get("plans") or []]}
