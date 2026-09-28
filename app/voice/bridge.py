"""Local Grok Voice: mouth on BlackHole 2ch, ears on a speaker process tap."""

from __future__ import annotations

import asyncio
import base64
import json
import multiprocessing
import os
import queue
import select
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from app.voice.audio_route import (
    GROK_TO_PHONE,
    PHONE_TO_GROK,
    apply_phone_cables,
    cables_ready,
    loudest_channel_pcm16,
    pcm16_rms,
    resample_pcm16,
)
from app.voice.session import build_reservation_session_payload

_RATE = 48000
_BLOCK = 4800
_OUT_CHANNELS = 2


def _stereo_from_mono(chunk: bytes) -> bytes:
    if len(chunk) < 2:
        return chunk
    return b"".join(chunk[i:i + 2] * 2 for i in range(0, len(chunk) - 1, 2))


def take_playback_bytes(
    leftover: bytearray, frames: int, pull, *, channels: int = _OUT_CHANNELS
) -> bytes:
    """Fill a PortAudio output callback without blocking speaker.write()."""
    needed = frames * channels * 2
    while len(leftover) < needed:
        chunk = pull()
        if not chunk:
            break
        leftover.extend(_stereo_from_mono(chunk))
    if len(leftover) >= needed:
        out = bytes(leftover[:needed])
        del leftover[:needed]
        return out
    padded = bytes(leftover) + b"\x00" * (needed - len(leftover))
    leftover.clear()
    return padded


def _device_input_channels(name: str, fallback: int = 2) -> int:
    import sounddevice as sd
    for device in sd.query_devices():
        if device.get("name") == name and int(device.get("max_input_channels") or 0) > 0:
            return int(device["max_input_channels"])
    return fallback


def pump_process_tap(
    chunks: Iterable[bytes], incoming, speaking, stop, *, chunk_bytes: int = 9600,
) -> None:
    buf = bytearray()
    for piece in chunks:
        if stop.is_set():
            break
        buf.extend(piece)
        while len(buf) >= chunk_bytes:
            call = bytes(buf[:chunk_bytes])
            del buf[:chunk_bytes]
            if speaking.value:
                continue
            try:
                incoming.put_nowait(call)
            except Exception:
                pass
    if buf and not stop.is_set() and not speaking.value:
        try:
            incoming.put_nowait(bytes(buf))
        except Exception:
            pass


def _tap_script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "tap_system_out.swift"


