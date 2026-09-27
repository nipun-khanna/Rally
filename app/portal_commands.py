"""Explicit in-chat portal commands for members of an allowlisted group."""

import re

from app.group_admin_commands import hosted_page_reply


_SECTION = r"history|messages|media|photos|attachments|analytics|stats|plans|members|activity"
_ALIASES = {"messages": "history", "photos": "media", "attachments": "media", "stats": "analytics"}


def portal_reply(message, portal_store, app_url: str, *, history_enabled: bool = True,
                 resolve_public_id=None) -> str | None:
    """Return a reply for an addressed portal command, or None for normal Rally work."""
    text = message.text.strip()
    if not re.search(r"\b(portal|page|site|history|messages|media|photos|attachments|analytics|stats|plans|members|activity)\b", text, re.I):
        return None
    chat_id = message.chat_id
    match = re.search(rf"\b(hide|show|turn on|turn off|enable|disable)\s+(?:the\s+)?({_SECTION})\b", text, re.I)
    if match:
        section = _ALIASES.get(match.group(2).lower(), match.group(2).lower())
        visible = match.group(1).lower() in ("show", "turn on", "enable")
        if visible and section in {"history", "media", "analytics"} and not history_enabled:
            return "History reading is disabled globally. Enable it in Rally setup before showing history, media, or analytics; this command has not imported messages."
        portal_store.update_settings(chat_id, sections={section: visible})
        return f"{section.title()} is now {'shown' if visible else 'hidden'} on our page."
    match = re.search(r"\b(?:name|title|rename)\s+(?:(?:the|our|group)\s+)?(?:portal|page|site)\s+(?:to|as)\s+(.+)$", text, re.I)
    if match:
        title = match.group(1).strip().strip(". ")[:80]
        if not title:
            return "Tell me the name to use for our page."
        portal_store.update_settings(chat_id, title=title)
        return f"Our page is now called {title}."
    match = re.search(r"\b(?:set|change)\s+(?:(?:the|our|group)\s+)?(?:portal|page|site)\s+theme\s+to\s+(imessage|midnight|sage)\b", text, re.I)
    if match:
        theme = match.group(1).lower()
        portal_store.update_settings(chat_id, theme=theme)
        return f"Our page theme is now {theme}."
    resolve = resolve_public_id or portal_store.ensure_group
    if re.search(r"\b(?:rotate|replace|reset)\s+(?:the\s+)?(?:portal|page|site)\s+link\b", text, re.I):
        portal_store.rotate_group(chat_id)
        public_id = resolve(chat_id)
        return f"The old page link has been replaced. New link: {app_url.rstrip('/')}/{public_id}"
    if re.search(r"\b(?:link|url|send|open|see|share)\b", text, re.I) or re.search(
            r"\b(?:our|group)\s+(?:portal|page|site)\b", text, re.I):
        public_id = resolve(chat_id)
        return hosted_page_reply(f"{app_url.rstrip('/')}/{public_id}")
    return None
