import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.models import ChatMessage, Plan, PlanFacts, Proposal, Reservation
from app.policy import plan_state


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, sender_id TEXT NOT NULL,
                    text TEXT NOT NULL, sent_at TEXT NOT NULL, is_from_rally INTEGER NOT NULL,
                    processed INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS messages_chat ON messages(chat_id, sent_at);
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, version INTEGER NOT NULL,
                    facts TEXT NOT NULL, state TEXT NOT NULL, last_human_at TEXT NOT NULL,
                    last_intervention_version INTEGER, pending_proposal_id TEXT);
                CREATE INDEX IF NOT EXISTS plans_chat ON plans(chat_id);
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, version INTEGER NOT NULL,
                    venue_id TEXT NOT NULL, venue_name TEXT NOT NULL, venue_address TEXT NOT NULL,
                    date TEXT NOT NULL, time TEXT NOT NULL, party_size INTEGER NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS approvals (
                    proposal_id TEXT PRIMARY KEY, sender_id TEXT NOT NULL,
                    message_id TEXT UNIQUE NOT NULL, includes_calendar INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS reservations (
                    proposal_id TEXT PRIMARY KEY, confirmation_id TEXT NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calendar_results (
                    proposal_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    event_id TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, text TEXT NOT NULL,
                    kind TEXT NOT NULL, ref_id TEXT, status TEXT NOT NULL, error TEXT);
                CREATE TABLE IF NOT EXISTS provider_quota (
                    day TEXT PRIMARY KEY, request_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS calendar_quota (
                    day TEXT PRIMARY KEY, request_count INTEGER NOT NULL);
            """)
            if "processed" not in {row[1] for row in db.execute("PRAGMA table_info(messages)")}:
                db.execute("ALTER TABLE messages ADD COLUMN processed INTEGER NOT NULL DEFAULT 0")
            if "created_at" not in {row[1] for row in db.execute("PRAGMA table_info(proposals)")}:
                db.execute("ALTER TABLE proposals ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
            if "includes_calendar" not in {row[1] for row in db.execute("PRAGMA table_info(approvals)")}:
                db.execute("ALTER TABLE approvals ADD COLUMN includes_calendar INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def add_message(self, message: ChatMessage) -> bool:
        with self._db() as db:
            result = db.execute(
                """INSERT OR IGNORE INTO messages
                (message_id, chat_id, sender_id, text, sent_at, is_from_rally)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (message.message_id, message.chat_id, message.sender_id, message.text,
                 message.sent_at.isoformat(), int(message.is_from_rally)),
            )
            return result.rowcount == 1

    def is_processed(self, message_id: str) -> bool:
        with self._db() as db:
            row = db.execute("SELECT processed FROM messages WHERE message_id=?", (message_id,)).fetchone()
        return bool(row and row["processed"])

    def mark_processed(self, message_id: str):
        with self._db() as db:
            db.execute("UPDATE messages SET processed=1 WHERE message_id=?", (message_id,))

    def has_unprocessed_prior(self, chat_id: str, message_id: str, sent_at: datetime) -> bool:
        with self._db() as db:
            row = db.execute("""SELECT 1 FROM messages WHERE chat_id=? AND message_id != ?
                AND processed=0 AND sent_at <= ? LIMIT 1""",
                (chat_id, message_id, sent_at.isoformat())).fetchone()
        return row is not None

    def recent_messages(self, chat_id: str, limit: int = 50) -> list[ChatMessage]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY sent_at DESC LIMIT ?", (chat_id, limit)).fetchall()
        return [ChatMessage(r["message_id"], r["chat_id"], r["sender_id"], r["text"],
                            datetime.fromisoformat(r["sent_at"]), bool(r["is_from_rally"])) for r in reversed(rows)]

    def get_plan(self, chat_id: str) -> Plan | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM plans WHERE chat_id=? ORDER BY rowid DESC LIMIT 1", (chat_id,)).fetchone()
        return self._plan(row) if row else None

    def get_plan_by_id(self, plan_id: str) -> Plan | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        return self._plan(row) if row else None

    def plans_for_chat(self, chat_id: str) -> list[Plan]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM plans WHERE chat_id=? ORDER BY rowid DESC", (chat_id,)).fetchall()
        return [self._plan(row) for row in rows]

    def active_plans(self) -> list[Plan]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM plans WHERE state NOT IN ('DONE','ABANDONED')").fetchall()
        return [self._plan(row) for row in rows]

    @staticmethod
    def _plan(row: sqlite3.Row) -> Plan:
        return Plan(row["id"], row["chat_id"], row["version"], PlanFacts(**json.loads(row["facts"])),
                    row["state"], datetime.fromisoformat(row["last_human_at"]),
                    row["last_intervention_version"], row["pending_proposal_id"])

    def save_plan(self, chat_id: str, facts: PlanFacts, last_human_at: datetime) -> Plan:
        previous = self.get_plan(chat_id)
        if previous and previous.state in ("DONE", "ABANDONED"):
            previous = None
        payload = json.dumps(asdict(facts), sort_keys=True)
        def material(f: PlanFacts):
            return (f.goal, f.activity, tuple(f.participants), f.party_size,
                    f.date, f.time, f.earliest_time,
                    f.location, tuple(f.excluded_cuisines), tuple(f.preferred_cuisines),
                    tuple(f.objections),
                    tuple(f.blockers), f.abandoned)
        changed = previous is None or material(previous.facts) != material(facts)
        version = (previous.version + int(changed)) if previous else 1
        pending = previous.pending_proposal_id if previous and not changed else None
        state = (previous.state if previous and not changed else plan_state(facts, bool(pending)))
        plan_id = previous.id if previous else str(uuid4())
        activity_at = last_human_at if changed or not previous else previous.last_human_at
        with self._db() as db:
            if previous:
                if changed and previous.pending_proposal_id:
                    db.execute("UPDATE proposals SET status='stale' WHERE id=?",
                               (previous.pending_proposal_id,))
                    db.execute("""UPDATE outbox SET status='canceled' WHERE kind='proposal'
                        AND ref_id=? AND status IN ('pending','failed')""",
                        (previous.pending_proposal_id,))
                db.execute("""UPDATE plans SET version=?, facts=?, state=?, last_human_at=?,
                    pending_proposal_id=? WHERE id=?""",
                    (version, payload, state, activity_at.isoformat(), pending, plan_id))
            else:
                db.execute("INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (plan_id, chat_id, version, payload, state, activity_at.isoformat(), None, pending))
        return self.get_plan(chat_id)

    def set_state(self, plan_id: str, state: str):
        with self._db() as db:
            db.execute("UPDATE plans SET state=? WHERE id=?", (state, plan_id))

    def mark_intervened(self, plan_id: str, version: int, when: datetime):
        with self._db() as db:
            db.execute("UPDATE plans SET last_intervention_version=? WHERE id=? AND version=?",
                       (version, plan_id, version))

    def save_proposal(self, proposal: Proposal):
        with self._db() as db:
            db.execute("INSERT INTO proposals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (proposal.id, proposal.plan_id, proposal.version, proposal.venue_id,
                        proposal.venue_name, proposal.venue_address, proposal.date, proposal.time,
                        proposal.party_size, proposal.status, proposal.created_at))
            db.execute("UPDATE plans SET pending_proposal_id=?, state='READY' WHERE id=? AND version=?",
                       (proposal.id, proposal.plan_id, proposal.version))

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        return Proposal(*tuple(row)) if row else None

    def latest_proposal(self, plan_id: str) -> Proposal | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM proposals WHERE plan_id=? ORDER BY rowid DESC LIMIT 1",
                             (plan_id,)).fetchone()
        return Proposal(*tuple(row)) if row else None

    def expire_proposal(self, proposal_id: str):
        with self._db() as db:
            db.execute("UPDATE proposals SET status='stale' WHERE id=? AND status='pending'", (proposal_id,))
            db.execute("""UPDATE outbox SET status='canceled' WHERE kind='proposal' AND ref_id=?
                AND status IN ('pending','failed')""", (proposal_id,))
            db.execute("""UPDATE plans SET pending_proposal_id=NULL, state='BLOCKED',
                last_intervention_version=version+1, version=version+1
                WHERE pending_proposal_id=? AND state='READY'""", (proposal_id,))

    def approve(self, proposal_id: str, sender_id: str, message_id: str,
                includes_calendar: bool = False) -> bool:
        with self._db() as db:
            result = db.execute("""INSERT OR IGNORE INTO approvals
                (proposal_id, sender_id, message_id, includes_calendar) VALUES (?, ?, ?, ?)""",
                (proposal_id, sender_id, message_id, int(includes_calendar)))
            return result.rowcount == 1

    def approval(self, proposal_id: str) -> sqlite3.Row | None:
        with self._db() as db:
            return db.execute("SELECT * FROM approvals WHERE proposal_id=?",
                              (proposal_id,)).fetchone()

    def has_approval(self, proposal_id: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM approvals WHERE proposal_id=?",
                              (proposal_id,)).fetchone() is not None

    def reservation(self, proposal_id: str) -> Reservation | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM reservations WHERE proposal_id=?", (proposal_id,)).fetchone()
        return Reservation(*tuple(row)) if row else None

    def save_reservation(self, reservation: Reservation) -> Reservation:
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO reservations VALUES (?, ?, ?)",
                       (reservation.proposal_id, reservation.confirmation_id, reservation.status))
        return self.reservation(reservation.proposal_id)

    def calendar_result(self, proposal_id: str) -> sqlite3.Row | None:
        with self._db() as db:
            return db.execute("SELECT * FROM calendar_results WHERE proposal_id=?",
                              (proposal_id,)).fetchone()

    def save_calendar_result(self, proposal_id: str, status: str,
                             event_id: str | None, error: str | None):
        if status not in ("confirmed", "unconfirmed"):
            raise ValueError("Invalid calendar result status")
        with self._db() as db:
            db.execute("""INSERT INTO calendar_results VALUES (?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET status=excluded.status,
                event_id=excluded.event_id, error=excluded.error
                WHERE calendar_results.status!='confirmed'""",
                (proposal_id, status, event_id, error))

    def queue_message(self, chat_id: str, text: str, kind: str, ref_id: str | None = None) -> str:
        message_id = str(uuid4())
        with self._db() as db:
            db.execute("INSERT INTO outbox VALUES (?, ?, ?, ?, ?, 'pending', NULL)",
                       (message_id, chat_id, text, kind, ref_id))
        return message_id

    def set_delivery(self, message_id: str, status: str, error: str | None = None):
        with self._db() as db:
            db.execute("UPDATE outbox SET status=?, error=? WHERE id=?", (status, error, message_id))

    def pending_messages(self) -> list[sqlite3.Row]:
        with self._db() as db:
            return db.execute("SELECT * FROM outbox WHERE status IN ('pending','failed')").fetchall()

    def actions_for_chat(self, chat_id: str, limit: int = 100) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""SELECT kind, text, status FROM outbox
                WHERE chat_id=? ORDER BY rowid DESC LIMIT ?""",
                (chat_id, max(1, min(limit, 1000)))).fetchall()
        return [dict(row) for row in rows]

    def sent_message(self, kind: str, ref_id: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM outbox WHERE kind=? AND ref_id=? AND status='sent'",
                              (kind, ref_id)).fetchone() is not None

    def has_message(self, kind: str, ref_id: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM outbox WHERE kind=? AND ref_id=?",
                              (kind, ref_id)).fetchone() is not None

    def consume_quota(self, day: str, daily_limit: int) -> bool:
        if daily_limit < 1:
            return False
        with self._db() as db:
            result = db.execute("""INSERT INTO provider_quota(day, request_count) VALUES (?, 1)
                ON CONFLICT(day) DO UPDATE SET request_count=request_count+1
                WHERE request_count < ?""", (day, daily_limit))
            return result.rowcount == 1

    def consume_calendar_quota(self, day: str, daily_limit: int) -> bool:
        if daily_limit < 1:
            return False
        with self._db() as db:
            result = db.execute("""INSERT INTO calendar_quota(day, request_count) VALUES (?, 1)
                ON CONFLICT(day) DO UPDATE SET request_count=request_count+1
                WHERE request_count < ?""", (day, daily_limit))
            return result.rowcount == 1
