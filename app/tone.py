"""Small local style hint; never sends surrounding messages to web search."""

import re

_CASUAL = re.compile(
    r'\b(yo|bro|lol|lmao|lmfao|nah|yup|wanna|gonna|fr|rn|idk|wtf|shit|fuck|'
    r'ngl|lowkey|mid|dude|ass|bitch|damn|hell|tbh|smh|bet|cap|sus|down bad|'
    r'omfg|bruh|deadass)\b',
    re.I,
)
_FORMAL = re.compile(r'\b(please|thank you|certainly|sincerely|regards|good evening|good morning|would you|could we)\b', re.I)


def group_tone(messages) -> str:
    texts = [m.text for m in messages[-20:] if not m.is_from_rally and m.text.strip()]
    casual = sum(bool(_CASUAL.search(text)) for text in texts)
    formal = sum(bool(_FORMAL.search(text)) for text in texts)
    if casual > formal and casual:
        return 'casual'
    if formal > casual and formal:
        return 'formal'
    return 'neutral'
