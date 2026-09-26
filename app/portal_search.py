"""Local, evidence-backed lookup for plans mentioned in older messages."""

import re


PLAN_WORDS = re.compile(
    r"\b(plan|dinner|lunch|brunch|meet|trip|movie|party|concert|reservation|book|going|tomorrow|weekend)\b",
    re.I,
)
STOP_WORDS = {"what", "were", "the", "our", "old", "past", "plans", "plan", "show", "find", "from", "about"}


def find_historical_plans(query: str, candidates: list[dict]) -> list[dict]:
    """Return possible plan mentions with evidence; never claim group agreement."""
    terms = [term for term in re.findall(r"[\w']+", query.lower())
             if len(term) > 2 and term not in STOP_WORDS]
    findings = []
    seen = set()
    for message in candidates:
        body = message["text"].strip()
        if not body or not PLAN_WORDS.search(body):
            continue
        if terms and not any(term in body.lower() for term in terms):
            continue
        day = message["sent_at"][:10]
        key = (day, body[:80].lower())
        if key in seen:
            continue
        seen.add(key)
        findings.append({
            "title": f"Possible plan · {day}",
            "summary": "This older message mentions a possible plan. Check the conversation for what the group agreed to.",
            "evidence": [message],
        })
        if len(findings) == 8:
            break
    return findings
