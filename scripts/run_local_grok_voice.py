"""Run Grok Voice mic/speaker bridge. Does not dial. Uses .env xAI key."""

from __future__ import annotations

import faulthandler
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.voice.run_worker import main as worker_main

faulthandler.enable()


def main() -> int:
    return worker_main()


if __name__ == "__main__":
    raise SystemExit(main())
