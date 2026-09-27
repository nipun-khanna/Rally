"""Local gates for group conversation safety and forget commands."""

from __future__ import annotations

import re

from app.policy import explicitly_addresses_rally


_CRIME_THING = (
    r"(?:car|wallet|credit card|identity|gun|bike|catalytic|bank|store|house|"
    r"passport|ssn|account|password)"
)
_FACILITATION = re.compile(
    r"\b(?:how (?:do i|to|can (?:i|we)|would i)\b.{0,80}\b(?:"
    r"steal (?:a |the |from (?:a |the )?)?" + _CRIME_THING + r"|"
    r"shoplift|burgle|"
    r"rob (?:a |the )?(?:bank|store|person|house|car)|"
    r"make (?:a )?(?:bomb|explosive|weapon|bioweapon)|"
    r"cook (?:meth|fentanyl)|buy (?:illegal )?drugs?|"
    r"hack(?:ing)? into|"
    r"forge (?:a )?(?:passport|id|check|document)|counterfeit|"
    r"bypass (?:security|a lock)|"
    r"synthesize (?:ricin|anthrax|sarin)|make (?:a )?nerve agent)|"
    r"help me (?:steal (?:a |the )?" + _CRIME_THING + r"|rob (?:a |the )?(?:bank|store)|"
    r"hack into|forge|make (?:a )?(?:bomb|bioweapon))|"
    r"(?:write|give) me (?:a )?(?:ransomware|phishing) (?:kit|script|email)|"
    r"(?:child (?:porn|pornography)|csam))\b",
    re.I | re.S,
)
_FORGET = re.compile(
    r"^\s*(?:(?:hey|hi|hello|yo|ok|okay)[,\s]+)?@?rally\b[\s,:!\-]*"
    r"forget(?:\s+(.*))?$",
    re.I | re.S,
)
_ALL = re.compile(r"^\s*(?:all|everything|that|it)?\s*$", re.I)


def illegal_assistance_request(text: str) -> bool:
    """True for actionable requests to facilitate wrongdoing."""
    if not isinstance(text, str) or not text.strip():
        return False
    return bool(_FACILITATION.search(text))


def parse_forget_command(text: str) -> str | None:
    """Return '' to forget the group, a fact key, or None if this is not a forget command."""
    if not isinstance(text, str) or not explicitly_addresses_rally(text):
        return None
    match = _FORGET.match(text.strip())
    if not match:
        return None
    rest = (match.group(1) or "").strip()
    if _ALL.match(rest):
        return ""
    key = re.sub(r"[^\w.:-]+", ".", rest.casefold()).strip(".")
    return key or ""


def forget_phrase(text: str) -> str:
    """Original forget tail, used to match stored fact text exactly."""
    if not isinstance(text, str):
        return ""
    match = _FORGET.match(text.strip())
    if not match:
        return ""
    return (match.group(1) or "").strip()


def refusal_text() -> str:
    return "I can't help with that."
