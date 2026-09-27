"""Mac Phone.app / Continuity / iPhone Mirroring outbound when Twilio is unset.

Only the authorized connectivity-test number can be opened. This never
books a restaurant and never invents a card.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_CONFIRM_APPLESCRIPT = _SCRIPTS / "confirm_phone_call.applescript"
_CLICK_CHIP = _SCRIPTS / "click_call_chip.swift"

AUTHORIZED_TEST_NUMBER = "+17032004231"
PHONE_APP = "Phone"
MIRRORING_APP = "iPhone Mirroring"
METHODS = ("phone", "tel", "facetime-audio", "mirroring", "facetime-new")
DEFAULT_METHODS = ("phone",)


class ContinuityError(Exception):
    pass


def tel_url(e164: str) -> str:
    return f"tel://{e164}"


def facetime_audio_url(e164: str) -> str:
    return f"facetime-audio://{e164}"


def url_for(e164: str, method: str = "phone") -> str:
    if method in {"phone", "tel", "mirroring"}:
        return tel_url(e164)
    if method == "facetime-audio":
        return facetime_audio_url(e164)
    if method == "facetime-new":
        return f"facetime-new:{e164}"
    raise ContinuityError("unsupported Continuity method")


def open_url(url: str) -> None:
    subprocess.run(["/usr/bin/open", url], check=True, timeout=15)


def open_phone_app(url: str) -> None:
    subprocess.run(
        ["/usr/bin/open", "-a", PHONE_APP, url], check=True, timeout=15)


def open_mirroring_then_phone(url: str) -> None:
    subprocess.run(
        ["/usr/bin/open", "-a", MIRRORING_APP], check=True, timeout=15)
    subprocess.run(
        ["/usr/bin/open", "-a", PHONE_APP, url], check=True, timeout=15)


def facetime_new_call(e164: str) -> None:
    """Activate FaceTime, Cmd+N, type the allowlisted digits, press Return."""
    digits = e164[2:] if e164.startswith("+1") else e164.lstrip("+")
    if not digits.isdigit():
        raise ContinuityError("FaceTime new-call needs a numeric destination")
    script = (
        'tell application "FaceTime" to activate\n'
        "delay 1.2\n"
        'tell application "System Events"\n'
        '  tell process "FaceTime"\n'
        "    set frontmost to true\n"
        '    keystroke "n" using command down\n'
        "    delay 0.7\n"
        f'    keystroke "{digits}"\n'
        "    delay 0.4\n"
        "    keystroke return\n"
        "  end tell\n"
        "end tell\n"
    )
    subprocess.run(["/usr/bin/osascript", "-e", script], check=True, timeout=30)


def open_method(method: str, url: str) -> None:
    if method == "phone":
        open_phone_app(url)
        return
    if method == "mirroring":
        open_mirroring_then_phone(url)
        return
    if method == "facetime-new":
        if url.startswith("facetime-new:"):
            facetime_new_call(url.split(":", 1)[1])
            return
        facetime_new_call(AUTHORIZED_TEST_NUMBER)
        return
    open_url(url)


def click_call_chip() -> str:
    """Click the top-right Continuity 'Click to Call' pill with the real pointer."""
    completed = subprocess.run(
        ["/usr/bin/swift", str(_CLICK_CHIP)],
        check=False, capture_output=True, text=True, timeout=25)
    return (completed.stdout or completed.stderr or "").strip()


def confirm_outgoing_call() -> str:
    """Click Call. Live path is the green top-right chip."""
    chip = click_call_chip()
    if chip.startswith("chip-click:"):
        return chip
    completed = subprocess.run(
        ["/usr/bin/osascript", str(_CONFIRM_APPLESCRIPT)],
        check=False, capture_output=True, text=True, timeout=20)
    ax = (completed.stdout or completed.stderr or "").strip()
    if ax.startswith("nc-ui-Call") or ax.startswith("clicked-Call"):
        return ax
    return chip or ax or "no-confirm-button"


class ContinuityDialer:
    def __init__(
        self,
        *,
        opener: Callable[..., None] | None = None,
        confirmer: Callable[[], str] | None = None,
        allowed: frozenset[str] | None = None,
        method: str = "phone",
        methods: Sequence[str] | None = None,
    ):
        self.opener = opener or (lambda method, url: open_method(method, url))
        self.confirmer = confirmer
        self.allowed = allowed if allowed is not None else frozenset({AUTHORIZED_TEST_NUMBER})
        self.method = method if method in METHODS else "phone"
        self.methods = tuple(methods) if methods else DEFAULT_METHODS
        self._injected = opener is not None

    def ready(self) -> bool:
        if self._injected:
            return True
        return sys.platform == "darwin"

    def allows(self, e164: str) -> bool:
        return bool(e164) and e164 in self.allowed

    def place_call(self, *, to_number: str, method: str | None = None) -> dict:
        if not self.ready():
            raise ContinuityError("Continuity dialer is not available")
        if not self.allows(to_number):
            raise ContinuityError("number is not allowlisted for Continuity")
        if to_number != AUTHORIZED_TEST_NUMBER:
            raise ContinuityError("refused: will not call restaurants or other numbers")
        chain = (method,) if method else self.methods
        errors: list[str] = []
        for chosen in chain:
            if chosen not in METHODS:
                continue
            url = url_for(to_number, chosen)
            try:
                try:
                    self.opener(chosen, url)
                except TypeError:
                    self.opener(url)
                clicked = ""
                confirm = self.confirmer or confirm_outgoing_call
                if not self._injected or self.confirmer is not None:
                    if not self._injected:
                        import time
                        time.sleep(0.8)
                    clicked = confirm() or ""
                    if not clicked or clicked in {
                            "no-confirm-button", "return-sent", "no-green-chip"}:
                        import time
                        time.sleep(0.4)
                        clicked = confirm() or clicked
                return {
                    "url": url, "method": chosen, "dialed": True,
                    "confirm": clicked,
                }
            except Exception as exc:
                errors.append(f"{chosen}: {type(exc).__name__}")
        raise ContinuityError(
            "Phone.app / Continuity did not start a call ("
            + "; ".join(errors[:4]) + ")")
