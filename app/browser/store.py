"""Durable browser request and approval metadata. Page bodies are never stored."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class BrowserStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS browser_requests (
                    id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    action_digest TEXT,
                    pending_action TEXT,
                    url_host TEXT,
                    url_path TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    UNIQUE(chat_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS browser_approvals (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    action_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY(request_id) REFERENCES browser_requests(id)
                );
                CREATE TABLE IF NOT EXISTS browser_audit (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    url_host TEXT,
                    url_path TEXT,
                    outcome TEXT NOT NULL,
                    created_at TEXT
                );
            """)
            db.execute("UPDATE browser_requests SET status='uncertain' WHERE status='running'")

    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def create_request(self, chat_id: str, message_id: str, text: str, *, sender_id: str) -> dict:
        if not all((chat_id, message_id, text, sender_id)):
            raise ValueError("Request fields must be nonempty")
        request_hash = _hash(text)
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT OR IGNORE INTO browser_requests
                (id, chat_id, message_id, sender_id, request_hash, status, created_at, updated_at)
                VALUES (?,?,?,?,?,'pending',?,?)""",
                       (str(uuid4()), chat_id, message_id, sender_id, request_hash, now, now))
            row = db.execute("SELECT * FROM browser_requests WHERE chat_id=? AND message_id=?",
                             (chat_id, message_id)).fetchone()
            if row["request_hash"] != request_hash:
                raise ValueError("Message ID already used with different text")
            return dict(row)

    def get_request(self, chat_id: str, message_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM browser_requests WHERE chat_id=? AND message_id=?",
                             (chat_id, message_id)).fetchone()
        if row is None:
            raise PermissionError("Unknown browser request")
        return dict(row)

    def set_action_digest(self, request_id: str, digest: str) -> None:
        with self._db() as db:
            db.execute("UPDATE browser_requests SET action_digest=?, updated_at=? WHERE id=?",
                       (digest, datetime.now(timezone.utc).isoformat(), request_id))

    def set_pending_action(self, request_id: str, action: dict, digest: str,
                           host: str = "", path: str = "") -> None:
        with self._db() as db:
            db.execute("""UPDATE browser_requests
                SET pending_action=?, action_digest=?, url_host=?, url_path=?,
                    status='awaiting_approval', updated_at=? WHERE id=?""",
                       (json.dumps(action, sort_keys=True), digest, host, path,
                        datetime.now(timezone.utc).isoformat(), request_id))

    def pending_action(self, request_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT pending_action FROM browser_requests WHERE id=?",
                             (request_id,)).fetchone()
        if row is None or not row["pending_action"]:
            return None
        return json.loads(row["pending_action"])

    def mark_running(self, request_id: str) -> None:
        self._set_status(request_id, "running")

    def mark_status(self, request_id: str, status: str, *, host: str = "", path: str = "") -> None:
        with self._db() as db:
            db.execute("""UPDATE browser_requests
                SET status=?, url_host=?, url_path=?, updated_at=? WHERE id=?""",
                       (status, host, path, datetime.now(timezone.utc).isoformat(), request_id))

    def _set_status(self, request_id: str, status: str) -> None:
        with self._db() as db:
            db.execute("UPDATE browser_requests SET status=?, updated_at=? WHERE id=?",
                       (status, datetime.now(timezone.utc).isoformat(), request_id))

    def create_approval(self, request_id: str, code: str, digest: str, expires_at) -> None:
        now = datetime.now(timezone.utc).isoformat()
        expires = expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at)
        with self._db() as db:
            db.execute("""INSERT INTO browser_approvals
                (id, request_id, code_hash, action_digest, status, expires_at, created_at)
                VALUES (?,?,?,?, 'pending', ?, ?)""",
                       (str(uuid4()), request_id, _hash(code), digest, expires, now))

    def approval_code_hash(self, request_id: str) -> str:
        with self._db() as db:
            row = db.execute("""SELECT code_hash FROM browser_approvals
                WHERE request_id=? ORDER BY created_at DESC LIMIT 1""", (request_id,)).fetchone()
        if row is None:
            raise ValueError("No approval")
        return row["code_hash"]

    def audit(self, request_id: str, operation: str, outcome: str,
              host: str = "", path: str = "") -> None:
        with self._db() as db:
            db.execute("""INSERT INTO browser_audit
                (id, request_id, operation, url_host, url_path, outcome, created_at)
                VALUES (?,?,?,?,?,?,?)""",
                       (str(uuid4()), request_id, operation, host, path, outcome,
                        datetime.now(timezone.utc).isoformat()))

    def take_replayable(self, chat_id: str, message_id: str) -> dict | None:
        try:
            row = self.get_request(chat_id, message_id)
        except PermissionError:
            return None
        if row["status"] in {"pending", "awaiting_approval"}:
            return row
        return None

    def peek_approval(self, chat_id: str, sender_id: str, code: str, now=None) -> dict | None:
        now = now or datetime.now(timezone.utc)
        with self._db() as db:
            row = db.execute("""SELECT a.id AS approval_id, a.request_id, a.action_digest,
                a.expires_at, a.status AS approval_status, r.chat_id, r.sender_id, r.status,
                r.pending_action
                FROM browser_approvals a JOIN browser_requests r ON r.id=a.request_id
                WHERE a.code_hash=? AND a.status='pending'""", (_hash(code),)).fetchone()
        if row is None or row["chat_id"] != chat_id or row["sender_id"] != sender_id:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            return None
        result = dict(row)
        if result["pending_action"]:
            result["pending_action"] = json.loads(result["pending_action"])
        return result

    def resolve_approval(self, chat_id: str, sender_id: str, code: str, approve: bool,
                         expected_digest: str | None = None, now=None) -> dict:
        now = now or datetime.now(timezone.utc)
        peeked = self.peek_approval(chat_id, sender_id, code, now=now)
        if peeked is None:
            raise PermissionError("Approval is not valid")
        if expected_digest is not None and expected_digest != peeked["action_digest"]:
            raise PermissionError("Approval digest mismatch")
        status = "approved" if approve else "cancelled"
        request_status = "approved" if approve else "cancelled"
        with self._db() as db:
            db.execute("UPDATE browser_approvals SET status=? WHERE id=?",
                       (status, peeked["approval_id"]))
            db.execute("UPDATE browser_requests SET status=?, updated_at=? WHERE id=?",
                       (request_status, datetime.now(timezone.utc).isoformat(),
                        peeked["request_id"]))
        return {"status": request_status, "request_id": peeked["request_id"],
                "digest": peeked["action_digest"], "pending_action": peeked["pending_action"]}
