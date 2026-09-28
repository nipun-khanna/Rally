"""Isolated Playwright runtime with typed, schema-checked page actions."""

from __future__ import annotations

import ipaddress
import os
import queue
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

from app.browser.chrome import (
    clone_user_data,
    persistent_launch_kwargs,
    resolve_channel,
)
from app.browser.log import action_summary, chat_label, logger, safe_url
from app.browser.url_policy import validate_public_url


ALLOWED_ACTIONS = frozenset({
    "navigate", "inspect", "click_link", "fill", "scroll", "screenshot", "download",
    "search", "wait_for_human",
})
ACTION_KEYS = {
    "navigate": frozenset({"action", "url"}),
    "inspect": frozenset({"action"}),
    "click_link": frozenset({"action", "role", "name"}),
    "fill": frozenset({"action", "role", "name", "text"}),
    "scroll": frozenset({"action", "direction"}),
    "screenshot": frozenset({"action"}),
    "download": frozenset({"action", "role", "name"}),
    "search": frozenset({"action", "query"}),
    "wait_for_human": frozenset({"action", "reason", "timeout_seconds"}),
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
_SECRET_FIELD = re.compile(
    r"password|passwd|passcode|one[- ]?time|otp|2fa|cvv|cvc|card number|"
    r"credit card|ssn|social security|secret",
    re.I,
)
HUMAN_WAIT_SECONDS = 300


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


def is_secret_fill(role: str | None, name: str | None, text: str | None = None) -> bool:
    return bool(
        _SECRET_FIELD.search(role or "")
        or _SECRET_FIELD.search(name or "")
        or _SECRET_FIELD.search(text or "")
    )


def maps_search_url(query: str) -> str:
    q = quote_plus((query or "").strip() or "restaurants")
    return "https://www.google.com/maps/search/?api=1&query=" + q


def google_search_url(query: str) -> str:
    return "https://www.google.com/search?q=" + quote_plus((query or "").strip())


def search_url(query: str, *, hosted: bool = False) -> str:
    """Hosted Browserbase can survive Google /search; local Playwright cannot."""
    if hosted:
        return google_search_url(query)
    return maps_search_url(query)


def _query_from_google_url(url: str, *, depth: int = 0) -> str:
    if not url or depth > 3:
        return ""
    parsed = urlsplit(url)
    qs = parse_qs(parsed.query)
    for key in ("q", "query"):
        value = (qs.get(key) or [""])[0].strip()
        if value:
            return value
    continue_to = (qs.get("continue") or [""])[0].strip()
    if continue_to:
        return _query_from_google_url(unquote(continue_to), depth=depth + 1)
    path = parsed.path or ""
    if path.startswith("/search/"):
        return unquote(path.split("/search/", 1)[-1]).strip("/")
    if path.startswith("/maps/search/"):
        return unquote(path.split("/maps/search/", 1)[-1]).strip("/")
    return ""


def rewrite_blocked_search_url(url: str, *, hosted: bool = False) -> str:
    """Local google.com/search and /sorry trip interstitials; Maps does not."""
    if hosted:
        return url
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").lower()
    if host in {"www.google.com", "google.com"} and parsed.path.startswith(("/search", "/sorry")):
        query = _query_from_google_url(url)
        return maps_search_url(query)
    return url


def validate_action(action: dict) -> dict:
    if not isinstance(action, dict) or action.get("action") not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported action")
    kind = action["action"]
    allowed = ACTION_KEYS[kind]
    extra = sorted(set(action) - allowed)
    if extra:
        logger.debug("ignoring extra action fields action=%s extras=%s", kind, extra)
    action = {key: action[key] for key in allowed if key in action}
    if kind == "navigate":
        url = action.get("url")
        if not isinstance(url, str) or url.lower().startswith(("javascript:", "file:", "data:")):
            raise ValueError("Unsupported URL")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("Unsupported URL")
        rewritten = rewrite_blocked_search_url(url)
        if rewritten != url:
            action["url"] = rewritten
            url = rewritten
            parsed = urlsplit(url)
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


_DEATH_TOKENS = (
    "targetclosed", "target closed", "has been closed", "browser has been closed",
    "crashed", "disconnected", "econnreset", "connection closed",
    "existing browser session", "already in use", "profile is already",
)


def death_reason(exc: Exception) -> str | None:
    text = f"{type(exc).__name__} {exc}".lower()
    for token in _DEATH_TOKENS:
        if token in text:
            return token
    return None


def _is_browser_death(exc: Exception) -> bool:
    return death_reason(exc) is not None


def _object_pid(obj) -> int | None:
    if obj is None:
        return None
    for attr in ("pid",):
        value = getattr(obj, attr, None)
        if isinstance(value, int) and value > 0:
            return value
    process = getattr(obj, "process", None) or getattr(obj, "_process", None)
    if process is not None:
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 0:
            return pid
    impl = getattr(obj, "_impl_obj", None)
    if impl is not None and impl is not obj:
        return _object_pid(impl)
    return None


def _playwright_importable() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    del sync_playwright
    return True


class _WorkerJob:
    def __init__(self, fn):
        self.fn = fn
        self.done = threading.Event()
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.fn()
        except BaseException as exc:
            self.error = exc
        finally:
            self.done.set()

    def wait(self, timeout):
        if not self.done.wait(timeout):
            raise TimeoutError("Playwright worker timed out")
        if self.error is not None:
            raise self.error
        return self.result


class BrowserRuntime:
    def __init__(self, profile_path, downloads_path, proxy_url, max_text_chars,
                 driver=None, resolver=socket.getaddrinfo, channel=None,
                 user_data_source=None, hosted=None, vendor=None):
        self.profile_path = Path(profile_path)
        self.downloads_path = Path(downloads_path)
        self.proxy_url = proxy_url
        self.max_text_chars = max_text_chars
        self.driver = driver
        self.resolver = resolver
        self.channel = channel
        self.user_data_source = Path(user_data_source) if user_data_source else None
        self.hosted = hosted
        self.vendor = vendor
        self._use_hosted = hosted is not None
        self._hosted_session = None
        self._running = False
        self._playwright = None
        self._context = None
        self._browser = None
        self._owner_page = None
        self._ephemeral = {}
        self._headed = False
        self._installed: bool | None = None
        self._playwright_thread: int | None = None
        self._chromium_pid: int | None = None
        self._jobs: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop, name="rally-playwright", daemon=True)
            self._worker.start()

    def _worker_loop(self) -> None:
        ident = threading.get_ident()
        self._playwright_thread = ident
        logger.debug("playwright worker loop ident=%s", ident)
        while True:
            job = self._jobs.get()
            if job is None:
                logger.debug("playwright worker loop exit ident=%s", ident)
                break
            job.run()

    def _on_worker(self, fn, timeout: float = 960):
        self._ensure_worker()
        if threading.current_thread() is self._worker:
            return fn()
        job = _WorkerJob(fn)
        self._jobs.put(job)
        return job.wait(timeout)

    def status(self) -> dict:
        return {"running": self._running, "installed": self._is_installed(),
                "profile": "configured",
                "channel": self._resolved_channel() or "chromium",
                "backend": ("browser-use" if self.vendor is not None
                            else "browserbase" if self._use_hosted else "local")}

    def _resolved_channel(self) -> str | None:
        return resolve_channel(self.channel)

    def _prepare_profile(self) -> None:
        self.profile_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.downloads_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.profile_path.chmod(0o700)
        self.downloads_path.chmod(0o700)
        clone_user_data(self.user_data_source, self.profile_path)

    def _persistent_launch_kwargs(self) -> dict:
        return persistent_launch_kwargs(
            downloads_path=self.downloads_path, headed=self._headed,
            channel=self._resolved_channel(), proxy_url=self.proxy_url)

    def _launch_persistent_context(self):
        kwargs = self._persistent_launch_kwargs()
        logger.debug(
            "launch_persistent_context headed=%s headless=%s profile=%s "
            "channel=%s downloads=%s service_workers=block %s thread=%s",
            self._headed, not self._headed, self.profile_path,
            kwargs.get("channel") or "chromium",
            self.downloads_path, self._exe_status(), threading.get_ident())
        try:
            return self._playwright.chromium.launch_persistent_context(
                str(self.profile_path), **kwargs)
        except Exception:
            if not kwargs.get("channel"):
                raise
            logger.exception("chrome channel launch failed; falling back to bundled chromium")
            kwargs = dict(kwargs)
            kwargs.pop("channel", None)
            return self._playwright.chromium.launch_persistent_context(
                str(self.profile_path), **kwargs)

    def _is_installed(self) -> bool:
        if self.driver is not None:
            return getattr(self.driver, "installed", True)
        if self._installed is not None:
            return self._installed
        if self._playwright is not None:
            exe = getattr(self._playwright.chromium, "executable_path", "") or ""
            self._installed = bool(exe) and Path(exe).exists()
            return self._installed
        return _playwright_importable()

    def _exe_status(self) -> str:
        exe = ""
        if self._playwright is not None:
            exe = getattr(self._playwright.chromium, "executable_path", "") or ""
        exists = bool(exe) and Path(exe).exists()
        return f"exe_set={bool(exe)} exe_exists={exists}"

    def _pid_status(self) -> str:
        context_pid = _object_pid(self._context)
        browser_pid = _object_pid(self._browser)
        if context_pid:
            self._chromium_pid = context_pid
        elif browser_pid:
            self._chromium_pid = browser_pid
        return (f"uvicorn_pid={os.getpid()} chromium_pid={self._chromium_pid} "
                f"context_pid={context_pid} browser_pid={browser_pid}")

    def start(self, headed: bool = False) -> dict:
        return self._on_worker(lambda: self._start_locked(headed))

    def recover(self, headed: bool | None = None) -> dict:
        return self._on_worker(lambda: self._recover_locked(headed))

    def stop(self) -> dict:
        if self._worker is None or not self._worker.is_alive():
            return self.status()
        return self._on_worker(self._stop_locked)

    def _start_error(self, exc: Exception, headed: bool) -> RuntimeError:
        if isinstance(exc, ImportError) or not _playwright_importable():
            return RuntimeError("Chromium is not installed")
        exe = ""
        if self._playwright is not None:
            exe = getattr(self._playwright.chromium, "executable_path", "") or ""
        if exe and Path(exe).exists():
            logger.exception("playwright start failed though chromium exists headed=%s",
                             headed)
            return RuntimeError(f"Playwright failed to start: {type(exc).__name__}")
        if "asyncio loop" in str(exc).lower() or "greenlet" in str(exc).lower():
            logger.exception("playwright start failed on wrong thread headed=%s", headed)
            return RuntimeError(f"Playwright failed to start: {type(exc).__name__}")
        return RuntimeError(f"Playwright failed to start: {type(exc).__name__}")

    def _start_locked(self, headed: bool = False) -> dict:
        if self._running:
            self._headed = headed
            return self.status()
        thread = threading.get_ident()
        logger.debug(
            "start headed=%s headless=%s profile=%s downloads=%s proxy=%s thread=%s %s",
            headed, not headed, self.profile_path, self.downloads_path,
            "set" if self.proxy_url else "none", thread, self._pid_status())
        if self.driver is not None:
            if not getattr(self.driver, "installed", True):
                raise RuntimeError("Chromium is not installed")
            self.driver.start(proxy_url=self.proxy_url, profile_path=str(self.profile_path),
                              downloads_path=str(self.downloads_path), headed=headed)
            self._running = True
            self._headed = headed
            self._playwright_thread = thread
            logger.debug("start driver-ok headed=%s thread=%s", headed, thread)
            return self.status()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            logger.exception("playwright import failed headed=%s profile=%s",
                             headed, self.profile_path)
            raise RuntimeError("Chromium is not installed") from exc
        self.profile_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.downloads_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.profile_path.chmod(0o700)
        self.downloads_path.chmod(0o700)
        try:
            self._playwright = sync_playwright().start()
            exe = self._playwright.chromium.executable_path
            logger.debug("playwright started %s thread=%s", self._exe_status(), thread)
            if not exe or not Path(exe).exists():
                raise RuntimeError("Chromium is not installed")
        except Exception as exc:
            self._playwright = None
            logger.exception("playwright start failed headed=%s profile=%s thread=%s",
                             headed, self.profile_path, thread)
            if isinstance(exc, RuntimeError) and str(exc) == "Chromium is not installed":
                raise
            raise self._start_error(exc, headed) from exc
        self._headed = headed
        self._running = True
        self._installed = True
        self._playwright_thread = thread
        logger.info("browser started headed=%s thread=%s %s %s",
                    headed, thread, self._exe_status(), self._pid_status())
        return self.status()

    def _recover_locked(self, headed: bool | None = None) -> dict:
        """Tear down a dead Playwright process and start a fresh one."""
        use_headed = self._headed if headed is None else headed
        logger.info(
            "recover begin headed=%s was_running=%s playwright_thread=%s now_thread=%s %s",
            use_headed, self._running, self._playwright_thread,
            threading.get_ident(), self._pid_status())
        try:
            self._stop_locked()
        except Exception:
            logger.exception("recover stop failed; resetting handles")
            self._playwright = None
            self._context = None
            self._browser = None
            self._owner_page = None
            self._ephemeral = {}
            self._running = False
            self._chromium_pid = None
            self._hosted_session = None
            self._use_hosted = self.hosted is not None
        try:
            status = self._start_locked(headed=use_headed)
        except Exception:
            logger.exception("recover start failed headed=%s", use_headed)
            raise
        logger.info("recover ok running=%s headed=%s thread=%s %s",
                    status.get("running"), use_headed, threading.get_ident(),
                    self._pid_status())
        return status

    def _stop_locked(self) -> dict:
        logger.debug("stop begin thread=%s %s", threading.get_ident(), self._pid_status())
        if self.hosted is not None:
            try:
                self.hosted.release()
            except Exception:
                logger.exception("hosted session release failed")
            self._hosted_session = None
            self._use_hosted = self.hosted is not None
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
        self._chromium_pid = None
        logger.info("browser stopped uvicorn_pid=%s", os.getpid())
        return self.status()

    def _ensure_started(self) -> None:
        if not self._running:
            self._start_locked(headed=True if self.driver is None else self._headed)

    def observe(self, *, chat_id: str, authenticated: bool) -> BrowserObservation:
        started = time.monotonic()
        logger.debug("observe begin %s auth=%s thread=%s pw_thread=%s running=%s",
                     chat_label(chat_id), authenticated, threading.get_ident(),
                     self._playwright_thread, self._running)
        result = self._on_worker(
            lambda: self._with_recovery(lambda: self._observe_once(chat_id, authenticated)))
        logger.debug(
            "observe done %s auth=%s duration_ms=%.0f url=%s",
            chat_label(chat_id), authenticated,
            (time.monotonic() - started) * 1000, safe_url(result.url))
        return result

    def act(self, *, chat_id: str, authenticated: bool, action: dict) -> dict:
        try:
            action = validate_action(action)
        except ValueError as exc:
            if "download type" in str(exc):
                return {"status": "blocked", "reason": "download type is not allowed"}
            raise
        if action["action"] == "fill" and is_secret_fill(
                action.get("role"), action.get("name"), action.get("text")):
            return {"status": "blocked", "reason": "credentials must be entered on the Mac"}
        if action["action"] == "search":
            action = {"action": "navigate",
                      "url": search_url(action.get("query") or "", hosted=self._use_hosted)}
        if action["action"] == "navigate":
            action["url"] = rewrite_blocked_search_url(action["url"], hosted=self._use_hosted)
            validate_public_url(action["url"], self.resolver)
        if action["action"] == "download":
            name = action.get("name") or ""
            if Path(name).suffix and classify_download(name, 0) == "blocked":
                return {"status": "blocked", "reason": "download type is not allowed"}
        started = time.monotonic()
        logger.debug("act begin %s auth=%s %s thread=%s pw_thread=%s",
                     chat_label(chat_id), authenticated, action_summary(action),
                     threading.get_ident(), self._playwright_thread)
        result = self._on_worker(
            lambda: self._with_recovery(lambda: self._act_once(chat_id, authenticated, action)))
        logger.debug("act done %s %s status=%s duration_ms=%.0f",
                     chat_label(chat_id), action_summary(action),
                     result.get("status"), (time.monotonic() - started) * 1000)
        return result

    def _ensure_hosted(self, authenticated: bool) -> None:
        if not authenticated or not self._use_hosted or self._hosted_session is not None:
            return
        try:
            session = self.hosted.create_session()
        except Exception:
            logger.exception("browserbase session create failed; falling back to local playwright")
            self._use_hosted = False
            return
        self._hosted_session = session
        logger.info("hosted browser session ready backend=browserbase id=%s",
                    session.get("id"))

    def _connect_hosted(self):
        session = self._hosted_session or self.hosted.create_session()
        self._hosted_session = session
        url = session["connect_url"]
        logger.debug("browserbase connect_over_cdp id=%s", session.get("id"))
        browser = self._playwright.chromium.connect_over_cdp(url)
        self._browser = browser
        return browser.contexts[0] if browser.contexts else browser.new_context()

    def _open_owner_context(self):
        if self._use_hosted:
            try:
                self._ensure_hosted(True)
                return self._connect_hosted()
            except Exception:
                logger.exception("browserbase connect failed; falling back to local playwright")
                self._use_hosted = False
        return self._launch_persistent_context()

    def _observe_once(self, chat_id: str, authenticated: bool) -> BrowserObservation:
        self._ensure_started()
        self._ensure_hosted(authenticated)
        if self.driver is not None:
            observed = self.driver.observe(chat_id, authenticated)
        else:
            observed = self._live_observe(chat_id, authenticated)
        return BrowserObservation(
            observed.url, observed.title,
            bound_text(observed.text, self.max_text_chars), observed.controls)

    def _act_once(self, chat_id: str, authenticated: bool, action: dict) -> dict:
        self._ensure_started()
        self._ensure_hosted(authenticated)
        if self.driver is not None:
            result = self.driver.act(chat_id, authenticated, action)
            return {key: value for key, value in result.items() if key != "cookies"}
        return self._live_act(chat_id, authenticated, action)

    def _with_recovery(self, fn):
        try:
            return fn()
        except Exception as exc:
            reason = death_reason(exc)
            logger.exception(
                "browser op failed death=%s reason=%s running=%s headed=%s "
                "thread=%s pw_thread=%s %s",
                bool(reason), reason or "none", self._running, self._headed,
                threading.get_ident(), self._playwright_thread, self._pid_status())
            if not reason:
                raise
            logger.info("recovering because death marker=%s", reason)
            try:
                self._recover_locked()
            except Exception:
                logger.exception("recover failed after death marker=%s", reason)
                raise
            return fn()

    def _proxy_kwargs(self) -> dict:
        return {"proxy": {"server": self.proxy_url}} if self.proxy_url else {}

    def _live_page(self, chat_id: str, authenticated: bool):
        if self._playwright is None:
            raise RuntimeError("Playwright is not started")
        if (self._playwright_thread is not None
                and self._playwright_thread != threading.get_ident()):
            logger.warning(
                "playwright thread mismatch pw_thread=%s now_thread=%s %s",
                self._playwright_thread, threading.get_ident(), chat_label(chat_id))
        if authenticated:
            if self._context is None:
                self._context = self._open_owner_context()
                self._wire(self._context)
                logger.info("owner context launched backend=%s %s %s",
                            "browserbase" if self._use_hosted else "local",
                            chat_label(chat_id), self._pid_status())
            if self._owner_page is None:
                self._owner_page = (self._context.pages[0] if self._context.pages
                                    else self._context.new_page())
                self._owner_page.on("popup", lambda page: page.close())
            return self._owner_page
        # Logged-out session: a new context, not a rejection and not the owner profile.
        if chat_id not in self._ephemeral:
            if self._browser is None:
                logger.debug("launch chromium headed=%s headless=%s %s thread=%s",
                             self._headed, not self._headed, self._exe_status(),
                             threading.get_ident())
                self._browser = self._playwright.chromium.launch(
                    headless=not self._headed, **self._proxy_kwargs())
                logger.info("ephemeral browser launched %s %s",
                            chat_label(chat_id), self._pid_status())
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
        try:
            page = self._live_page(chat_id, authenticated)
            controls = []
            for role in ("link", "button", "textbox"):
                for locator in page.get_by_role(role).all()[:20]:
                    name = (locator.inner_text() or locator.get_attribute("aria-label") or "").strip()
                    if name:
                        controls.append({"role": role, "name": name[:80]})
            url = page.url or ""
            body = ""
            if url and url != "about:blank":
                deadline = time.monotonic() + 2.5
                while True:
                    try:
                        body = page.inner_text("body") or ""
                    except Exception:
                        body = ""
                    if len(body.strip()) >= 80 or time.monotonic() >= deadline:
                        break
                    time.sleep(0.25)
            try:
                title = page.title() or ""
            except Exception:
                title = ""
            return BrowserObservation(url, title, bound_text(body, self.max_text_chars),
                                      tuple(controls))
        except Exception:
            logger.exception("live observe failed %s auth=%s url=%s",
                             chat_label(chat_id), authenticated,
                             safe_url(getattr(self._owner_page, "url", "")
                                      if authenticated else ""))
            if authenticated:
                self._owner_page = None
                self._context = None
            else:
                self._ephemeral.pop(chat_id, None)
            raise

    def _wait_for_human(self, page, timeout_seconds) -> dict:
        try:
            seconds = HUMAN_WAIT_SECONDS if timeout_seconds is None else int(timeout_seconds)
        except (TypeError, ValueError):
            seconds = HUMAN_WAIT_SECONDS
        seconds = max(0, min(seconds, 900))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
        url = getattr(page, "url", "") or ""
        return {"status": "waiting", "url": url}

    def _live_act(self, chat_id: str, authenticated: bool, action: dict) -> dict:
        page = self._live_page(chat_id, authenticated)
        kind = action["action"]
        started = time.monotonic()
        logger.debug("live_act %s %s page=%s",
                     chat_label(chat_id), action_summary(action),
                     safe_url(getattr(page, "url", "")))
        if kind == "wait_for_human":
            result = self._wait_for_human(page, action.get("timeout_seconds"))
            logger.debug("live_act wait_for_human duration_ms=%.0f url=%s",
                         (time.monotonic() - started) * 1000,
                         safe_url(result.get("url")))
            return result
        if kind == "navigate":
            page.goto(action["url"], wait_until="domcontentloaded", timeout=15000)
            landed = getattr(page, "url", "") or action.get("url") or ""
            fallback = rewrite_blocked_search_url(landed, hosted=self._use_hosted)
            if fallback != landed and fallback != action["url"]:
                logger.info("bot wall bounced url=%s", safe_url(landed))
                page.goto(fallback, wait_until="domcontentloaded", timeout=15000)
            logger.debug("live_act navigate duration_ms=%.0f url=%s",
                         (time.monotonic() - started) * 1000,
                         safe_url(getattr(page, "url", "") or action.get("url")))
            return {"status": "ok"}
        if kind == "inspect":
            return {"status": "ok"}
        if kind == "fill" and is_secret_fill(
                action.get("role"), action.get("name"), action.get("text")):
            return {"status": "blocked", "reason": "credentials must be entered on the Mac"}
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
