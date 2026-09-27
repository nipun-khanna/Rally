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


REVIVAL_COOLDOWN = timedelta(minutes=15)


def eligible_for_intervention(plan: Plan, now: datetime, stall_minutes: int) -> bool:
    return (
        plan.state == "BLOCKED"
        and len(set(plan.facts.participants)) >= 2
        and bool(plan.facts.blockers)
        and plan.pending_proposal_id is None
        and plan.last_intervention_version != plan.version
        and now - plan.last_human_at >= timedelta(minutes=stall_minutes)
    )


def unfinished_plan(plan: Plan | None) -> bool:
    return bool(
        plan
        and plan.state not in ("DONE", "ABANDONED", "READY", "EXECUTING")
        and (plan.facts.activity or plan.facts.goal)
        and plan.pending_proposal_id is None
    )


def eligible_for_revival(
    plan: Plan,
    now: datetime,
    *,
    last_rally_at: datetime | None = None,
    incoming_stall: bool = False,
    cooldown: timedelta = REVIVAL_COOLDOWN,
) -> bool:
    """One unsolicited revival for an unfinished plan, after cooldown or a stall signal."""
    if not unfinished_plan(plan) or plan.last_intervention_version == plan.version:
        return False
    if incoming_stall:
        return True
    if last_rally_at is not None and now - last_rally_at < cooldown:
        return False
    return now - plan.last_human_at >= cooldown


def valid_approval(text: str) -> bool:
    return bool(re.fullmatch(
        r"\s*(?:yes[, ]+|please\s+)?(?:book it|make (?:the )?reservation|reserve it)"
        r"(?:\s+and\s+add\s+(?:a\s+)?calendar event)?[.!\s]*", text, re.I))


def explicitly_addresses_rally(text: str) -> bool:
    """Recognize a plain-text call to Rally without reacting to incidental mentions."""
    return bool(re.match(
        r"^\s*(?:(?:hey|hi|hello|yo|ok|okay|ask)[,\s]+)?@?rally\b",
        text, re.I))


def valid_calendar_approval(text: str) -> bool:
    return bool(valid_approval(text) and re.search(
        r"\band\s+add\s+(?:a\s+)?calendar event\b", text, re.I))
