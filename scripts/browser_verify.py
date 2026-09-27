"""Prove the configured browser backend can open https://example.com.

Prints backend + page title only. Never prints API keys or CDP URLs.
"""

from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings


def _title_from_page(page) -> str:
    try:
        return (page.title() or "").strip()
    except Exception:
        return ""


def verify_browser_use(settings: Settings) -> dict:
    from app.browser.hosted import BrowserUseClient

    client = BrowserUseClient(settings.browser_use_api_key)
    result = client.run_task(
        "Open https://example.com and return the page title.", timeout_seconds=120)
    answer = (result.get("answer") or "").strip()
    return {"backend": "browser-use", "title": answer[:80],
            "ok": result.get("status") == "ok" and bool(answer)}


def verify_hosted(settings: Settings) -> dict:
    from playwright.sync_api import sync_playwright

    from app.browser.hosted import BrowserbaseClient

    client = BrowserbaseClient(settings.browserbase_api_key, settings.browserbase_project_id)
    session = client.create_session()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(session["connect_url"])
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://example.com", wait_until="domcontentloaded", timeout=20000)
            title = _title_from_page(page)
            browser.close()
    finally:
        client.release()
    return {"backend": "browserbase", "title": title, "ok": "example" in title.lower()}


def verify_local() -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded", timeout=20000)
        title = _title_from_page(page)
        browser.close()
    return {"backend": "local", "title": title, "ok": "example" in title.lower()}


def main() -> None:
    settings = Settings.from_env()
    if settings.browser_use_api_key:
        result = verify_browser_use(settings)
    elif settings.browserbase_api_key:
        result = verify_hosted(settings)
    else:
        result = verify_local()
    print(f"backend={result['backend']} title={result['title'] or 'unknown'} "
          f"ok={str(result['ok']).lower()}")
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
