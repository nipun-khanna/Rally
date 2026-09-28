import asyncio
import json
import queue
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from app.voice import bridge
from app.voice.bridge import (
    LocalGrokVoice,
    local_voice_ready,
    pump_process_tap,
    take_playback_bytes,
)
from app.voice.pipeline import run_mac_phone_call
from app.voice.telco import audio_bridge_ready


def test_twilio_audio_bridge_stays_off():
    assert audio_bridge_ready() is False


def test_local_voice_ready_needs_key():
    assert local_voice_ready("") is False
    assert local_voice_ready("xai-test") is True


def test_injected_voice_does_not_open_a_websocket():
    started = []
    voice = LocalGrokVoice("secret", starter=lambda brief: started.append(brief) or {"attached": True})

    class Dialer:
        def place_call(self, *, to_number, method="phone"):
            return {"dialed": True, "method": method, "url": f"tel://{to_number}"}

    placed = run_mac_phone_call(
        to_number="+17032004231", dialer=Dialer(), voice=voice, brief={"venue": "test"})
    assert placed["dialed"] is True
    assert placed["voice_attached"] is True
    assert started == [{"venue": "test"}]


def test_process_tap_chunks_reach_grok_while_not_speaking():
    class Incoming:
        def __init__(self):
            self.items = []

        def put_nowait(self, chunk):
            self.items.append(chunk)

    class Flag:
        value = False

    class Stop:
        def __init__(self):
            self.n = 0

        def is_set(self):
            self.n += 1
            return self.n > 1

    speech = (9000).to_bytes(2, "little", signed=True) * 4800
    incoming = Incoming()
    pump_process_tap(
        iter([speech]), incoming, Flag(), Stop(), chunk_bytes=9600)
    assert incoming.items == [speech]


def test_playback_callback_pads_silence_when_queue_empty():
    leftover = bytearray()
    chunk = take_playback_bytes(leftover, 4, lambda: b"", channels=2)
    assert chunk == b"\x00" * 16


def test_playback_callback_consumes_mono_pcm():
    leftover = bytearray()
    sample = (1000).to_bytes(2, "little", signed=True)
    chunks = [sample * 2]

    def pull():
        return chunks.pop(0) if chunks else b""

    chunk = take_playback_bytes(leftover, 2, pull, channels=2)
    assert len(chunk) == 8
    assert leftover == b""


def test_socket_queue_read_has_timeout_for_cancellation():
    class Incoming:
        def get(self, block=True, timeout=None):
            assert timeout is not None and timeout <= 1
            raise queue.Empty

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, message):
            pass

        async def __aiter__(self):
            yield json.dumps({"type": "session.updated"})
            await asyncio.sleep(0.05)

    async def run():
        socket = SimpleNamespace(connect=lambda *args, **kwargs: Socket())
        task = asyncio.create_task(LocalGrokVoice("test")._run_socket(
            socket, "unused", {}, Incoming(), queue.Queue()))
        await asyncio.sleep(0.1)
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


@pytest.mark.parametrize("ready", [False, True])
def test_process_tap_stop_unblocks_silent_subprocess(monkeypatch, tmp_path, ready):
    script = tmp_path / "tap.swift"
    script.touch()
    monkeypatch.setattr(bridge, "_tap_script", lambda: script)
    real_popen = subprocess.Popen
    children = []

    def popen(*args, **kwargs):
        code = "import sys,time; "
        if ready:
            code += "print('@READY', file=sys.stderr); "
        child = real_popen([sys.executable, "-u", "-c", code + "time.sleep(30)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(bridge.subprocess, "Popen", popen)
    stop = threading.Event()
    worker = threading.Thread(target=bridge.capture_process_tap,
                              args=(queue.Queue(), SimpleNamespace(value=False), stop))
    worker.start()
    try:
        # Let startup or a silent stdout read begin before requesting shutdown.
        stop.wait(0.1)
        stop.set()
        worker.join(timeout=2)
        assert not worker.is_alive(), "silent tap must observe stop without audio"
        assert children and children[0].poll() is not None
        assert children[0].stdout.closed
        assert children[0].stderr.closed
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
        worker.join(timeout=2)


def test_session_terminates_and_reaps_children_after_graceful_stop(monkeypatch):
    children = []
    stop = threading.Event()

    class Process:
        def __init__(self, **kwargs):
            self.actions = []
            children.append(self)

        def start(self):
            self.actions.append("start")

        def join(self, timeout=None):
            assert stop.is_set()
            self.actions.append("join")

        def is_alive(self):
            return "terminate" not in self.actions

        def terminate(self):
            self.actions.append("terminate")

    context = SimpleNamespace(Queue=queue.Queue, Value=lambda *args: None,
                              Event=lambda: stop, Process=Process)
    monkeypatch.setattr(bridge.multiprocessing, "get_context", lambda _: context)
    monkeypatch.setattr(bridge, "apply_phone_cables", lambda: None)
    monkeypatch.setattr(bridge, "_device_input_channels", lambda *args: 2)

    async def cancel(*args):
        raise asyncio.CancelledError

    voice = LocalGrokVoice("test")
    monkeypatch.setattr(voice, "_run_socket", cancel)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(voice._session({}))
    assert len(children) == 2
    assert all(child.actions == ["start", "join", "terminate", "join"]
               for child in children)
