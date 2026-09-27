"""Isolated Playwright runtime with typed, schema-checked page actions."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.browser.url_policy import validate_public_url


ALLOWED_ACTIONS = frozenset({
    "navigate", "inspect", "click_link", "fill", "scroll", "screenshot", "download",
})
ACTION_KEYS = {
    "navigate": frozenset({"action", "url"}),
    "inspect": frozenset({"action"}),
    "click_link": frozenset({"action", "role", "name"}),
    "fill": frozenset({"action", "role", "name", "text"}),
    "scroll": frozenset({"action", "direction"}),
    "screenshot": frozenset({"action"}),
    "download": frozenset({"action", "role", "name"}),
}
MAX_DOWNLOAD_BYTES = 5_000_000
ALLOWED_DOWNLOAD_SUFFIXES = frozenset({
    ".pdf", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".html", ".json",
})
BLOCKED_DOWNLOAD_SUFFIXES = frozenset({
    ".exe", ".sh", ".bat", ".cmd", ".com", ".msi", ".dll", ".bin", ".app", ".dmg",
    ".pkg", ".scr", ".ps1", ".js", ".mjs", ".py",
})
_COMMITMENT = re.compile(
    r"\b(submit|send|post|purchase|buy|book|delete|remove|confirm|accept|"
    r"agree|pay|checkout|grant|allow|update password)\b",
    re.I,
)


@dataclass(frozen=True)
class BrowserObservation:
    url: str
    title: str
    text: str
    controls: tuple[dict[str, str], ...]


def bound_text(text: str, max_chars: int) -> str:
    return text[:max_chars]


def classify_download(filename: str, size: int) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in BLOCKED_DOWNLOAD_SUFFIXES or suffix not in ALLOWED_DOWNLOAD_SUFFIXES:
        return "blocked"
    if size > MAX_DOWNLOAD_BYTES:
        return "blocked"
    return "ok"


def is_commitment_control(role: str | None, name: str | None) -> bool:
    return bool(_COMMITMENT.search(name or "") or _COMMITMENT.search(role or ""))


def validate_action(action: dict) -> dict:
    if not isinstance(action, dict) or action.get("action") not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported action")
    kind = action["action"]
    allowed = ACTION_KEYS[kind]
    if not set(action) <= allowed or "action" not in action:
        raise ValueError("Unsupported action fields")
    if kind == "navigate":
        url = action.get("url")
        if not isinstance(url, str) or url.lower().startswith(("javascript:", "file:", "data:")):
            raise ValueError("Unsupported URL")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("Unsupported URL")
        try:
            address = ipaddress.ip_address(parsed.hostname or "")
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("URL resolves to a non-public address")
    if kind == "download" and isinstance(action.get("name"), str):
        if classify_download(action["name"], 0) == "blocked" and Path(action["name"]).suffix:
            raise ValueError("download type is not allowed")
    return dict(action)


def audit_url_parts(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.hostname or "", parsed.path or "/"


class BrowserRuntime:
    def __init__(self, profile_path, downloads_path, proxy_url, max_text_chars,
                 driver=None, resolver=socket.getaddrinfo):
        self.profile_path = Path(profile_path)
        self.downloads_path = Path(downloads_path)
        self.proxy_url = proxy_url
        self.max_text_chars = max_text_chars
        self.driver = driver
        self.resolver = resolver
        self._running = False
        self._playwright = None
        self._context = None
        self._browser = None
        self._owner_page = None
        self._ephemeral = {}
        self._headed = False

    def status(self) -> dict:
        return {"running": self._running, "installed": self._is_installed(),
                "profile": "configured"}

    def _is_installed(self) -> bool:
        if self.driver is not None:
            return getattr(self.driver, "installed", True)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False
        try:
            playwright = sync_playwright().start()
            try:
                return bool(playwright.chromium.executable_path)
            finally:
                playwright.stop()
        except Exception:
            return False

    def start(self, headed: bool = False) -> dict:
        if self.driver is not None:
            if not getattr(self.driver, "installed", True):
                raise RuntimeError("Chromium is not installed")
            self.driver.start(proxy_url=self.proxy_url, profile_path=str(self.profile_path),
                              downloads_path=str(self.downloads_path), headed=headed)
            self._running = True
            return self.status()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Chromium is not installed") from exc
        self.profile_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.downloads_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.profile_path.chmod(0o700)
        self.downloads_path.chmod(0o700)
        try:
            self._playwright = sync_playwright().start()
            if not self._playwright.chromium.executable_path:
                raise RuntimeError("Chromium is not installed")
        except Exception as exc:
            self._playwright = None
            raise RuntimeError("Chromium is not installed") from exc
        self._headed = headed
        self._running = True
        return self.status()

    def stop(self) -> dict:
        if self.driver is not None:
            self.driver.stop()
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._owner_page = None
        self._ephemeral = {}
        self._running = False
        return self.status()

    def _ensure_started(self) -> None:
        if not self._running:
            self.start()

    def observe(self, *, chat_id: str, authenticated: bool) -> BrowserObservation:
        self._ensure_started()
        if self.driver is not None:
            observed = self.driver.observe(chat_id, authenticated)
        else:
            observed = self._live_observe(chat_id, authenticated)
        return BrowserObservation(
            observed.url, observed.title,
            bound_text(observed.text, self.max_text_chars), observed.controls)

    def act(self, *, chat_id: str, authenticated: bool, action: dict) -> dict:
        self._ensure_started()
        try:
            action = validate_action(action)
        except ValueError as exc:
            if "download type" in str(exc):
                return {"status": "blocked", "reason": "download type is not allowed"}
            raise
        if action["action"] == "navigate":
            validate_public_url(action["url"], self.resolver)
        if action["action"] == "download":
            name = action.get("name") or ""
            if Path(name).suffix and classify_download(name, 0) == "blocked":
                return {"status": "blocked", "reason": "download type is not allowed"}
        if self.driver is not None:
            result = self.driver.act(chat_id, authenticated, action)
            return {key: value for key, value in result.items() if key != "cookies"}
        return self._live_act(chat_id, authenticated, action)

    def _proxy_kwargs(self) -> dict:
        return {"proxy": {"server": self.proxy_url}} if self.proxy_url else {}

    def _live_page(self, chat_id: str, authenticated: bool):
        if authenticated:
            if self._context is None:
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(self.profile_path), headless=not self._headed,
                    downloads_path=str(self.downloads_path),
                    service_workers="block", **self._proxy_kwargs())
                self._wire(self._context)
            if self._owner_page is None:
                self._owner_page = (self._context.pages[0] if self._context.pages
                                    else self._context.new_page())
                self._owner_page.on("popup", lambda page: page.close())
            return self._owner_page
        if chat_id not in self._ephemeral:
            if self._browser is None:
                self._browser = self._playwright.chromium.launch(
                    headless=not self._headed, **self._proxy_kwargs())
            context = self._browser.new_context(service_workers="block",
                                                **self._proxy_kwargs())
            self._wire(context)
            page = context.new_page()
            page.on("popup", lambda popup: popup.close())
            self._ephemeral[chat_id] = page
        return self._ephemeral[chat_id]

    def _wire(self, context) -> None:
        context.route("**/*", self._on_route)

    def _on_route(self, route) -> None:
        try:
            validate_public_url(route.request.url, self.resolver)
        except ValueError:
            route.abort()
            return
        route.continue_()

    def _live_observe(self, chat_id: str, authenticated: bool) -> BrowserObservation:
        page = self._live_page(chat_id, authenticated)
        controls = []
        for role in ("link", "button", "textbox"):
            for locator in page.get_by_role(role).all()[:20]:
                name = (locator.inner_text() or locator.get_attribute("aria-label") or "").strip()
                if name:
                    controls.append({"role": role, "name": name[:80]})
        return BrowserObservation(
            page.url or "", page.title() or "",
            bound_text(page.inner_text("body") if page.url else "", self.max_text_chars),
            tuple(controls))

    def _live_act(self, chat_id: str, authenticated: bool, action: dict) -> dict:
        page = self._live_page(chat_id, authenticated)
        kind = action["action"]
        if kind == "navigate":
            page.goto(action["url"], wait_until="domcontentloaded", timeout=15000)
            return {"status": "ok"}
        if kind == "inspect":
            return {"status": "ok"}
        if kind == "scroll":
            page.mouse.wheel(0, 600 if action.get("direction") != "up" else -600)
            return {"status": "ok"}
        if kind == "screenshot":
            page.screenshot(type="png")
            return {"status": "ok"}
        locator = page.get_by_role(action.get("role") or "button", name=action.get("name") or "")
        if kind == "fill":
            locator.fill(action.get("text") or "")
            return {"status": "ok"}
        if kind == "download":
            with page.expect_download(timeout=15000) as download_info:
                locator.click()
            download = download_info.value
            suggested = download.suggested_filename or "download"
            if classify_download(suggested, 0) == "blocked":
                download.cancel()
                return {"status": "blocked", "reason": "download type is not allowed"}
            target = self.downloads_path / Path(suggested).name
            download.save_as(str(target))
            size = target.stat().st_size
            if classify_download(suggested, size) == "blocked":
                target.unlink(missing_ok=True)
                return {"status": "blocked", "reason": "download type is not allowed"}
            return {"status": "ok", "path": str(target), "bytes": size}
        locator.click()
        return {"status": "ok"}
