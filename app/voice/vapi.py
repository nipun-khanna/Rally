"""Bounded Vapi outbound calls using an existing assistant and phone number.

Vapi owns the audio connection. Creating a call is attempted once: a failed
HTTP exchange can still have placed a call, so callers must not retry blindly.
"""

from __future__ import annotations

from contextlib import nullcontext
import re
from uuid import UUID

import httpx


AUTHORIZED_TEST_NUMBER = "+16785991244"
_E164 = re.compile(r"\+[1-9]\d{1,14}\Z")
_API_BASE = "https://api.vapi.ai"
_STATUSES = frozenset({"scheduled", "queued", "ringing", "in-progress", "forwarding", "ended"})


class VapiError(Exception):
    """Safe to show to users; never contains provider response bodies or keys."""


def _valid_call_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


class VapiDialer:
    def __init__(
        self,
        api_key: str,
        assistant_id: str,
        phone_number_id: str,
        *,
        client: httpx.Client | None = None,
    ):
        self.api_key = (api_key or "").strip()
        self.assistant_id = (assistant_id or "").strip()
        self.phone_number_id = (phone_number_id or "").strip()
        self._client = client

    def ready(self) -> bool:
        return bool(self.api_key and self.assistant_id and self.phone_number_id)

    def allows(self, number: str) -> bool:
        return isinstance(number, str) and bool(_E164.fullmatch(number))

    def prepare_call(self, *, to_number: str, assistant_overrides: dict | None = None) -> dict:
        """Build the create-call body. This does not contact Vapi."""
        if not self.allows(to_number):
            raise VapiError("Vapi destination is not authorized")
        if not self.ready():
            raise VapiError("Vapi is not configured")
        payload = {
            "assistantId": self.assistant_id,
            "phoneNumberId": self.phone_number_id,
            "customer": {"number": to_number},
        }
        if assistant_overrides:
            payload["assistantOverrides"] = assistant_overrides
        return payload

    def place_call(self, *, to_number: str, assistant_overrides: dict | None = None) -> dict:
        payload = self.prepare_call(
            to_number=to_number, assistant_overrides=assistant_overrides)
        data = self._request("POST", "/call", payload=payload)
        return {"id": data["id"], "status": data["status"]}

    def get_call(self, call_id: str) -> dict:
        data = self._fetch_call(call_id)
        return {"id": data["id"], "status": data["status"]}

    def get_call_evidence(self, call_id: str) -> dict:
        """Status plus restaurant analysis. Omits recordings, monitor URLs, and secrets."""
        data = self._fetch_call(call_id)
        return {
            "id": data["id"],
            "status": data["status"],
            "structured": _structured_evidence(data),
            "transcript": _transcript_evidence(data),
            "messages": _message_evidence(data),
        }

    def _fetch_call(self, call_id: str) -> dict:
        if not _valid_call_id(call_id):
            raise VapiError("Vapi call ID is invalid")
        if not self.api_key:
            raise VapiError("Vapi is not configured")
        data = self._request("GET", f"/call/{call_id}")
        if data["id"].lower() != call_id.lower():
            raise VapiError("Vapi returned an invalid call ID")
        return data

    def _request(self, method: str, path: str, *, payload: dict | None = None) -> dict:
        # The default HTTPX transport does not retry. Disable redirects even for
        # injected clients so the bearer key never follows a provider redirect.
        context = nullcontext(self._client) if self._client is not None else httpx.Client()
        try:
            with context as client:
                response = client.request(
                    method, _API_BASE + path,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload, timeout=20, follow_redirects=False,
                )
        except httpx.HTTPError:
            message = (
                "Vapi call outcome is unknown; check the dashboard before another attempt"
                if method == "POST" else "Vapi call status could not be retrieved"
            )
            raise VapiError(message) from None
        if not 200 <= response.status_code < 300:
            message = f"Vapi request failed (HTTP {response.status_code})"
            if method == "POST":
                message += "; check the dashboard before another attempt"
            raise VapiError(message)
        try:
            data = response.json()
        except ValueError:
            raise VapiError("Vapi returned an invalid call response") from None
        if not isinstance(data, dict) or not _valid_call_id(data.get("id")):
            raise VapiError("Vapi returned an invalid call ID")
        status = data.get("status")
        if not isinstance(status, str) or status not in _STATUSES:
            raise VapiError("Vapi returned an invalid call status")
        return data


def _structured_evidence(data: dict) -> dict | None:
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    raw = analysis.get("structuredData") if isinstance(analysis.get("structuredData"), dict) else None
    if raw is None:
        artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
        outputs = artifact.get("structuredOutputs")
        if isinstance(outputs, dict):
            for item in outputs.values():
                if isinstance(item, dict) and isinstance(item.get("result"), dict):
                    raw = item["result"]
                    break
    if not isinstance(raw, dict):
        return None
    kept = {}
    for key in ("outcome", "confirmationCode", "confirmation_code", "date", "time",
                "guestName", "venue"):
        value = raw.get(key)
        if isinstance(value, str):
            kept[key] = value.strip()[:80]
    party = raw.get("partySize")
    if isinstance(party, int) and not isinstance(party, bool):
        kept["partySize"] = party
    elif isinstance(party, str) and party.isdigit():
        kept["partySize"] = int(party)
    return kept or None


def _transcript_evidence(data: dict) -> str:
    artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
    for candidate in (data.get("transcript"), artifact.get("transcript")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:2000]
    return ""


_MESSAGE_ROLES = {
    "bot": "assistant", "assistant": "assistant", "ai": "assistant",
    "system": "assistant", "model": "assistant",
    "user": "user", "customer": "user", "restaurant": "user",
    "host": "user", "callee": "user",
}


def _message_text(item: dict) -> str:
    for key in ("message", "text", "content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:400]
    return ""


def _bounded_messages(rows) -> list[dict]:
    kept = []
    if not isinstance(rows, list):
        return kept
    for item in rows:
        if len(kept) >= 40:
            break
        if not isinstance(item, dict):
            continue
        role = _MESSAGE_ROLES.get(str(item.get("role") or "").casefold())
        text = _message_text(item)
        if not role or not text:
            continue
        kept.append({"role": role, "text": text})
    return kept


def _message_evidence(data: dict) -> list[dict]:
    """Role-tagged turns from the call payload. Unlabeled transcript text is omitted."""
    artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
    for rows in (data.get("messages"), artifact.get("messages")):
        kept = _bounded_messages(rows)
        if kept:
            return kept
    return []
