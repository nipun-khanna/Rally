"""Twilio PSTN outbound for reservation calls.

Rally places the restaurant call; Twilio streams audio back to
`/voice/call/stream` so Grok Voice can talk. A public HTTPS app URL is
required — Twilio cannot reach 127.0.0.1.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import httpx


class TelcoError(Exception):
    pass


def public_media_base(app_url: str) -> str | None:
    if not app_url or not isinstance(app_url, str):
        return None
    parsed = urlsplit(app_url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def twiml_url_for(app_url: str) -> str:
    base = public_media_base(app_url)
    if not base:
        raise TelcoError("Twilio needs a public HTTPS RALLY_APP_URL")
    return urljoin(base + "/", "voice/call/twiml")


def stream_url_for(app_url: str) -> str:
    base = public_media_base(app_url)
    if not base:
        raise TelcoError("Twilio needs a public HTTPS RALLY_APP_URL")
    host = urlsplit(base).netloc
    return f"wss://{host}/voice/call/stream"


def twiml_connect_stream(stream_url: str) -> str:
    if not stream_url.startswith("wss://"):
        raise TelcoError("Media stream URL must be wss")
    escaped = (
        stream_url.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Say>This is Rally calling to make a reservation.</Say>"
        "<Connect>"
        f'<Stream url="{escaped}"/>'
        "</Connect>"
        "</Response>"
    )


def audio_bridge_ready() -> bool:
    """True only when Twilio media can be forwarded to grok-voice-latest.

    The stream endpoint accepts Twilio today, but it does not yet proxy audio
    to xAI. Keep this false so Rally will not ring a restaurant and sit silent.
    """
    return False


def can_place_pstn_call(dialer, app_url: str, *, destination_phone: str = "") -> bool:
    from app.voice.continuity import AUTHORIZED_TEST_NUMBER
    if destination_phone != AUTHORIZED_TEST_NUMBER:
        return False
    if not audio_bridge_ready():
        return False
    if dialer is None or not getattr(dialer, "ready", lambda: False)():
        return False
    if not destination_phone:
        return False
    try:
        public_media_base(app_url)
        twiml_url_for(app_url)
    except TelcoError:
        return False
    return public_media_base(app_url) is not None


class TwilioDialer:
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.account_sid = (account_sid or "").strip()
        self.auth_token = (auth_token or "").strip()
        self.from_number = (from_number or "").strip()

    def ready(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number)

    def place_call(self, *, to_number: str, twiml_url: str) -> dict:
        from app.voice.continuity import AUTHORIZED_TEST_NUMBER
        if to_number != AUTHORIZED_TEST_NUMBER:
            raise TelcoError("refused: will not call restaurants or other numbers")
        if not self.ready():
            raise TelcoError("Twilio is not configured")
        if not to_number or not twiml_url:
            raise TelcoError("Destination and TwiML URL are required")
        url = (f"https://api.twilio.com/2010-04-01/Accounts/"
               f"{self.account_sid}/Calls.json")
        try:
            response = httpx.post(
                url,
                auth=(self.account_sid, self.auth_token),
                data={"To": to_number, "From": self.from_number, "Url": twiml_url},
                timeout=15,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelcoError("Twilio did not accept the outbound call") from exc
        data = response.json()
        sid = data.get("sid")
        if not isinstance(sid, str) or not sid:
            raise TelcoError("Twilio did not return a call sid")
        return {"sid": sid, "status": data.get("status")}
