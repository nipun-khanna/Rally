"""Durable outbound call claims and final reports in Rally's SQLite database."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


_SNAPSHOT_STATES = frozenset({
    "collecting", "awaiting_authorization", "authorized", "dialing", "placed",
    "confirmed", "unresolved", "failed", "unknown", "superseded",
})


class CallAttemptStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS voice_call_attempts (
                source_message_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                destination TEXT NOT NULL,
                call_id TEXT UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(voice_call_attempts)")}
            if "purpose" not in columns:
                db.execute(
                    "ALTER TABLE voice_call_attempts ADD COLUMN purpose TEXT NOT NULL DEFAULT ''")
            if "contact_name" not in columns:
                db.execute(
                    "ALTER TABLE voice_call_attempts ADD COLUMN contact_name TEXT NOT NULL DEFAULT ''")
            db.execute("""CREATE TABLE IF NOT EXISTS restaurant_call_snapshots (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                terms_json TEXT NOT NULL,
                terms_digest TEXT NOT NULL,
                state TEXT NOT NULL,
                source_message_id TEXT,
                authorization_message_id TEXT,
                call_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def claim(self, message_id: str, chat_id: str, destination: str, *,
              status: str = "dialing", purpose: str = "", contact_name: str = "") -> bool:
        if status not in {"dialing", "noted"}:
            raise ValueError("Invalid call claim")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            result = db.execute("""INSERT OR IGNORE INTO voice_call_attempts
                (source_message_id, chat_id, destination, call_id, status, created_at, updated_at,
                 purpose, contact_name)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
                (message_id, chat_id, destination or "", status, now, now,
                 (purpose or "")[:1000], (contact_name or "")[:80]))
        return result.rowcount == 1

    def record_result(self, message_id: str, *, call_id: str | None, status: str) -> None:
        if status not in {"queued", "scheduled", "ringing", "in-progress", "forwarding", "ended", "failed"}:
            raise ValueError("Invalid call status")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("""UPDATE voice_call_attempts SET call_id=?, status=?, updated_at=?
                WHERE source_message_id=? AND status='dialing'""",
                (call_id, status, now, message_id))

    def get(self, message_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM voice_call_attempts WHERE source_message_id=?",
                             (message_id,)).fetchone()
        return dict(row) if row else None

    def pending(self, limit: int = 10) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""SELECT * FROM voice_call_attempts
                WHERE call_id IS NOT NULL AND status NOT IN ('ended', 'timed_out')
                ORDER BY created_at LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def unidentified_claims(self, limit: int = 10) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""SELECT * FROM voice_call_attempts
                WHERE status='dialing' AND call_id IS NULL
                ORDER BY created_at LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def abandon_unidentified(self, message_id: str) -> bool:
        """Mark a pre-POST claim failed. Does not create a provider call."""
        with self._db() as db:
            result = db.execute("""UPDATE voice_call_attempts SET status='failed', updated_at=?
                WHERE source_message_id=? AND status='dialing' AND call_id IS NULL""",
                (datetime.now(timezone.utc).isoformat(), message_id))
        return result.rowcount == 1

    def queue_notice(self, chat_id: str, text: str, ref_id: str) -> None:
        with self._db() as db:
            db.execute("""INSERT INTO outbox (id, chat_id, text, kind, ref_id, status, error)
                VALUES (?, ?, ?, 'voice_call_result', ?, 'pending', NULL)""",
                (str(uuid4()), chat_id, text, ref_id))

    def record_status(self, message_id: str, status: str) -> None:
        if status not in {"scheduled", "queued", "ringing", "in-progress", "forwarding"}:
            raise ValueError("Invalid interim call status")
        with self._db() as db:
            db.execute("""UPDATE voice_call_attempts SET status=?, updated_at=?
                WHERE source_message_id=? AND status NOT IN ('ended', 'timed_out')""",
                (status, datetime.now(timezone.utc).isoformat(), message_id))

    def finish_and_queue(self, message_id: str, status: str, text: str) -> bool:
        if status not in {"ended", "timed_out"}:
            raise ValueError("Invalid final call status")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT chat_id, call_id FROM voice_call_attempts
                WHERE source_message_id=? AND status NOT IN ('ended', 'timed_out')""",
                (message_id,)).fetchone()
            if row is None or row["call_id"] is None:
                return False
            db.execute("""UPDATE voice_call_attempts SET status=?, updated_at=?
                WHERE source_message_id=?""",
                (status, datetime.now(timezone.utc).isoformat(), message_id))
            db.execute("""INSERT INTO outbox (id, chat_id, text, kind, ref_id, status, error)
                VALUES (?, ?, ?, 'voice_call_result', ?, 'pending', NULL)""",
                (str(uuid4()), row["chat_id"], text, row["call_id"]))
        return True

    def _restaurant_view(self, row) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        item["terms"] = json.loads(item["terms_json"])
        return item

    def open_restaurant(self, chat_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("""SELECT * FROM restaurant_call_snapshots
                WHERE chat_id=? AND state IN ('collecting', 'awaiting_authorization')
                ORDER BY created_at DESC LIMIT 1""", (chat_id,)).fetchone()
        return self._restaurant_view(row)

    def save_restaurant(self, *, chat_id: str, terms: dict, digest: str, state: str,
                        source_message_id: str) -> dict:
        if state not in _SNAPSHOT_STATES:
            raise ValueError("Invalid restaurant snapshot state")
        now = datetime.now(timezone.utc).isoformat()
        snapshot_id = str(uuid4())
        with self._db() as db:
            db.execute("""UPDATE restaurant_call_snapshots SET state='superseded', updated_at=?
                WHERE chat_id=? AND state IN ('collecting', 'awaiting_authorization')""",
                (now, chat_id))
            db.execute("""INSERT INTO restaurant_call_snapshots
                (id, chat_id, terms_json, terms_digest, state, source_message_id,
                 authorization_message_id, call_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
                (snapshot_id, chat_id, json.dumps(terms, sort_keys=True), digest, state,
                 source_message_id, now, now))
        saved = self._restaurant_by_id(snapshot_id)
        if saved is None:
            raise RuntimeError("restaurant snapshot was not saved")
        return saved

    def update_restaurant(self, snapshot_id: str, **fields) -> dict | None:
        allowed = ("terms_json", "terms_digest", "state", "authorization_message_id", "call_id")
        assignments = []
        values = []
        for key in allowed:
            if key not in fields:
                continue
            if key == "state" and fields[key] not in _SNAPSHOT_STATES:
                raise ValueError("Invalid restaurant snapshot state")
            assignments.append(f"{key}=?")
            values.append(fields[key])
        if not assignments:
            return self._restaurant_by_id(snapshot_id)
        now = datetime.now(timezone.utc).isoformat()
        assignments.append("updated_at=?")
        values.extend((now, snapshot_id))
        with self._db() as db:
            db.execute(
                f"UPDATE restaurant_call_snapshots SET {', '.join(assignments)} WHERE id=?",
                values)
        return self._restaurant_by_id(snapshot_id)

    def restaurant_for_call(self, call_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("""SELECT * FROM restaurant_call_snapshots
                WHERE call_id=? ORDER BY created_at DESC LIMIT 1""", (call_id,)).fetchone()
        return self._restaurant_view(row)

    def restaurant_for_claim(self, message_id: str, chat_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("""SELECT * FROM restaurant_call_snapshots
                WHERE authorization_message_id=?
                ORDER BY updated_at DESC LIMIT 1""", (message_id,)).fetchone()
            if row is None:
                row = db.execute("""SELECT * FROM restaurant_call_snapshots
                    WHERE chat_id=? AND state IN ('collecting', 'awaiting_authorization', 'dialing')
                    ORDER BY updated_at DESC LIMIT 1""", (chat_id,)).fetchone()
        return self._restaurant_view(row)

    def _restaurant_by_id(self, snapshot_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM restaurant_call_snapshots WHERE id=?",
                             (snapshot_id,)).fetchone()
        return self._restaurant_view(row)
