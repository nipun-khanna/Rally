"""Formatting shared by outbound message transports."""

import re


_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def remove_rally_signature(text: str) -> str:
    """Return canonical message content without a legacy sender prefix."""
    return re.sub(r"^\s*Rally:\s*", "", text, count=1, flags=re.IGNORECASE)


def add_rally_signature(text: str) -> str:
    """Mark an outbound Rally text with the current temporary sender prefix."""
    body = remove_rally_signature(text)
    parts = []
    cursor = 0
    for match in _URL.finditer(body):
        parts.append(body[cursor:match.start()].lower())
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(body[cursor:].lower())
    return f"Rally: {''.join(parts)}"
