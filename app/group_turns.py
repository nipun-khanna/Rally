"""Persisted per-group conversation turns, reply caps, and reaction idempotency."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


TURN_TTL = timedelta(minutes=5)
REPLY_WINDOW = timedelta(minutes=1)
MAX_REPLIES_PER_WINDOW = 3
COALESCE_WINDOW = timedelta(seconds=15)


class GroupTurnStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS group_turns (
                    chat_id TEXT PRIMARY KEY,
                    opened_by_message_id TEXT NOT NULL,
                    last_relevant_at TEXT NOT NULL,
                    last_source_message_id TEXT NOT NULL,
                    last_inbound_text TEXT,
                    closed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS group_turn_replies (
                    chat_id TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS group_turn_replies_chat
                    ON group_turn_replies(chat_id, sent_at);
                CREATE TABLE IF NOT EXISTS group_turn_reactions (
                    message_id TEXT PRIMARY KEY,
                    reaction TEXT NOT NULL DEFAULT ''
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(group_turn_reactions)")}
            if "reaction" not in columns:
                db.execute("ALTER TABLE group_turn_reactions ADD COLUMN reaction TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _time(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()

    def open(self, chat_id: str, message_id: str, at: datetime, text: str = "") -> None:
        stamp = self._time(at)
        with self._db() as db:
            db.execute("""
                INSERT INTO group_turns
                    (chat_id, opened_by_message_id, last_relevant_at, last_source_message_id,
                     last_inbound_text, closed)
                VALUES (?, ?, ?, ?, ?, 0)
                ON CONFLICT(chat_id) DO UPDATE SET
                    opened_by_message_id=excluded.opened_by_message_id,
                    last_relevant_at=excluded.last_relevant_at,
                    last_source_message_id=excluded.last_source_message_id,
                    last_inbound_text=excluded.last_inbound_text,
                    closed=0
            """, (chat_id, message_id, stamp, message_id, text.casefold().strip()))

    def touch(self, chat_id: str, message_id: str, at: datetime, text: str = "") -> None:
        stamp = self._time(at)
        with self._db() as db:
            db.execute("""
                UPDATE group_turns SET last_relevant_at=?, last_source_message_id=?,
                    last_inbound_text=?, closed=0 WHERE chat_id=?
            """, (stamp, message_id, text.casefold().strip(), chat_id))

    def close(self, chat_id: str) -> None:
        with self._db() as db:
            db.execute("UPDATE group_turns SET closed=1 WHERE chat_id=?", (chat_id,))

    def active(self, chat_id: str, now: datetime) -> bool:
        with self._db() as db:
            row = db.execute("SELECT closed, last_relevant_at FROM group_turns WHERE chat_id=?",
                             (chat_id,)).fetchone()
        if row is None or row["closed"]:
            return False
        last = datetime.fromisoformat(row["last_relevant_at"])
        return now - last <= TURN_TTL

    def should_coalesce(self, chat_id: str, text: str, now: datetime) -> bool:
        with self._db() as db:
            row = db.execute(
                "SELECT closed, last_relevant_at, last_inbound_text FROM group_turns WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
        if row is None or row["closed"] or not row["last_inbound_text"]:
            return False
        if row["last_inbound_text"] != text.casefold().strip():
            return False
        last = datetime.fromisoformat(row["last_relevant_at"])
        return now - last <= COALESCE_WINDOW

    def mark_relevant(self, chat_id: str, message_id: str, at: datetime, text: str = "") -> None:
        if self.active(chat_id, at):
            self.touch(chat_id, message_id, at, text)
        else:
            self.open(chat_id, message_id, at, text)

    def allow_reply(self, chat_id: str, now: datetime) -> bool:
        stamp = self._time(now)
        cutoff = self._time(now - REPLY_WINDOW)
        with self._db() as db:
            db.execute("DELETE FROM group_turn_replies WHERE chat_id=? AND sent_at < ?",
                       (chat_id, cutoff))
            count = db.execute("SELECT COUNT(*) AS n FROM group_turn_replies WHERE chat_id=?",
                               (chat_id,)).fetchone()["n"]
            if count >= MAX_REPLIES_PER_WINDOW:
                return False
            db.execute("INSERT INTO group_turn_replies (chat_id, sent_at) VALUES (?, ?)",
                       (chat_id, stamp))
            return True

    def last_reaction(self, message_id: str) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT reaction FROM group_turn_reactions WHERE message_id=?",
                             (message_id,)).fetchone()
        if row is None or not row["reaction"]:
            return None
        return row["reaction"]

    def remember_reaction(self, message_id: str, reaction: str | None) -> None:
        stored = reaction or ""
        with self._db() as db:
            db.execute("""
                INSERT INTO group_turn_reactions (message_id, reaction) VALUES (?, ?)
                ON CONFLICT(message_id) DO UPDATE SET reaction=excluded.reaction
            """, (message_id, stored))
