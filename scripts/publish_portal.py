"""Publish an approved static portal snapshot with the Vercel CLI."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import subprocess
import threading
from pathlib import Path

from app.config import Settings
from app.portal_store import PortalStore
from app.store import Store
from scripts.export_portal import export_portal

# Serializes every publish() call (manual, periodic, or debounced-trigger) so two
# concurrent runs never rmtree/rewrite the same output directory out from under each other.
_publish_lock = threading.Lock()


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


def publish(settings: Settings, *, project: str | None = None,
            output_dir: str | Path | None = None) -> str:
    """Rebuild and deploy only when every archive import completed and content changed."""
    project = project or settings.vercel_project or "rallyplans"
    if os.environ.get("RALLY_PORTAL_PUBLISH_APPROVED") != "1":
        raise RuntimeError("External publication has not been enabled")
    if not _publish_lock.acquire(blocking=False):
        return "already publishing"
    try:
        lock_path = settings.database_path.parent / "portal_publish.lock"
        with open(lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return "already publishing"
            try:
                return _publish(settings, project=project, output_dir=output_dir)
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
    finally:
        _publish_lock.release()


def _publish(settings: Settings, *, project: str, output_dir: str | Path | None) -> str:
    portal_store = PortalStore(settings.database_path)
    ready_chat_ids = {chat_id for chat_id in settings.allowed_chat_ids
                      if portal_store.import_state(chat_id)["status"] == "complete"}
    if not ready_chat_ids:
        return "waiting for complete history import"
    # Deploy from outside any git working tree: the Vercel CLI attaches ambient
    # git metadata (commit author) from an ancestor .git, which this project's
    # deployment protection then blocks since that author has no access there.
    output = (Path(output_dir).resolve() if output_dir is not None
              else Path.home() / ".rally" / "portal_build")
    export_portal(settings.database_path, settings.database_path.parent / "portal_media",
                  ready_chat_ids, output, owner_name=settings.owner_display_name)
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
        try:
            subprocess.run(["vercel", "rm", previous_url, "--yes", "--no-color"],
                           cwd=output, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            pass
    previous_url_file.write_text(new_url)
    marker.write_text(digest)
    return "published"


def publish_live(settings: Settings, chat_id: str, *, project: str | None = None,
                 output_dir: str | Path | None = None) -> str:
    """Generate one chat's live snapshot and deploy it without waiting on history import."""
    project = project or settings.vercel_project or "rallyplans"
    if os.environ.get("RALLY_PORTAL_PUBLISH_APPROVED") != "1":
        raise RuntimeError("External publication has not been enabled")
    if chat_id not in settings.allowed_chat_ids:
        raise PermissionError("Chat is not allowed")
    if not _publish_lock.acquire(blocking=False):
        return "already publishing"
    try:
        lock_path = settings.database_path.parent / "portal_publish.lock"
        with open(lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return "already publishing"
            try:
                from app.dashboard_live import sync_live_context
                portal_store = PortalStore(settings.database_path)
                sync_live_context(Store(settings.database_path), portal_store, chat_id)
                output = (Path(output_dir).resolve() if output_dir is not None
                          else Path.home() / ".rally" / "portal_build")
                export_portal(
                    settings.database_path, settings.database_path.parent / "portal_media",
                    {chat_id}, output, owner_name=settings.owner_display_name)
                digest = _digest(output)
                marker = settings.database_path.parent / "portal_publish_hash"
                if marker.exists() and marker.read_text() == digest:
                    return "unchanged"
                subprocess.run(["vercel", "link", "--yes", "--project", project, "--no-color"],
                               cwd=output, check=True, capture_output=True, text=True)
                previous_url_file = settings.database_path.parent / "portal_deployment_url"
                previous_url = previous_url_file.read_text().strip() if previous_url_file.exists() else ""
                deployment = subprocess.run(
                    ["vercel", "deploy", "--prod", "--yes", "--no-color"],
                    cwd=output, check=True, capture_output=True, text=True)
                match = re.search(r"https://[a-z0-9-]+\.vercel\.app", deployment.stdout)
                if not match:
                    raise RuntimeError("Vercel did not return a deployment URL")
                new_url = match.group(0)
                if previous_url and previous_url != new_url:
                    try:
                        subprocess.run(["vercel", "rm", previous_url, "--yes", "--no-color"],
                                       cwd=output, check=True, capture_output=True, text=True)
                    except subprocess.CalledProcessError:
                        pass
                previous_url_file.write_text(new_url)
                marker.write_text(digest)
                return "published"
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
    finally:
        _publish_lock.release()


if __name__ == "__main__":
    print(publish(Settings.from_env()))
