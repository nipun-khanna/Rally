"""Place one authorized Mac Continuity test call. Does not book anything.

Only +17032004231 is allowed. Dry-run prints the URL and exits.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.voice.caller import normalize_phone
from app.voice.continuity import (
    AUTHORIZED_TEST_NUMBER,
    ContinuityDialer,
    ContinuityError,
    url_for,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--method",
        choices=("phone", "tel", "facetime-audio", "mirroring", "facetime-new"),
        default="phone")
    parser.add_argument("--number", default=AUTHORIZED_TEST_NUMBER)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    number = normalize_phone(args.number) or args.number.strip()
    if number != AUTHORIZED_TEST_NUMBER:
        print("refused: only the authorized test number may be dialed", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"dry-run {args.method} {url_for(number, args.method)}")
        return 0
    try:
        from app.config import Settings
        from app.voice.bridge import LocalGrokVoice
        from app.voice.pipeline import run_mac_phone_call

        settings = Settings.from_env()
        voice = None
        if settings.xai_api_key:
            voice = LocalGrokVoice(settings.xai_api_key, model=settings.voice_model)
        placed = run_mac_phone_call(
            to_number=number,
            dialer=ContinuityDialer(method=args.method, methods=(args.method,)),
            voice=voice,
        )
    except ContinuityError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    confirm = placed.get("confirm") or ""
    voice = "attached" if placed.get("voice_attached") else (placed.get("voice_reason") or "off")
    print(f"placed method={placed['method']} confirm={confirm} voice={voice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
