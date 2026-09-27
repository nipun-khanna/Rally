"""Open Rally's isolated Chromium profile for manual website login."""

from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings


def run_browser_login(settings: Settings, chromium) -> None:
    if not settings.browser_enabled:
        raise ValueError("Enable RALLY_BROWSER_ENABLED before opening the browser profile")
    for path in (settings.browser_profile_path, settings.browser_download_path):
        Path(path).mkdir(parents=True, exist_ok=True, mode=0o700)
        Path(path).chmod(0o700)
    context = chromium.launch_persistent_context(
        str(settings.browser_profile_path), headless=False,
        downloads_path=str(settings.browser_download_path),
    )
    context.wait_for_event("close", timeout=0)


def main() -> None:
    settings = Settings.from_env()
    if not settings.browser_enabled:
        raise SystemExit("Set RALLY_BROWSER_ENABLED=1 after configuring the private owner")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        run_browser_login(settings, playwright.chromium)


if __name__ == "__main__":
    main()
