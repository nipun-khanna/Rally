"""Formatting shared by outbound message transports."""

import re


def remove_rally_signature(text: str) -> str:
    """Return message content without a leading ``Rally:`` sender prefix."""
    current = text
    while True:
        stripped = re.sub(r"^\s*Rally:\s*", "", current, count=1, flags=re.IGNORECASE)
        if stripped == current:
            return current
        current = stripped


def add_rally_signature(text: str) -> str:
    """Format an outbound Rally text without a sender prefix.

    The body keeps its original case, including confirmation codes and other
    identifiers. A legacy ``Rally:`` prefix is removed instead of being sent.
    """
    return remove_rally_signature(text)
