import re
from datetime import datetime, timedelta

from app.models import Plan, PlanFacts


STATES = ("SPARK", "INTEREST", "ALIGNMENT", "BLOCKED", "READY", "EXECUTING", "DONE", "ABANDONED")
ACTIONS = ("WAIT", "NUDGE", "ASK", "PROPOSE", "ACT")


def plan_state(facts: PlanFacts, has_proposal: bool) -> str:
    if facts.abandoned:
        return "ABANDONED"
    if has_proposal:
        return "READY"
    if len(set(facts.participants)) < 2:
        return "SPARK"
    if facts.blockers:
        return "BLOCKED"
    if facts.date or facts.location or facts.time:
        return "ALIGNMENT"
    return "INTEREST"


def eligible_for_intervention(plan: Plan, now: datetime, stall_minutes: int) -> bool:
    return (
        plan.state == "BLOCKED"
        and len(set(plan.facts.participants)) >= 2
        and bool(plan.facts.blockers)
        and plan.pending_proposal_id is None
        and plan.last_intervention_version != plan.version
        and now - plan.last_human_at >= timedelta(minutes=stall_minutes)
    )


def valid_approval(text: str) -> bool:
    return bool(re.fullmatch(
        r"\s*(?:yes[, ]+|please\s+)?(?:book it|make (?:the )?reservation|reserve it)"
        r"(?:\s+and\s+add\s+(?:a\s+)?calendar event)?[.!\s]*", text, re.I))


def explicitly_addresses_rally(text: str) -> bool:
    """Recognize a plain-text call to Rally without reacting to incidental mentions."""
    match = re.match(r"^\s*(?:(hey|hi|hello|yo|ok|okay)[,\s]+)?@?rally\b(.*)$",
                     text, re.I | re.S)
    if not match:
        return False
    rest = match.group(2).lstrip()
    if match.group(1):
        return True
    if rest.startswith((",", ":", "?", "!", "-")):
        return True
    return bool(re.match(
        r"(?:can|could|would|will|what|when|where|why|how|who|do|does|did|"
        r"should|please|help|find|suggest|tell|recap|summarize|update|"
        r"remind|book|plan|give|show|any)\b", rest, re.I))


def valid_calendar_approval(text: str) -> bool:
    return bool(valid_approval(text) and re.search(
        r"\band\s+add\s+(?:a\s+)?calendar event\b", text, re.I))
