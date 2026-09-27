from app.voice.audio_route import (
    boost_pcm16,
    gate_noise,
    loudest_channel_pcm16,
    mix_pcm16,
    pcm16_rms,
)
from app.voice.session import build_reservation_session_payload


def test_noise_gate_silences_hiss():
    quiet = (40).to_bytes(2, "little", signed=True) * 240
    assert pcm16_rms(quiet) < 500
    assert gate_noise(quiet) == b"\x00" * len(quiet)


def test_noise_gate_keeps_speech():
    loud = (8000).to_bytes(2, "little", signed=True) * 240
    assert gate_noise(loud) == loud


def test_loudest_channel_keeps_phone_tap_not_channel_zero():
    silent = (0).to_bytes(2, "little", signed=True)
    speech = (9000).to_bytes(2, "little", signed=True)
    frame = silent * 7 + speech + silent * 8
    chunk = frame * 40
    mono = loudest_channel_pcm16(chunk, 16)
    assert mono == speech * 40


def test_mix_pcm16_adds_room_and_call():
    call = (4000).to_bytes(2, "little", signed=True) * 4
    room = (3000).to_bytes(2, "little", signed=True) * 4
    mixed = mix_pcm16(call, room)
    sample = int.from_bytes(mixed[:2], "little", signed=True)
    assert sample == 7000


def test_reservation_session_sends_pcm_48k_not_ulaw():
    payload = build_reservation_session_payload(tools=[], brief={"venue": "test"})
    assert payload["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 48000}
    assert payload["turn_detection"]["type"] == "server_vad"


def test_live_call_without_venue_listens_instead_of_booking():
    payload = build_reservation_session_payload(tools=[], brief=None)
    assert "Listen to every word" in payload["instructions"]
    assert "book a table" not in payload["instructions"]


def test_boost_pcm16_amplifies_quiet_speech():
    quiet = (200).to_bytes(2, "little", signed=True) * 8
    boosted = boost_pcm16(quiet, 8)
    sample = int.from_bytes(boosted[:2], "little", signed=True)
    assert sample == 1600
