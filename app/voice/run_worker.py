"""Entry for scripts/watch_rally_voice.sh. Loops so a clean WS close comes back."""

from __future__ import annotations

import faulthandler
import fcntl
import multiprocessing
import signal
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.voice.bridge import LocalGrokVoice

faulthandler.enable()
LOCK_PATH = Path("/tmp/rally-grok-voice-worker.lock")


def _stop_worker(signum, frame) -> None:
    # BaseException bypasses reconnect/retry handlers while running finally blocks.
    raise KeyboardInterrupt


def main() -> int:
    multiprocessing.freeze_support()
    settings = Settings.from_env()
    if not settings.xai_api_key:
        print("no xai key", file=sys.stderr)
        return 2
    # Keep the file in place: unlinking it could let another process lock a new inode.
    with LOCK_PATH.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("rally grok voice worker already running", flush=True)
            return 0
        previous_sigterm = signal.signal(signal.SIGTERM, _stop_worker)
        try:
            print("rally grok voice worker starting", flush=True)
            voice = LocalGrokVoice(settings.xai_api_key, model=settings.voice_model)
            while True:
                try:
                    voice._run(None)
                except Exception:
                    traceback.print_exc()
                    print("worker-loop-error", flush=True)
                print("rally grok voice worker returned", flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print("rally grok voice worker stopping", flush=True)
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
