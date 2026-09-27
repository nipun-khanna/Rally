"""Entry for scripts/watch_rally_voice.sh. Loops so a clean WS close comes back."""

from __future__ import annotations

import faulthandler
import multiprocessing
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


def main() -> int:
    multiprocessing.freeze_support()
    settings = Settings.from_env()
    if not settings.xai_api_key:
        print("no xai key", file=sys.stderr)
        return 2
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
