from app.voice.audio_route import apply_phone_app_io
from app.voice.caller import ReservationCaller, format_call_status, parse_reservation_call
from app.voice.continuity import AUTHORIZED_TEST_NUMBER, ContinuityDialer, url_for


def test_phone_app_url_and_method_chain():
    assert url_for(AUTHORIZED_TEST_NUMBER, "phone") == "tel://+17032004231"
    opened = []

    def opener(method, url):
        opened.append((method, url))

    dialer = ContinuityDialer(opener=opener, confirmer=lambda: "clicked:Call:Phone")
    placed = dialer.place_call(to_number=AUTHORIZED_TEST_NUMBER)
    assert placed["dialed"] is True
    assert placed["method"] == "phone"
    assert opened[0][0] == "phone"
    assert opened[0][1].startswith("tel://")
    assert "Call" in placed["confirm"]


def test_phone_uses_2ch_mouth_and_speaker_playback():
    from app.voice.audio_route import CALL_PLAYBACK, GROK_TO_PHONE
    assert GROK_TO_PHONE == "BlackHole 2ch"
    assert CALL_PLAYBACK == "MacBook Pro Speakers"


def test_phone_video_io_script_exists():
    from pathlib import Path
    script = Path("scripts/set_phone_blackhole.applescript")
    text = script.read_text()
    assert "menu item 12" not in text
    assert "menu item 19" not in text
    assert 'whose name is "Use System Setting"' in text
    assert "AXMenuItemMarkChar" in text
    assert callable(apply_phone_app_io)


def test_rally_direct_number_uses_phone_app_not_loopback():
    opened = []
    dialer = ContinuityDialer(
        opener=lambda method, url: opened.append((method, url)),
        confirmer=lambda: "clicked:Call:Phone")
    caller = ReservationCaller(continuity=dialer)
    result = caller.run("Hey Rally, call 7032004231")
    assert result.dialed is True
    assert result.transport == "continuity"
    assert result.status != "booked"
    assert opened and opened[0][0] == "phone"
    status = format_call_status(result).lower()
    assert "nothing is booked" in status
    assert "phone" in status
