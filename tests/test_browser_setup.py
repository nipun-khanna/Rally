"""Local browser setup requires no downloaded Chromium in tests."""

import stat
import subprocess
import sys
import os
from pathlib import Path

import pytest

from app.config import Settings
from scripts.browser_login import run_browser_login


class FakeContext:
    def __init__(self):
        self.waited_for = None

    def wait_for_event(self, event, *, timeout):
        self.waited_for = (event, timeout)


class FakeChromium:
    def __init__(self):
        self.arguments = None
        self.context = FakeContext()

    def launch_persistent_context(self, profile, **kwargs):
        self.arguments = (profile, kwargs)
        return self.context


def test_login_uses_private_dedicated_headful_profile_and_waits_for_close(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env({
        "RALLY_BROWSER_ENABLED": "1",
        "RALLY_BROWSER_OWNER_CHAT_ID": "iMessage;-;owner",
        "RALLY_BROWSER_OWNER_SENDER_ID": "owner-handle",
    })
    chromium = FakeChromium()

    run_browser_login(settings, chromium)

    profile = Path("data/browser/profile")
    downloads = Path("data/browser/downloads")
    assert chromium.arguments == (str(profile), {
        "headless": False, "downloads_path": str(downloads),
    })
    assert profile.is_dir() and downloads.is_dir()
    assert stat.S_IMODE(profile.stat().st_mode) == 0o700
    assert stat.S_IMODE(downloads.stat().st_mode) == 0o700
    assert chromium.context.waited_for == ("close", 0)


def test_login_refuses_when_browser_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chromium = FakeChromium()
    with pytest.raises(ValueError):
        run_browser_login(Settings.from_env({}), chromium)
    assert chromium.arguments is None
    assert not (tmp_path / "data/browser").exists()


def test_documented_script_command_runs_from_checkout():
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "RALLY_BROWSER_ENABLED": "0"}
    result = subprocess.run([sys.executable, "scripts/browser_login.py"],
                            cwd=root, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "Set RALLY_BROWSER_ENABLED=1" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
