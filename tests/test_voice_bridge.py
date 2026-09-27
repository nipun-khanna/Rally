from app.voice.bridge import LocalGrokVoice, local_voice_ready, take_playback_bytes
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
