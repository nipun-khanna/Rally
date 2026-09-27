"""Detect image/video asks and keep outbound media prompts/URLs honest."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

import httpx


_INVOKE = re.compile(
    r"^\s*(?:(?:hey|hi|hello|yo|ok|okay|ask)[,\s]+)?@?rally\b[\s,:!\-]*",
    re.I,
)
_IMAGE_INTENT = re.compile(
    r"\b(?:draw|doodle|sketch|paint)\s+(?:me\s+)?(?:a|an|the)\b|"
    r"\b(?:generate|make|create|add|send)\b.{0,40}\b(?:an?\s+)?"
    r"(?:image|picture|pic|pics?|photo|drawing)s?\b|"
    r"\b(?:image|picture|pic|pics?|photo)\s+of\b|"
    r"\bpen\s+pics?\b",
    re.I,
)
_VIDEO_INTENT = re.compile(
    r"\b(?:send|share|post|drop|find|get)\b.{0,40}\b(?:a\s+)?"
    r"(?:video|clip|reel)s?\b|"
    r"\b(?:generate|make|create)\b.{0,40}\bvideo\b|"
    r"\b(?:video|clip|youtube|yt)\s+link\b|"
    r"\b(?:youtube|yt)\s+clip\b|"
    r"\blink\s+to\s+(?:a\s+)?video\b|"
    r"\bvideo\s+of\b",
    re.I,
)
_WANTS_GENERATED_VIDEO = re.compile(
    r"\b(?:generate|make|create|draw)\b.{0,40}\bvideo\b",
    re.I,
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_YT_WATCH = re.compile(
    r"^https://(?:www\.|m\.)?youtube\.com/watch\?(?:[^#]*&)?v=[\w-]{11}\b",
    re.I,
)
_YT_SHORT = re.compile(r"^https://youtu\.be/[\w-]{11}\b", re.I)
_VIMEO = re.compile(r"^https://(?:www\.)?vimeo\.com/\d+\b", re.I)


def looks_like_video_request(text: str) -> bool:
    return bool(isinstance(text, str) and _VIDEO_INTENT.search(text))


def looks_like_image_request(text: str) -> bool:
    if not isinstance(text, str) or looks_like_video_request(text):
        return False
    return bool(_IMAGE_INTENT.search(text))


def wants_generated_video(text: str) -> bool:
    return bool(isinstance(text, str) and _WANTS_GENERATED_VIDEO.search(text))


def _strip_invoke(text: str) -> str:
    return _INVOKE.sub("", text or "", count=1).strip()


def image_prompt(text: str) -> str:
    rest = _strip_invoke(text)
    rest = re.sub(
        r"^(?:please\s+)?(?:can you\s+|could you\s+)?"
        r"(?:generate|make|create|add|send|draw|doodle|sketch|paint)\s+"
        r"(?:me\s+)?(?:an?\s+)?(?:image|picture|pic|pics?|photo|drawing)s?\s*"
        r"(?:of\s+)?",
        "",
        rest,
        flags=re.I,
    ).strip()
    rest = re.sub(r"^pen\s+pics?\s+(?:of\s+)?", "", rest, flags=re.I).strip()
    rest = re.sub(
        r"^(?:please\s+)?(?:draw|doodle|sketch|paint)\s+(?:me\s+)?",
        "",
        rest,
        flags=re.I,
    ).strip()
    return rest or "an image"


def video_prompt(text: str) -> str:
    rest = _strip_invoke(text)
    rest = re.sub(
        r"^(?:please\s+)?(?:can you\s+|could you\s+)?"
        r"(?:generate|make|create|send|share|post|drop|find|get)\s+"
        r"(?:me\s+)?(?:an?\s+)?(?:link\s+to\s+(?:a\s+)?)?"
        r"(?:video|clip|reel|youtube|yt)\s*(?:link\s+)?(?:of\s+|for\s+)?",
        "",
        rest,
        flags=re.I,
    ).strip()
    rest = re.sub(r"^(?:youtube|yt)\s+clip\s+(?:of\s+)?", "", rest, flags=re.I).strip()
    return rest or "a short video"


def media_filename(data: bytes, *, kind: str = "image") -> tuple[str, str]:
    if kind == "video" or data.startswith(b"\x00\x00\x00") or b"ftyp" in data[:16]:
        return "rally.mp4", "video/mp4"
    if data.startswith(b"\x89PNG"):
        return "rally.png", "image/png"
    if data.startswith(b"\xff\xd8"):
        return "rally.jpg", "image/jpeg"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "rally.webp", "image/webp"
    if data.startswith(b"GIF8"):
        return "rally.gif", "image/gif"
    return ("rally.mp4", "video/mp4") if kind == "video" else ("rally.png", "image/png")


def is_watchable_video_url(url: str) -> bool:
    if not isinstance(url, str) or len(url) > 500:
        return False
    cleaned = url.strip().rstrip(").,;")
    parts = urlsplit(cleaned)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            return False
    if "youtube.com" in host and "/results" in parts.path:
        return False
    return bool(_YT_WATCH.match(cleaned) or _YT_SHORT.match(cleaned) or _VIMEO.match(cleaned))


def extract_video_url(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    for match in _URL.finditer(text):
        candidate = match.group(0).rstrip(").,;")
        if is_watchable_video_url(candidate):
            return candidate
    return None


def verify_video_url(url: str, *, timeout: float = 8) -> bool:
    """True only when a known video host confirms the clip exists."""
    if not is_watchable_video_url(url):
        return False
    host = (urlsplit(url).hostname or "").lower()
    if "youtu" in host:
        probe = f"https://www.youtube.com/oembed?format=json&url={url}"
    elif "vimeo.com" in host:
        probe = f"https://vimeo.com/api/oembed.json?url={url}"
    else:
        return False
    try:
        response = httpx.get(probe, timeout=timeout, follow_redirects=True)
        if response.status_code != 200:
            return False
        data = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return False
    return isinstance(data, dict) and bool(data.get("title") or data.get("html"))
