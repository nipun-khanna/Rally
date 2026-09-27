"""Publish an approved static portal snapshot with the Vercel CLI."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from app.config import Settings
from app.portal_store import PortalStore
from app.store import Store
from scripts.export_portal import export_group, export_portal


def _digest(directory: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        if ".vercel" in path.parts or path.name == ".env.local":
            continue
        hasher.update(str(path.relative_to(directory)).encode())
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                hasher.update(block)
    return hasher.hexdigest()


def _deploy(settings: Settings, output: Path, *, project: str) -> str:
    digest = _digest(output)
    marker = settings.database_path.parent / "portal_publish_hash"
    if marker.exists() and marker.read_text() == digest:
        return "unchanged"
    subprocess.run(["vercel", "link", "--yes", "--project", project, "--no-color"],
                   cwd=output, check=True, capture_output=True, text=True)
    previous_url_file = settings.database_path.parent / "portal_deployment_url"
    previous_url = previous_url_file.read_text().strip() if previous_url_file.exists() else ""
    deployment = subprocess.run(["vercel", "deploy", "--prod", "--yes", "--no-color"],
                                cwd=output, check=True, capture_output=True, text=True)
    match = re.search(r"https://[a-z0-9-]+\.vercel\.app", deployment.stdout)
    if not match:
        raise RuntimeError("Vercel did not return a deployment URL")
    new_url = match.group(0)
    if previous_url and previous_url != new_url:
        subprocess.run(["vercel", "rm", previous_url, "--yes", "--no-color"],
                       cwd=output, check=True, capture_output=True, text=True)
    previous_url_file.write_text(new_url)
    marker.write_text(digest)
    return "published"


def publish(settings: Settings, *, project: str = "rallyplans",
            output_dir: str | Path = "data/portal_build") -> str:
    """Rebuild and deploy only when every archive import completed and content changed."""
    if os.environ.get("RALLY_PORTAL_PUBLISH_APPROVED") != "1":
        raise RuntimeError("External publication has not been enabled")
    portal_store = PortalStore(settings.database_path)
    if not settings.allowed_chat_ids or any(
            portal_store.import_state(chat_id)["status"] != "complete"
            for chat_id in settings.allowed_chat_ids):
        return "waiting for complete history import"
    output = Path(output_dir).resolve()
    export_portal(settings.database_path, settings.database_path.parent / "portal_media",
                  settings.allowed_chat_ids, output)
    return _deploy(settings, output, project=project)


def publish_live(settings: Settings, chat_id: str, *, project: str = "rallyplans",
                 output_dir: str | Path = "data/portal_build") -> str:
    """Generate one chat's live snapshot and deploy it without waiting on history import."""
    if os.environ.get("RALLY_PORTAL_PUBLISH_APPROVED") != "1":
        raise RuntimeError("External publication has not been enabled")
    if chat_id not in settings.allowed_chat_ids:
        raise PermissionError("Chat is not allowed")
    from app.dashboard_live import sync_live_context
    portal_store = PortalStore(settings.database_path)
    sync_live_context(Store(settings.database_path), portal_store, chat_id)
    output = Path(output_dir).resolve()
    export_group(settings.database_path, settings.database_path.parent / "portal_media",
                 chat_id, output)
    return _deploy(settings, output, project=project)


if __name__ == "__main__":
    print(publish(Settings.from_env()))
