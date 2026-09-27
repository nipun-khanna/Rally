"""One Rally path: allowlisted Phone.app call, click Call, attach Grok Voice."""

from __future__ import annotations


def run_mac_phone_call(*, to_number: str, dialer, voice=None, brief=None) -> dict:
    from app.voice.audio_route import apply_phone_cables, cables_ready
    from app.voice.continuity import AUTHORIZED_TEST_NUMBER, ContinuityError
    if to_number != AUTHORIZED_TEST_NUMBER:
        raise ContinuityError("refused: will not call restaurants or other numbers")
    if (
        voice is not None
        and not getattr(dialer, "_injected", True)
        and cables_ready()
    ):
        apply_phone_cables()
    placed = dialer.place_call(to_number=to_number, method="phone")
    attached = False
    reason = ""
    if voice is not None and placed.get("dialed"):
        try:
            info = voice.start(brief=brief) or {}
            attached = bool(info.get("attached"))
            reason = str(info.get("reason") or "")
        except Exception as exc:
            reason = type(exc).__name__
    placed["voice_attached"] = attached
    placed["voice_reason"] = reason
    return placed
