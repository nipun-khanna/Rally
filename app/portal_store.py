"""Persistent, chat-scoped archive and public portal settings.

The public ID is an opaque bearer link; it is never an iMessage chat GUID.
The archive deliberately lives beside the operational tables without mutating them.
"""

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SECTIONS = {
    "history": True,
    "media": True,
    "analytics": True,
    "plans": True,
    "members": True,
    "activity": True,
    "knowledge": True,
}
THEMES = {"imessage", "midnight", "sage"}


class PortalStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS portal_groups (
                    chat_id TEXT PRIMARY KEY,
                    public_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL DEFAULT '',
                    theme TEXT NOT NULL DEFAULT 'imessage',
                    sections_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_messages (
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    sent_at TEXT NOT NULL,
                    is_from_me INTEGER NOT NULL DEFAULT 0,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    reaction_type TEXT,
                    reaction_to TEXT,
                    PRIMARY KEY(chat_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS portal_messages_time
                    ON portal_messages(chat_id, sent_at, message_id);
                CREATE TABLE IF NOT EXISTS portal_attachments (
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT '',
                    filename TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER,
                    local_path TEXT,
                    status TEXT NOT NULL DEFAULT 'metadata',
                    PRIMARY KEY(chat_id, message_id, attachment_id),
                    FOREIGN KEY(chat_id, message_id)
                        REFERENCES portal_messages(chat_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS portal_imports (
                    chat_id TEXT PRIMARY KEY,
                    cursor TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    imported_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_members (
                    chat_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    PRIMARY KEY(chat_id, sender_id)
                );
                CREATE TABLE IF NOT EXISTS portal_search_cache (
                    chat_id TEXT NOT NULL, query TEXT NOT NULL, results_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(chat_id, query)
                );
                CREATE TABLE IF NOT EXISTS portal_search_quota (
                    chat_id TEXT NOT NULL, day TEXT NOT NULL, request_count INTEGER NOT NULL,
                    PRIMARY KEY(chat_id, day)
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(portal_messages)")}
            if "reaction_type" not in columns:
                db.execute("ALTER TABLE portal_messages ADD COLUMN reaction_type TEXT")
            if "reaction_to" not in columns:
                db.execute("ALTER TABLE portal_messages ADD COLUMN reaction_to TEXT")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _public_id() -> str:
        return secrets.token_urlsafe(24)

    def ensure_group(self, chat_id: str) -> str:
        if not chat_id:
            raise ValueError("chat_id is required")
        with self._db() as db:
            db.execute("""INSERT OR IGNORE INTO portal_groups
                (chat_id, public_id, sections_json, created_at) VALUES (?, ?, ?, ?)""",
                (chat_id, self._public_id(), json.dumps(DEFAULT_SECTIONS), self._now()))
            return db.execute("SELECT public_id FROM portal_groups WHERE chat_id=?",
                              (chat_id,)).fetchone()["public_id"]

    def get_group(self, public_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM portal_groups WHERE public_id=?",
                             (public_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["sections"] = {**DEFAULT_SECTIONS, **json.loads(result.pop("sections_json"))}
        return result

    def hosted_group_public_id(self, prefix: str = "C3Jg") -> str | None:
        """Existing published group archive id, or None. Never invents a new id."""
        if not isinstance(prefix, str) or not prefix:
            return None
        with self._db() as db:
            row = db.execute(
                """SELECT public_id FROM portal_groups
                   WHERE instr(chat_id, ';+;') > 0 AND public_id LIKE ?
                   ORDER BY created_at LIMIT 1""",
                (prefix + "%",)).fetchone()
        return row["public_id"] if row else None

    def group_for_chat(self, chat_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT public_id FROM portal_groups WHERE chat_id=?", (chat_id,)).fetchone()
        return self.get_group(row["public_id"]) if row else None

    def rotate_group(self, chat_id: str) -> str:
        self.ensure_group(chat_id)
        public_id = self._public_id()
        with self._db() as db:
            db.execute("UPDATE portal_groups SET public_id=? WHERE chat_id=?", (public_id, chat_id))
        return public_id

    def update_settings(self, chat_id: str, *, title: str | None = None,
                        theme: str | None = None, sections: dict[str, bool] | None = None) -> dict:
        self.ensure_group(chat_id)
        current = self.group_for_chat(chat_id)
        if sections is not None:
            unknown = set(sections) - set(DEFAULT_SECTIONS)
            if unknown or any(type(value) is not bool for value in sections.values()):
                raise ValueError("Invalid portal sections")
        if theme is not None and theme not in THEMES:
            raise ValueError("Invalid portal theme")
        merged = {**current["sections"], **(sections or {})}
        with self._db() as db:
            db.execute("""UPDATE portal_groups SET title=?, theme=?, sections_json=?
                WHERE chat_id=?""", (current["title"] if title is None else title,
                current["theme"] if theme is None else theme, json.dumps(merged), chat_id))
        return self.group_for_chat(chat_id)

    def set_member(self, chat_id: str, sender_id: str, display_name: str) -> None:
        with self._db() as db:
            db.execute("""INSERT INTO portal_members VALUES (?, ?, ?)
                ON CONFLICT(chat_id, sender_id) DO UPDATE SET
                    display_name=excluded.display_name""", (chat_id, sender_id, display_name))

    def members(self, chat_id: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""SELECT sender_id, display_name FROM portal_members
                WHERE chat_id=? ORDER BY display_name COLLATE NOCASE""", (chat_id,)).fetchall()
        return [dict(row) for row in rows]

    def upsert_messages(self, chat_id: str, messages: list[dict]) -> int:
        """Ingest normalized messages and attachments; return newly inserted count.

        Each message needs message_id and sent_at. Optional keys: sender_id,
        text, is_from_me, is_deleted, attachments. Each attachment needs
        attachment_id; metadata/status may be updated on later passes.
        """
        inserted = 0
        with self._db() as db:
            for message in messages:
                message_id = str(message["message_id"])
                sent_at = message["sent_at"]
                if isinstance(sent_at, datetime):
                    sent_at = sent_at.isoformat()
                existing = db.execute("""SELECT 1 FROM portal_messages
                    WHERE chat_id=? AND message_id=?""", (chat_id, message_id)).fetchone()
                db.execute("""INSERT INTO portal_messages
                    (chat_id, message_id, sender_id, text, sent_at, is_from_me,
                     is_deleted, reaction_type, reaction_to)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    sender_id=excluded.sender_id, text=excluded.text,
                    sent_at=excluded.sent_at, is_from_me=excluded.is_from_me,
                    is_deleted=excluded.is_deleted,
                    reaction_type=excluded.reaction_type,
                    reaction_to=excluded.reaction_to""",
                    (chat_id, message_id, message.get("sender_id") or "",
                     message.get("text") or "", str(sent_at),
                     int(bool(message.get("is_from_me"))),
                     int(bool(message.get("is_deleted"))),
                     message.get("reaction_type"), message.get("reaction_to")))
                inserted += existing is None
                for attachment in message.get("attachments") or []:
                    attachment_id = str(attachment["attachment_id"])
                    db.execute("""INSERT INTO portal_attachments
                        (chat_id, message_id, attachment_id, mime_type, filename,
                         size_bytes, local_path, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(chat_id, message_id, attachment_id) DO UPDATE SET
                        mime_type=excluded.mime_type, filename=excluded.filename,
                        size_bytes=excluded.size_bytes,
                        local_path=COALESCE(excluded.local_path, portal_attachments.local_path),
                        status=CASE WHEN portal_attachments.status='available'
                            AND excluded.local_path IS NULL THEN 'available'
                            ELSE excluded.status END""",
                        (chat_id, message_id, attachment_id,
                         attachment.get("mime_type") or "",
                         attachment.get("filename") or "",
                         attachment.get("size_bytes"), attachment.get("local_path"),
                         attachment.get("status") or "metadata"))
            if messages:
                db.execute("DELETE FROM portal_search_cache WHERE chat_id=?", (chat_id,))
        return inserted

    def list_messages(self, chat_id: str, *, before: str | None = None,
                      limit: int = 100) -> list[dict]:
        limit = max(1, min(limit, 500))
        with self._db() as db:
            if before:
                if "|" in before:
                    sent_at, message_id = before.split("|", 1)
                    rows = db.execute("""SELECT * FROM portal_messages WHERE chat_id=?
                        AND is_deleted=0 AND (sent_at < ? OR (sent_at=? AND message_id<?))
                        ORDER BY sent_at DESC, message_id DESC LIMIT ?""",
                        (chat_id, sent_at, sent_at, message_id, limit)).fetchall()
                else:
                    rows = db.execute("""SELECT * FROM portal_messages WHERE chat_id=?
                        AND is_deleted=0 AND sent_at < ?
                        ORDER BY sent_at DESC, message_id DESC LIMIT ?""",
                        (chat_id, before, limit)).fetchall()
            else:
                rows = db.execute("""SELECT * FROM portal_messages WHERE chat_id=? AND is_deleted=0
                    ORDER BY sent_at DESC, message_id DESC LIMIT ?""",
                    (chat_id, limit)).fetchall()
            result = []
            for row in rows:
                message = dict(row)
                message["is_from_me"] = bool(message["is_from_me"])
                message["is_deleted"] = bool(message["is_deleted"])
                message["attachments"] = [dict(item) for item in db.execute(
                    """SELECT attachment_id, mime_type, filename, size_bytes,
                    local_path, status FROM portal_attachments
                    WHERE chat_id=? AND message_id=? ORDER BY attachment_id""",
                    (chat_id, message["message_id"]))]
                message["reactions"] = [dict(item) for item in db.execute(
                    """SELECT sender_id, reaction_type FROM portal_messages
                    WHERE chat_id=? AND reaction_to=? AND reaction_type IS NOT NULL
                        AND is_deleted=0 ORDER BY sent_at""",
                    (chat_id, message["message_id"]))]
                result.append(message)
        return result

    def get_attachment(self, chat_id: str, attachment_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("""SELECT a.* FROM portal_attachments a
                JOIN portal_messages m ON m.chat_id=a.chat_id AND m.message_id=a.message_id
                WHERE a.chat_id=? AND a.attachment_id=? AND m.is_deleted=0 LIMIT 1""",
                (chat_id, attachment_id)).fetchone()
        return dict(row) if row else None

    def set_import_state(self, chat_id: str, *, cursor: str | None,
                         status: str, error: str | None = None) -> None:
        if status not in {"pending", "running", "complete", "error"}:
            raise ValueError("Invalid import status")
        with self._db() as db:
            db.execute("""INSERT INTO portal_imports
                (chat_id, cursor, status, imported_count, error, updated_at)
                VALUES (?, ?, ?, (SELECT COUNT(*) FROM portal_messages WHERE chat_id=?), ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET cursor=excluded.cursor,
                status=excluded.status, imported_count=excluded.imported_count,
                error=excluded.error, updated_at=excluded.updated_at""",
                (chat_id, cursor, status, chat_id, error, self._now()))

    def import_state(self, chat_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM portal_imports WHERE chat_id=?", (chat_id,)).fetchone()
        return dict(row) if row else {"chat_id": chat_id, "cursor": None,
                                      "status": "pending", "imported_count": 0,
                                      "error": None, "updated_at": None}

    def analytics(self, chat_id: str) -> dict:
        with self._db() as db:
            total = db.execute("""SELECT COUNT(*) FROM portal_messages
                WHERE chat_id=? AND is_deleted=0 AND text!='' AND reaction_type IS NULL""", (chat_id,)).fetchone()[0]
            attachments = db.execute("""SELECT COUNT(*) FROM portal_attachments a
                JOIN portal_messages m ON m.chat_id=a.chat_id AND m.message_id=a.message_id
                WHERE a.chat_id=? AND m.is_deleted=0""", (chat_id,)).fetchone()[0]
            rows = db.execute("""SELECT m.sender_id,
                COALESCE(NULLIF(p.display_name, ''), m.sender_id) AS display_name,
                COUNT(*) AS message_count FROM portal_messages m
                LEFT JOIN portal_members p ON p.chat_id=m.chat_id AND p.sender_id=m.sender_id
                WHERE m.chat_id=? AND m.is_deleted=0 AND m.text!=''
                    AND m.reaction_type IS NULL AND m.sender_id!=''
                GROUP BY m.sender_id ORDER BY message_count DESC, display_name""",
                (chat_id,)).fetchall()
            laughs = db.execute("""SELECT target.sender_id, COUNT(*) AS laugh_count
                FROM portal_messages reaction JOIN portal_messages target
                ON target.chat_id=reaction.chat_id AND target.message_id=reaction.reaction_to
                WHERE reaction.chat_id=? AND reaction.reaction_type IN ('laugh','haha')
                    AND reaction.is_deleted=0 AND target.is_deleted=0
                GROUP BY target.sender_id ORDER BY laugh_count DESC""", (chat_id,)).fetchall()
            reactions = db.execute("""SELECT target.sender_id, COUNT(*) AS reaction_count
                FROM portal_messages reaction JOIN portal_messages target
                ON target.chat_id=reaction.chat_id AND target.message_id=reaction.reaction_to
                WHERE reaction.chat_id=? AND reaction.reaction_type IS NOT NULL
                    AND reaction.is_deleted=0 AND target.is_deleted=0
                GROUP BY target.sender_id ORDER BY reaction_count DESC""", (chat_id,)).fetchall()
            busiest = db.execute("""SELECT substr(sent_at,1,10) AS day, COUNT(*) AS message_count
                FROM portal_messages WHERE chat_id=? AND is_deleted=0 AND text!='' AND reaction_type IS NULL
                GROUP BY day ORDER BY message_count DESC LIMIT 1""", (chat_id,)).fetchone()
        return {"message_count": total, "attachment_count": attachments,
                "by_member": [dict(row) for row in rows],
                "laughs_received": [dict(row) for row in laughs],
                "reactions_received": [dict(row) for row in reactions],
                "busiest_day": dict(busiest) if busiest else None}

    def historical_candidates(self, chat_id: str, query: str, limit: int = 120) -> list[dict]:
        """Find older conversation evidence without changing Rally's tracked plans."""
        import re
        terms = [term for term in re.findall(r"[\w']+", query.lower())
                 if len(term) > 2 and term not in {"the", "for", "what", "were", "our", "old", "past", "plans", "plan", "show", "find"}]
        terms = terms[:6]
        signals = ["plan", "dinner", "lunch", "brunch", "meet", "trip", "movie", "party",
                   "concert", "reservation", "book", "going", "tomorrow", "weekend"]
        patterns = terms or signals
        conditions = " OR ".join("LOWER(m.text) LIKE ?" for _ in patterns)
        params = [chat_id, *[f"%{term}%" for term in patterns], max(1, min(limit, 500))]
        with self._db() as db:
            rows = db.execute(f"""SELECT m.message_id, m.sender_id, m.text, m.sent_at
                FROM portal_messages m WHERE m.chat_id=? AND m.is_deleted=0
                AND m.text!='' AND ({conditions})
                AND NOT EXISTS (SELECT 1 FROM messages live
                    WHERE live.chat_id=m.chat_id AND live.message_id=m.message_id)
                ORDER BY m.sent_at DESC LIMIT ?""", params).fetchall()
        return [dict(row) for row in rows]

    def cached_historical_search(self, chat_id: str, query: str) -> list[dict] | None:
        with self._db() as db:
            row = db.execute("SELECT results_json FROM portal_search_cache WHERE chat_id=? AND query=?",
                             (chat_id, query)).fetchone()
        return json.loads(row["results_json"]) if row else None

    def save_historical_search(self, chat_id: str, query: str, findings: list[dict]) -> None:
        with self._db() as db:
            db.execute("""INSERT INTO portal_search_cache VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, query) DO UPDATE SET results_json=excluded.results_json,
                    created_at=excluded.created_at""",
                (chat_id, query, json.dumps(findings), self._now()))

    def consume_search_quota(self, chat_id: str, day: str, daily_limit: int = 20) -> bool:
        with self._db() as db:
            result = db.execute("""INSERT INTO portal_search_quota VALUES (?, ?, 1)
                ON CONFLICT(chat_id, day) DO UPDATE SET request_count=request_count+1
                WHERE request_count<?""", (chat_id, day, daily_limit))
        return result.rowcount == 1
