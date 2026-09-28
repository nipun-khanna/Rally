"""Route Grok Voice onto the Phone call without using the Mac mic.

Uplink: BlackHole 2ch is the system input. Phone Video mic = Use System
Setting, so Grok's playback is what the far side hears.

Downlink: Phone plays the far side to real Speakers (even when the HUD
says "using your iPhone"). FaceTime/Phone refuse BlackHole as an output
device, so Grok hears a Core Audio process tap of that speaker mix
instead of a 16ch loopback.
"""

from __future__ import annotations

import array
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PHONE_SPEAKERS = "MacBook Pro Speakers"
PHONE_HEADPHONES = "Rally Headphones"
CALL_PLAYBACK = PHONE_SPEAKERS
GROK_TO_PHONE = "BlackHole 2ch"
PHONE_TO_GROK = "BlackHole 16ch"
_SWITCH = "SwitchAudioSource"


@dataclass(frozen=True)
class AudioRoute:
    grok_input: str
    grok_output: str
    previous_input: str
    previous_output: str


def _switch(*args: str) -> str:
    binary = shutil.which(_SWITCH)
    if not binary:
        return ""
    completed = subprocess.run(
        [binary, *args], check=False, capture_output=True, text=True, timeout=10)
    return (completed.stdout or "").strip()


def cables_ready() -> bool:
    return GROK_TO_PHONE in _switch("-a")


def ensure_headphones() -> str:
    names = _switch("-a")
    if PHONE_HEADPHONES in names:
        return PHONE_HEADPHONES
    script = Path(__file__).resolve().parents[2] / "scripts" / "ensure_rally_call_out.swift"
    if script.is_file():
        subprocess.run(
            ["swift", str(script)], check=False, capture_output=True, text=True, timeout=30)
    names = _switch("-a")
    if PHONE_HEADPHONES in names:
        return PHONE_HEADPHONES
    return PHONE_SPEAKERS


def current_defaults() -> tuple[str, str]:
    return _switch("-c", "-t", "input"), _switch("-c", "-t", "output")


def apply_phone_app_io() -> str:
    """Select and verify Phone's Use System Setting microphone and output."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "set_phone_blackhole.applescript"
    if not script.is_file():
        return "no-script"
    completed = subprocess.run(
        ["osascript", str(script)], check=False, capture_output=True, text=True, timeout=15)
    return (completed.stdout or completed.stderr or "").strip()


def apply_phone_cables() -> AudioRoute | None:
    if not cables_ready():
        return None
    prev_in, prev_out = current_defaults()
    _switch("-t", "input", "-s", GROK_TO_PHONE)
    _switch("-t", "output", "-s", CALL_PLAYBACK)
    phone_io = apply_phone_app_io()
    if phone_io != "phone-io:system-in,system-out":
        print("phone-io-unverified", phone_io, flush=True)
    return AudioRoute(CALL_PLAYBACK, GROK_TO_PHONE, prev_in, prev_out)


def restore_defaults(route: AudioRoute | None) -> None:
    if route is None:
        return
    if route.previous_input:
        _switch("-t", "input", "-s", route.previous_input)
    if route.previous_output:
        _switch("-t", "output", "-s", route.previous_output)


def resample_pcm16(chunk: bytes, src_rate: int, dst_rate: int = 48000) -> bytes:
    if src_rate <= 0 or dst_rate <= 0 or src_rate == dst_rate:
        return chunk
    samples = array.array("h")
    samples.frombytes(chunk[: len(chunk) - (len(chunk) % 2)])
    if not samples:
        return b""
    n_out = max(1, int(round(len(samples) * dst_rate / src_rate)))
    last = len(samples) - 1
    out = array.array("h")
    for index in range(n_out):
        pos = 0.0 if n_out == 1 else index * last / (n_out - 1)
        lo = int(pos)
        hi = min(lo + 1, last)
        frac = pos - lo
        out.append(int(samples[lo] * (1 - frac) + samples[hi] * frac))
    return out.tobytes()


def pcm16_rms(chunk: bytes) -> float:
    if len(chunk) < 2:
        return 0.0
    total = 0
    count = 0
    for i in range(0, len(chunk) - 1, 2):
        sample = int.from_bytes(chunk[i:i + 2], "little", signed=True)
        total += sample * sample
        count += 1
    return (total / count) ** 0.5 if count else 0.0


def gate_noise(chunk: bytes, *, floor: float = 500.0) -> bytes:
    """Drop room-level hiss so Grok VAD does not chase background noise."""
    if pcm16_rms(chunk) < floor:
        return b"\x00" * len(chunk)
    return chunk


def loudest_channel_pcm16(chunk: bytes, channels: int) -> bytes:
    """Keep the BlackHole channel Phone actually wrote, not ch0/average."""
    if channels <= 1:
        return chunk
    width = 2 * channels
    usable = len(chunk) - (len(chunk) % width)
    if usable < width:
        return b""
    samples = array.array("h")
    samples.frombytes(chunk[:usable])
    frames = len(samples) // channels
    energies = [0] * channels
    for i in range(frames):
        base = i * channels
        for channel in range(channels):
            sample = samples[base + channel]
            energies[channel] += sample * sample
    winner = max(range(channels), key=lambda channel: energies[channel])
    out = array.array("h")
    out.extend(samples[i * channels + winner] for i in range(frames))
    return out.tobytes()


def mix_pcm16(*chunks: bytes) -> bytes:
    living = [chunk for chunk in chunks if chunk]
    if not living:
        return b""
    length = max(len(chunk) for chunk in living)
    length -= length % 2
    if length < 2:
        return b""
    acc = array.array("h", b"\x00" * length)
    for chunk in living:
        other = array.array("h")
        other.frombytes(chunk[: len(chunk) - (len(chunk) % 2)])
        for index, sample in enumerate(other):
            if index >= len(acc):
                break
            mixed = acc[index] + sample
            acc[index] = max(-32768, min(32767, mixed))
    return acc.tobytes()


def boost_pcm16(chunk: bytes, gain: float) -> bytes:
    if gain == 1 or len(chunk) < 2:
        return chunk
    samples = array.array("h")
    samples.frombytes(chunk[: len(chunk) - (len(chunk) % 2)])
    for index, sample in enumerate(samples):
        value = int(sample * gain)
        samples[index] = max(-32768, min(32767, value))
    return samples.tobytes()
