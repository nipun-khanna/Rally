"""Formatting shared by outbound message transports."""

import re


def remove_rally_signature(text: str) -> str:
    """Drop the legacy bot-name prefix from text before sending it to a person."""
    return re.sub(r"^\s*Rally:\s*", "", text, count=1, flags=re.IGNORECASE)
