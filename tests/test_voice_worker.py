import fcntl
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.voice import run_worker


@pytest.fixture
def worker_env(monkeypatch, tmp_path):
    lock_path = tmp_path / "voice-worker.lock"
    monkeypatch.setattr(run_worker, "LOCK_PATH", lock_path, raising=False)
    monkeypatch.setattr(
        run_worker.Settings,
        "from_env",
        lambda: SimpleNamespace(xai_api_key="test-key", voice_model="test-model"),
    )
    return lock_path


def test_duplicate_worker_does_not_start_audio(monkeypatch, worker_env):
    class Voice:
        def __init__(self, *args, **kwargs):
            pytest.fail("duplicate worker tried to construct an audio session")

    monkeypatch.setattr(run_worker, "LocalGrokVoice", Voice)
    with worker_env.open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run_worker.main() == 0


@pytest.mark.parametrize("stop", ["keyboard", "sigterm", "retry-sleep"])
def test_shutdown_unwinds_session_releases_lock_and_restores_handler(
    monkeypatch, worker_env, stop
):
    sessions = []
    cleaned_up = []
    prior_handler = signal.getsignal(signal.SIGTERM)

    class Voice:
        def __init__(self, *args, **kwargs):
            pass

        def _run(self, brief):
            sessions.append(brief)
            try:
                if stop == "keyboard":
                    raise KeyboardInterrupt
                if stop == "sigterm":
                    handler = signal.getsignal(signal.SIGTERM)
                    if not callable(handler):
                        pytest.fail("worker must handle SIGTERM to unwind audio")
                    handler(signal.SIGTERM, None)
                    pytest.fail("SIGTERM handler returned without unwinding the session")
            finally:
                cleaned_up.append(True)

    def interrupted_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_worker, "LocalGrokVoice", Voice)
    monkeypatch.setattr(run_worker.time, "sleep", interrupted_sleep)
    try:
        result = run_worker.main()
    except KeyboardInterrupt:
        pytest.fail("worker leaked KeyboardInterrupt instead of exiting cleanly")
    assert result == 0
    assert sessions == [None]
    assert cleaned_up == [True]
    assert signal.getsignal(signal.SIGTERM) == prior_handler
    with worker_env.open("a") as next_owner:
        fcntl.flock(next_owner, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_watcher_stops_when_worker_exits_cleanly(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    watcher = scripts / "watch_rally_voice.sh"
    watcher.write_text(Path("scripts/watch_rally_voice.sh").read_text())
    executable = tmp_path / ".venv" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\necho worker-ran\nexit 0\n")
    executable.chmod(0o755)
    try:
        result = subprocess.run(
            ["/bin/bash", str(watcher)], capture_output=True, text=True, timeout=2
        )
    except subprocess.TimeoutExpired:
        pytest.fail("watcher restarted a worker after clean shutdown")
    assert result.returncode == 0
    assert result.stdout.count("worker-ran") == 1
