"""Mint short-lived xAI Realtime credentials so the long-lived key never
reaches the browser. See https://docs.x.ai/developers/model-capabilities/audio/ephemeral-tokens
"""

from __future__ import annotations

import httpx


class VoiceSessionError(Exception):
    pass


_INSTRUCTIONS = (
    "You are Rally, a private relationship check-in voice agent for one person. "
    "You help them notice who they are falling behind with and take one concrete "
    "next step. Speak briefly and conversationally. Use list_attention and "
    "get_person to ground every claim in real data; never invent a fact about a "
    "person, a date, or a relationship. If find_hangout_slot reports it is "
    "unavailable, say plainly that calendar availability isn't connected yet -- "
    "do not guess a free time. To send a message or run a plan check, first call "
    "propose_message or nudge_plan to draft it, describe the draft, then only "
    "call confirm_action after the user clearly says to go ahead. Never call "
    "confirm_action on your own initiative."
)


def mint_ephemeral_token(xai_api_key: str, *, expires_after_seconds: int = 1800) -> str:
    if not xai_api_key:
        raise VoiceSessionError('xAI API key is not configured')
    try:
        response = httpx.post(
            'https://api.x.ai/v1/realtime/client_secrets',
            headers={'Authorization': f'Bearer {xai_api_key}', 'Content-Type': 'application/json'},
            json={'expires_after': {'seconds': expires_after_seconds}},
            timeout=15)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise VoiceSessionError('Could not reach xAI to start a voice session') from exc
    data = response.json()
    token = data.get('value') or data.get('client_secret') or data.get('token')
    if not isinstance(token, str) or not token:
        raise VoiceSessionError('xAI did not return a usable ephemeral token')
    return token


def build_session_payload(*, tools: list[dict]) -> dict:
    return {
        'instructions': _INSTRUCTIONS,
        'tools': tools,
        'voice': 'eve',
        'turn_detection': {'type': 'server_vad'},
        'audio': {
            'input': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'transport': 'json'},
            'output': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'transport': 'json'},
        },
    }