def capture_process_tap(incoming, speaking, stop) -> bool:
    script = _tap_script()
    if not script.is_file():
        return False
    proc = subprocess.Popen(
        ["swift", str(script), "--exclude-pid", str(os.getpid())],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    src_rate = {"hz": _RATE}
    ready = threading.Event()

    def drain_err():
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace")
            print(line.rstrip(), flush=True)
            parts = line.split()
            if parts[:1] == ["@RATE"] and len(parts) > 1:
                try:
                    src_rate["hz"] = int(parts[1])
                except ValueError:
                    pass
            if line.startswith("@READY"):
                ready.set()

    stderr_thread = threading.Thread(target=drain_err, daemon=True)
    stderr_thread.start()

    def chunks():
        hz = src_rate["hz"]
        want = max(2, int(hz * 0.1) * 2)
        last = time.monotonic()
        while not stop.is_set():
            if not select.select([proc.stdout], [], [], 0.1)[0]:
                continue
            data = os.read(proc.stdout.fileno(), want)
            if not data:
                break
            if hz != _RATE:
                data = resample_pcm16(data, hz, _RATE)
            now = time.monotonic()
            if now - last >= 2:
                print("call-tap-rms", round(pcm16_rms(data), 1), "process-tap", flush=True)
                last = now
            yield data

    try:
        deadline = time.monotonic() + 60
        while not ready.is_set():
            if stop.is_set():
                return True
            if proc.poll() is not None or time.monotonic() >= deadline:
                return False
            ready.wait(0.1)
        if stop.is_set():
            return True
        if proc.poll() is not None or proc.stdout is None:
            return False
        print("capture-started", "process-tap", flush=True)
        pump_process_tap(chunks(), incoming, speaking, stop)
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        stderr_thread.join(timeout=2)
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()
    return True


def capture_call_tap(device: str, channels: int, incoming, speaking, stop) -> None:
    """Hear Phone far-end from Speakers via Core Audio tap; BlackHole is fallback."""
    if capture_process_tap(incoming, speaking, stop):
        return
    import sounddevice as sd
    last = time.monotonic()

    def on_call_audio(indata, frames, time_info, status):
        call = loudest_channel_pcm16(bytes(indata), channels)
        now = time.monotonic()
        nonlocal last
        if now - last >= 2:
            print("call-tap-rms", round(pcm16_rms(call), 1), "ch", channels, flush=True)
            last = now
        if speaking.value:
            return
        try:
            incoming.put_nowait(call)
        except Exception:
            pass

    stream = sd.RawInputStream(
        samplerate=_RATE, channels=channels, dtype="int16",
        blocksize=_BLOCK, callback=on_call_audio, device=device)
    stream.start()
    print("capture-started", device, flush=True)
    try:
        stop.wait()
    finally:
        stream.stop()
        stream.close()


def play_call_mic(device: str, outgoing, speaking, stop) -> None:
    """Own process: one PortAudio output stream on BlackHole."""
    import sounddevice as sd
    leftover = bytearray()

    def pull():
        try:
            return outgoing.get_nowait()
        except Exception:
            return b""

    def on_speak(outdata, frames, time_info, status):
        data = take_playback_bytes(leftover, frames, pull)
        speaking.value = any(b != 0 for b in data)
        view = memoryview(outdata).cast("B")
        nbytes = min(len(view), len(data))
        if nbytes:
            view[:nbytes] = data[:nbytes]
        if nbytes < len(view):
            view[nbytes:] = b"\x00" * (len(view) - nbytes)

    stream = sd.RawOutputStream(
        samplerate=_RATE, channels=_OUT_CHANNELS, dtype="int16",
        blocksize=_BLOCK, callback=on_speak, device=device)
    stream.start()
    print("playback-started", device, flush=True)
    try:
        stop.wait()
    finally:
        stream.stop()
        stream.close()


def local_voice_ready(api_key: str) -> bool:
    return bool(api_key)


class LocalGrokVoice:
    def __init__(
        self,
        api_key: str = "",
        *,
        model: str = "grok-voice-latest",
        starter: Callable[..., dict] | None = None,
        tools: list[dict] | None = None,
    ):
        self.api_key = (api_key or "").strip()
        self.model = model or "grok-voice-latest"
        self._starter = starter
        self.tools = tools or []

    def start(self, brief: dict | None = None) -> dict:
        if self._starter is not None:
            return self._starter(brief) or {}
        if not local_voice_ready(self.api_key):
            return {"attached": False, "reason": "no xai key"}
        if not cables_ready():
            return {"attached": False, "reason": "BlackHole cables missing"}
        try:
            import sounddevice  # noqa: F401
            import websockets  # noqa: F401
        except ImportError as exc:
            return {"attached": False, "reason": f"missing {exc.name}"}
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        watcher = root / "scripts" / "watch_rally_voice.sh"
        log = Path("/tmp/rally-grok-voice.log")
        subprocess.Popen(
            ["/bin/bash", str(watcher)],
            cwd=str(root),
            start_new_session=True,
            stdout=log.open("ab"),
            stderr=subprocess.STDOUT,
        )
        return {"attached": True}

    def _run(self, brief: dict | None) -> None:
        asyncio.run(self._session(brief))

    async def _session(self, brief: dict | None) -> None:
        import websockets

        apply_phone_cables()
        print("cables", "in", GROK_TO_PHONE, "out", "speakers", "hear", "process-tap", flush=True)
        ctx = multiprocessing.get_context("spawn")
        incoming = ctx.Queue(maxsize=32)
        outgoing = ctx.Queue(maxsize=64)
        speaking = ctx.Value("b", False)
        stop = ctx.Event()
        channels = _device_input_channels(PHONE_TO_GROK, 2)
        capture = ctx.Process(
            target=capture_call_tap,
            args=(PHONE_TO_GROK, channels, incoming, speaking, stop),
            daemon=True)
        playback = ctx.Process(
            target=play_call_mic,
            args=(GROK_TO_PHONE, outgoing, speaking, stop),
            daemon=True)
        capture.start()
        playback.start()
        print("streams-started", "tap", "process-or-blackhole", "play", GROK_TO_PHONE, flush=True)

        payload = build_reservation_session_payload(tools=self.tools, brief=brief)
        url = f"wss://api.x.ai/v1/realtime?model={self.model}"
        try:
            while True:
                try:
                    await self._run_socket(websockets, url, payload, incoming, outgoing)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    print("voice-reconnect", flush=True)
                    await asyncio.sleep(1)
                else:
                    print("socket-closed", flush=True)
                    await asyncio.sleep(1)
        finally:
            stop.set()
            for process in (capture, playback):
                process.join(timeout=2)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)

    async def _run_socket(self, websockets, url, payload, incoming, outgoing) -> None:
        async with websockets.connect(
            url, additional_headers={"Authorization": f"Bearer {self.api_key}"}
        ) as ws:
            await ws.send(json.dumps({"type": "session.update", "session": payload}))
            session_ready = asyncio.Event()

            async def pump_mic():
                await session_ready.wait()
                while True:
                    try:
                        chunk = await asyncio.to_thread(incoming.get, timeout=0.25)
                    except queue.Empty:
                        continue
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode("ascii"),
                    }))

            async def pump_ws():
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    kind = event.get("type")
                    if kind == "error":
                        print("xai-error", event, flush=True)
                        continue
                    if kind == "session.updated":
                        print("session-updated", flush=True)
                        if not session_ready.is_set():
                            session_ready.set()
                            await ws.send(json.dumps({
                                "type": "response.create",
                                "response": {
                                    "instructions": (
                                        "Say clearly: Hey Akshit, this is Rally, "
                                        "can you hear me?"
                                    ),
                                },
                            }))
                    if kind == "conversation.item.input_audio_transcription.completed":
                        print("transcript", event.get("transcript") or event, flush=True)
                    elif kind in {
                        "input_audio_buffer.speech_started",
                        "response.done",
                    }:
                        print(kind, flush=True)
                    if kind == "response.output_audio.delta" and event.get("delta"):
                        try:
                            outgoing.put_nowait(base64.b64decode(event["delta"]))
                        except Exception:
                            pass

            await asyncio.gather(pump_mic(), pump_ws())
