"""Dry-run or explicitly place one Vapi call to the configured test destination."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.voice.vapi import AUTHORIZED_TEST_NUMBER, VapiDialer, VapiError


def load_vapi_settings() -> tuple[str, str, str]:
    settings = Settings.from_env()
    return (settings.vapi_api_key, settings.vapi_assistant_id,
            settings.vapi_phone_number_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--place", action="store_true", help="actually place one outbound call")
    parser.add_argument("--number", default=AUTHORIZED_TEST_NUMBER)
    args = parser.parse_args(argv)
    if args.number != AUTHORIZED_TEST_NUMBER:
        print("refused: only the authorized Vapi test number may be called", file=sys.stderr)
        return 2
    dialer = VapiDialer(*load_vapi_settings())
    if not dialer.ready():
        print("Vapi needs API key, assistant ID, and outbound phone number ID", file=sys.stderr)
        return 2
    if not args.place:
        print(f"dry-run Vapi outbound to {args.number}; use --place to call")
        return 0
    try:
        result = dialer.place_call(to_number=args.number)
    except VapiError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    print(f"Vapi call {result['id']} {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
