"""Resumable BlueBubbles archive import for a group portal.

The archive is deliberately separate from Rally's live planning message queue.
BlueBubbles' local server is the source of truth for messages and media.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class HistoryFetchError(RuntimeError):
    """A history request failed; safe to show without exposing credentials."""


def normalize_archive_message(item: dict[str, Any], chat_id: str) -> dict[str, Any] | None:
    """Normalize a BlueBubbles message, including messages containing only media."""
    guid = item.get("guid")
    created = item.get("dateCreated")
    if not chat_id or not isinstance(guid, str) or not guid or isinstance(created, bool) or not isinstance(created, (int, float)):
        return None
    try:
        sent_at = datetime.fromtimestamp(created / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    handle = item.get("handle")
    sender = "local-imessage-account" if item.get("isFromMe") else (handle.get("address") if isinstance(handle, dict) else None)
    attachments = []
    for attachment in item.get("attachments") or []:
        if not isinstance(attachment, dict) or not isinstance(attachment.get("guid"), str):
            continue
        attachments.append({
            "attachment_id": attachment["guid"],
            "mime_type": attachment.get("mimeType") or "application/octet-stream",
            "filename": attachment.get("transferName") or "attachment",
            "size_bytes": attachment.get("totalBytes"),
            "local_path": None,
            "status": "pending",
        })
    reaction_to = item.get("associatedMessageGuid")
    if isinstance(reaction_to, str) and "/" in reaction_to:
        reaction_to = reaction_to.split("/", 1)[1]
    return {
        "message_id": guid,
        "sent_at": sent_at,
        "sender_id": sender or "unknown",
        "text": item.get("text") if isinstance(item.get("text"), str) else "",
        "is_from_me": bool(item.get("isFromMe")),
        "is_deleted": bool(item.get("isDeleted") or item.get("dateRetracted")),
        "reaction_type": item.get("associatedMessageType") or None,
        "reaction_to": reaction_to if isinstance(reaction_to, str) else None,
        "attachments": attachments,
    }


class BlueBubblesHistoryClient:
    def __init__(self, base_url: str, password: str, opener: Callable[..., Any] = urlopen):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Invalid BlueBubbles base URL")
        if not password:
            raise ValueError("BlueBubbles password is required")
        self._root = parsed
        self._password = password
        self._opener = opener

    def _url(self, path: str, **params: object) -> str:
        query = urlencode({"password": self._password, **params})
        return urlunsplit((self._root.scheme, self._root.netloc,
                           self._root.path.rstrip("/") + path, query, ""))

    def fetch_messages(self, chat_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Fetch one oldest-first page, including handle and attachment relations."""
        if not chat_id or not (1 <= limit <= 500) or offset < 0:
            raise ValueError("Invalid history page")
        path = f"/api/v1/chat/{quote(chat_id, safe='')}/message"
        url = self._url(path, limit=limit, offset=offset, sort="ASC",
                        **{"with": "handle,attachment"})
        try:
            with self._opener(Request(url), timeout=60) as response:
                body = json.load(response)
        except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError):
            raise HistoryFetchError("BlueBubbles history request failed") from None
        if not isinstance(body, dict) or body.get("status") != 200 or not isinstance(body.get("data"), list):
            raise HistoryFetchError("BlueBubbles returned an invalid history page")
        return [item for item in body["data"] if isinstance(item, dict)]

    def download_attachment(self, guid: str, destination: str | Path) -> None:
        """Stream one attachment to a file, replacing it only after complete download."""
        if not guid:
            raise ValueError("Attachment GUID is required")
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        url = self._url(f"/api/v1/attachment/{quote(guid, safe='')}/download")
        try:
            with self._opener(Request(url), timeout=120) as response, part.open("wb") as target:
                while block := response.read(1024 * 1024):
                    target.write(block)
            part.replace(dest)
        except (HTTPError, URLError, OSError):
            part.unlink(missing_ok=True)
            raise HistoryFetchError("BlueBubbles attachment download failed") from None

    def fetch_contacts(self) -> list[dict[str, Any]]:
        try:
            with self._opener(Request(self._url("/api/v1/contact")), timeout=30) as response:
                body = json.load(response)
        except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError):
            raise HistoryFetchError("BlueBubbles contacts request failed") from None
        if not isinstance(body, dict) or body.get("status") != 200 or not isinstance(body.get("data"), list):
            raise HistoryFetchError("BlueBubbles returned invalid contacts")
        return [item for item in body["data"] if isinstance(item, dict)]


