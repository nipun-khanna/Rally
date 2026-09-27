"""Tools Grok Voice may call while talking to a restaurant host."""

from __future__ import annotations

from app.voice.caller import (
    CallResult,
    looks_like_card_number,
    payment_card_for_hold,
    redact_card_digits,
)
from app.voice.tools import VoiceTool, VoiceToolRegistry


def build_reservation_call_tools(caller) -> VoiceToolRegistry:
    registry = VoiceToolRegistry()

    def report_reservation_result(args: dict) -> dict:
        status = args["status"]
        if status not in ("booked", "need_confirm", "failed"):
            return {"ok": False, "reason": "status must be booked, need_confirm, or failed"}
        confirmation = (args.get("confirmation_id") or "").strip() or None
        notes = redact_card_digits(args.get("notes") or "")
        if looks_like_card_number(confirmation) or looks_like_card_number(notes):
            return {"ok": False, "reason": "Do not store or speak card numbers"}
        if status == "booked" and payment_card_for_hold() is not None:
            return {"ok": False, "reason": "Payment cards cannot be invented"}
        dialed = caller.can_dial_pstn()
        result = CallResult(
            status=status,
            transport="twilio" if dialed else "loopback",
            dialed=dialed,
            venue=args.get("venue") or "the restaurant",
            confirmation_id=confirmation,
            notes=notes,
        )
        if hasattr(caller, "last_result"):
            from app.voice.caller import finalize_result
            caller.last_result = finalize_result(result)
        return {"ok": True, "status": caller.last_result.status if caller.last_result else status}

    registry.register(VoiceTool(
        "report_reservation_result",
        "Report the restaurant call outcome after the host clearly confirms, "
        "asks to call back, or refuses. status must be booked, need_confirm, "
        "or failed. Only use booked when the host gave a real confirmation "
        "code on a live phone call. Never invent a confirmation or a card.",
        {"type": "object", "properties": {
            "status": {"type": "string"},
            "confirmation_id": {"type": "string"},
            "notes": {"type": "string"},
            "venue": {"type": "string"},
        }, "required": ["status"]},
        "commitment", report_reservation_result))

    def wait_for_human(args: dict) -> dict:
        reason = redact_card_digits(args.get("reason") or "host needs a person")
        if payment_card_for_hold() is not None:
            return {"ok": False, "reason": "Payment cards cannot be invented"}
        result = CallResult(
            status="waiting_for_human",
            transport="loopback",
            dialed=False,
            venue="the restaurant",
            notes=reason,
        )
        caller.last_result = result
        return {
            "ok": True,
            "status": "waiting_for_human",
            "note": "Do not give a card number. Stop and wait for a person.",
        }

    registry.register(VoiceTool(
        "wait_for_human",
        "Call this immediately if the restaurant asks for a credit card, "
        "deposit, ID photo, or anything a person must provide. Never invent "
        "or speak a card number.",
        {"type": "object", "properties": {"reason": {"type": "string"}},
         "required": ["reason"]},
        "commitment", wait_for_human))

    return registry
