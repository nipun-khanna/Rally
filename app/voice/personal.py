"""Turn a phone transcript into a cleaned report and, when possible, a plan."""

from __future__ import annotations

import re
from datetime import datetime

from app.models import PlanFacts

_FILLER = re.compile(
    r"^(?:thanks?(?:\s+you)?|thank you|bye|goodbye|good bye|all right|alright|"
    r"okay|ok|yeah|yep|yup|yes|no|sure|mm-?hmm|uh-?huh|you(?:'re| are) welcome|"
    r"have a good (?:one|day|night)|got it|cool|sounds good|"
    r"yeah,?\s+it'?s a great time|"
    r"yeah,?\s+now'?s a good time|"
    r"now'?s a good time)\.?$",
    re.I,
)
_GLITCH = re.compile(
    r"\b(?:cut(?:ting|s)?\s+out|cut\s+off|audio|still here|just say anything|"
    r"what the hell|it'?s gone|going to your|going to the side)\b|"
    r"^(?:wait|huh|what|oh|um+|uh+)\b",
    re.I,
)
_LEADING_HEDGE = re.compile(r"^(?:uh+|um+|oh|yeah|okay|yes)[,.\s]+", re.I)
_NEGATE = re.compile(r"\b(?:not|n't|never|no longer)\b", re.I)
_SUBSTANCE = re.compile(
    r"\b(?:tomorrow|today|tonight|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|\d{1,2}(?::\d{2})?\s*(?:am|pm)|schedule|plan|pizza|"
    r"restaurant|mexican|italian|thai|indian|free|book)\b",
    re.I,
)
_CUISINE = re.compile(
    r"\b(mexican|italian|thai|indian|chinese|japanese|korean|pizza|sushi|"
    r"bbq|vegan|vegetarian)\b",
    re.I,
)
_PLACE = re.compile(
    r"\b((?:midtown|downtown|buckhead|inman park|east atlanta)\s*,?\s*"
    r"(?:atlanta)?|atlanta)\b",
    re.I,
)
_TIME = re.compile(
    r"\b(tomorrow|today|tonight|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)?\s*(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
    re.I,
)
_PLAN_ASK = re.compile(
    r"\b(?:find|looking for|schedule|plan|restaurant|pizza|eat|dinner|lunch)\b",
    re.I,
)
_CHEAP = re.compile(r"\b(?:low price|cheap|inexpensive|budget)\b", re.I)


def _is_filler(text: str) -> bool:
    if _FILLER.match(text) or _GLITCH.search(text):
        return True
    parts = [part.strip() for part in re.split(r"[,.]+", text) if part.strip()]
    return bool(parts) and all(_FILLER.match(part) or _GLITCH.search(part) for part in parts)


def _clean_line(text: str) -> str:
    cleaned = text
    while True:
        nxt = _LEADING_HEDGE.sub("", cleaned, count=1).strip(" ,.-")
        if nxt == cleaned:
            break
        cleaned = nxt
    return cleaned


def _callee_lines(evidence) -> list[str]:
    if not isinstance(evidence, dict):
        return []
    lines = []
    for item in evidence.get("messages") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").casefold() != "user":
            continue
        text = _clean_line(" ".join(str(item.get("text") or "").split()))
        if not text or _is_filler(text):
            continue
        if not _SUBSTANCE.search(text) and len(text) < 28:
            continue
        lines.append(text[:240])
    return lines


def _conflicts(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    negated = [line for line in lines if _NEGATE.search(line)]
    if not negated:
        return False
    positives = [line for line in lines if line not in negated]
    return bool(positives)


def facts_from_callee(lines: list[str], name: str = "") -> PlanFacts | None:
    blob = " ".join(lines)
    if not blob or not _PLAN_ASK.search(blob):
        return None
    cuisines = []
    for match in _CUISINE.finditer(blob):
        item = match.group(1).title()
        if item not in cuisines:
            cuisines.append(item)
    place = _PLACE.search(blob)
    location = " ".join((place.group(1) or "").split()).title() if place else None
    if "midtown" in blob.casefold() and "atlanta" in blob.casefold():
        location = "Midtown Atlanta"
    when = _TIME.search(blob)
    day = (when.group(1) or "").lower() if when else ""
    clock = (when.group(2) or "").lower() if when else None
    date = {"today": "today", "tonight": "today", "tomorrow": "tomorrow"}.get(day) or (
        day.title() if day else None)
    cheap = "cheap " if _CHEAP.search(blob) else ""
    cuisine = (cuisines[0].lower() + " ") if cuisines else ""
    activity = "dinner"
    goal = f"{cheap}{cuisine}near {location}" if location else f"{cheap}{cuisine}dinner".strip()
    goal = " ".join(goal.split())
    people = [name.strip()] if name.strip() else []
    return PlanFacts(
        goal=goal, activity=activity, participants=people,
        date=date, time=clock, location=location,
        preferred_cuisines=cuisines, confidence=0.6,
    )


def callee_followup(evidence, name: str = "", purpose: str = "",
                    when: datetime | None = None, timezone: str = "") -> tuple[str, PlanFacts | None]:
    """Cleaned group report plus plan facts when the callee asked to meet."""
    del purpose, when, timezone
    who = (name or "").strip() or "them"
    header = f"The call with {who} ended."
    lines = _callee_lines(evidence)
    if not lines or _conflicts(lines):
        return f"{header} I couldn't verify their answer from the transcript.", None
    facts = facts_from_callee(lines, who if who != "them" else "")
    if facts and facts.activity:
        where = facts.location or "a spot"
        food = (facts.preferred_cuisines[0] if facts.preferred_cuisines else "food")
        when_bit = ""
        if facts.date or facts.time:
            when_bit = f" {facts.date or ''} {facts.time or ''}".strip()
            when_bit = f" {when_bit}" if when_bit else ""
        extra = " Need a day and time before I can put it on the calendar."
        if facts.date and facts.time:
            extra = " Say yes and I'll add a calendar hold — nothing is booked yet."
        body = (
            f"{header} {who} wants {food} near {where}{when_bit}. "
            f"I started a plan in this chat.{extra}"
        )
        return " ".join(body.split()), facts
    quoted = " ".join(lines)
    if len(quoted) > 280:
        quoted = quoted[:277].rsplit(" ", 1)[0] + "…"
    return f"{header} They said: {quoted}", None


def callee_report(evidence, name: str = "", purpose: str = "",
                  when: datetime | None = None, timezone: str = "") -> str:
    body, _facts = callee_followup(
        evidence, name=name, purpose=purpose, when=when, timezone=timezone)
    return body


def availability_report(evidence, name: str, when: datetime, timezone: str) -> str:
    return callee_report(evidence, name=name, purpose="when they are free",
                         when=when, timezone=timezone)