class HistoryImporter:
    """Import oldest-first pages without feeding historical messages to Rally's agent."""

    def __init__(self, client: BlueBubblesHistoryClient, store: Any, media_root: str | Path):
        self.client = client
        self.store = store
        self.media_root = Path(media_root)

    def import_page(self, chat_id: str, limit: int = 100) -> int:
        state = self.store.import_state(chat_id)
        offset = int(state.get("cursor") or 0)
        self.store.set_import_state(chat_id, cursor=str(offset), status="running")
        try:
            source = self.client.fetch_messages(chat_id, limit=limit, offset=offset)
            messages = [self._normalize(chat_id, item) for item in source]
            messages = [item for item in messages if item is not None]
            self.store.upsert_messages(chat_id, messages)
            next_offset = offset + len(source)
            self.store.set_import_state(chat_id, cursor=str(next_offset),
                                        status="complete" if len(source) < limit else "pending")
            if len(source) < limit and hasattr(self.client, "fetch_contacts"):
                try:
                    self.sync_member_labels(chat_id)
                except HistoryFetchError:
                    pass
            return len(source)
        except Exception as exc:
            self.store.set_import_state(chat_id, cursor=str(offset), status="error",
                                        error=str(exc) if isinstance(exc, HistoryFetchError) else "History import failed")
            raise

    def import_all(self, chat_id: str, limit: int = 100, max_pages: int | None = None) -> int:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be positive")
        total = 0
        pages = 0
        while max_pages is None or pages < max_pages:
            count = self.import_page(chat_id, limit)
            total += count
            pages += 1
            if count < limit:
                break
        return total

    def sync_member_labels(self, chat_id: str) -> int:
        """Resolve only senders in this group's archive against local contacts."""
        contacts = self.client.fetch_contacts()
        addresses = {}
        for contact in contacts:
            name = contact.get("displayName") or " ".join(filter(None, [contact.get("firstName"), contact.get("lastName")]))
            if not isinstance(name, str) or not name.strip():
                continue
            for field in ("phoneNumbers", "emails"):
                for item in contact.get(field) or []:
                    address = item.get("address") if isinstance(item, dict) else None
                    if isinstance(address, str):
                        addresses[address.lower()] = name.strip()
                        digits = re.sub(r"\D", "", address)
                        if len(digits) >= 10:
                            addresses[digits[-10:]] = name.strip()
        count = 0
        for member in self.store.analytics(chat_id)["by_member"]:
            sender = member["sender_id"]
            digits = re.sub(r"\D", "", sender)
            name = addresses.get(sender.lower()) or (addresses.get(digits[-10:]) if len(digits) >= 10 else None)
            if name:
                self.store.set_member(chat_id, sender, name)
                count += 1
        return count

    def hydrate_pending_media(self, chat_id: str, page_size: int = 500) -> int:
        """Download media seen in live webhooks or missing during the first import."""
        before = None
        downloaded = 0
        while True:
            page = self.store.list_messages(chat_id, before=before, limit=page_size)
            if not page:
                break
            for message in page:
                changed = False
                for attachment in message.get("attachments") or []:
                    if attachment.get("status") == "unavailable":
                        continue
                    if attachment.get("status") == "available" and attachment.get("local_path") and Path(attachment["local_path"]).exists():
                        continue
                    attachment_id = attachment.get("attachment_id")
                    if not attachment_id:
                        continue
                    digest = hashlib.sha256((chat_id + "\0" + attachment_id).encode()).hexdigest()
                    destination = self.media_root / digest[:2] / digest
                    try:
                        self.client.download_attachment(attachment_id, destination)
                    except HistoryFetchError:
                        attachment["status"] = "unavailable"
                        attachment["local_path"] = None
                    else:
                        attachment["status"] = "available"
                        attachment["local_path"] = str(destination)
                        downloaded += 1
                    changed = True
                if changed:
                    self.store.upsert_messages(chat_id, [message])
            if len(page) < page_size:
                break
            before = page[-1]["sent_at"]
        return downloaded

    def _normalize(self, chat_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
        message = normalize_archive_message(item, chat_id)
        if message is None:
            return None
        for attachment in message["attachments"]:
            attachment_id = attachment["attachment_id"]
            digest = hashlib.sha256((chat_id + "\0" + attachment_id).encode()).hexdigest()
            destination = self.media_root / digest[:2] / digest
            status = "available"
            if not destination.exists():
                try:
                    self.client.download_attachment(attachment_id, destination)
                except HistoryFetchError:
                    status = "unavailable"
            attachment["local_path"] = str(destination) if status == "available" else None
            attachment["status"] = status
        return message
