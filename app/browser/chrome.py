"""Launch Google Chrome via Playwright without touching a live Default profile."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.browser.log import logger

CHROME_CHANNEL = "chrome"
_IGNORE = shutil.ignore_patterns(
    "Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
    "GraphiteDawnCache", "DawnCache", "DawnGraphiteCache", "Crashpad",
    "BrowserMetrics", "OptimizationHints", "OptimizationGuidePredictionModels",
    "SingletonLock", "SingletonCookie", "SingletonSocket", "Service Worker",
    "component_crx_cache", "extensions_crx_cache",
)


def chrome_executable_candidates() -> tuple[Path, ...]:
    home = Path.home()
    return (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    )


def chrome_channel_available() -> bool:
    return any(path.exists() for path in chrome_executable_candidates())


def resolve_channel(configured: str | None) -> str | None:
    value = (configured or "auto").strip().lower()
    if value in {"chromium", "off", "0"}:
        return None
    if value in {"auto", "chrome", ""}:
        if value == "chrome":
            return CHROME_CHANNEL
        return CHROME_CHANNEL if chrome_channel_available() else None
    return None


def profile_is_ready(path: Path) -> bool:
    root = Path(path)
    return any((root / rel).exists() for rel in (
        "Default/Cookies", "Default/Preferences", "Cookies", "Preferences",
    ))


def source_is_locked(path: Path) -> bool:
    root = Path(path)
    return any((candidate / "SingletonLock").exists() for candidate in (root, root.parent))


STEALTH_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
)


def persistent_launch_kwargs(*, downloads_path, headed: bool, channel: str | None,
                             proxy_url: str | None = None) -> dict:
    kwargs = {
        "headless": not headed,
        "downloads_path": str(downloads_path),
        "service_workers": "block",
        "args": list(STEALTH_ARGS),
        "ignore_default_args": ["--enable-automation"],
    }
    if channel:
        kwargs["channel"] = channel
    if proxy_url:
        kwargs["proxy"] = {"server": proxy_url}
    return kwargs


def clone_user_data(source: Path | str | None, dest: Path | str) -> str:
    """Copy a real Chrome profile into Rally's user_data_dir. Never attach in place."""
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest_path.chmod(0o700)
    if not source:
        return "missing"
    source_path = Path(source).expanduser()
    if not source_path.exists():
        logger.info("chrome user-data source missing; using empty rally profile")
        return "missing"
    if not source_path.is_dir():
        raise ValueError("Browser user data dir must be a directory")
    if profile_is_ready(dest_path):
        logger.debug("rally profile already initialized; skip chrome clone")
        return "skipped"
    source_path = source_path.resolve()
    dest_path = dest_path.resolve()
    if source_path == dest_path:
        return "skipped"
    if dest_path.is_relative_to(source_path) or source_path.is_relative_to(dest_path):
        logger.info("chrome user-data source overlaps rally profile; skip clone")
        return "skipped"
    locked = source_is_locked(source_path)
    if locked:
        logger.info("chrome source has SingletonLock; cloning instead of attaching")
    try:
        if (source_path / "Default").is_dir() or (source_path / "Local State").exists():
            default = source_path / "Default"
            if default.is_dir():
                shutil.copytree(default, dest_path / "Default", dirs_exist_ok=True,
                                ignore=_IGNORE)
            for name in ("Local State", "First Run"):
                item = source_path / name
                if item.is_file():
                    shutil.copy2(item, dest_path / name)
        else:
            shutil.copytree(source_path, dest_path / "Default", dirs_exist_ok=True,
                            ignore=_IGNORE)
    except shutil.Error:
        logger.exception("chrome clone skipped some locked files")
    dest_path.chmod(0o700)
    logger.info("cloned chrome profile into rally user_data_dir locked=%s ready=%s",
                locked, profile_is_ready(dest_path))
    return "cloned"
