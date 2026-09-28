"""Per-group knowledge base: short, positive/neutral facts about members, built from chat.

The KB is never fed wholesale into Rally's reply prompt. It is exported to the group
page and to the page's KB chat function only.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.group_memory import _EMAIL, _PHONE, _PROMPT_INJECTION, _URL

logger = logging.getLogger(__name__)

GROUP_SUBJECT = "__group__"
CATEGORIES = ("food", "dietary", "activities", "personality", "dates",
              "places", "gifts", "likes", "dislikes", "other")
MAX_PER_PERSON = 25
MAX_GROUP = 20

_SECRETS = re.compile(
    r"\b(?:passwords?|passcodes?|api[\s_-]?keys?|access[\s_-]?tokens?|ssn|social security|"
    r"routing number|bank account|credit cards?|debit cards?|home address|street address|"
    r"salary|income|debt|mortgage|sexual|sex life|nudes?|porn|intimat(?:e|ely)|"
    r"shoplift|steal|drugs?|hack(?:ing)? into|weapon|bomb)\b", re.I)
_NEGATIVE = re.compile(
    r"\b(?:rude|irritabl\w*|annoying|lazy|mean|toxic|cheap|fake|stupid|dumb|ugly|fat|"
    r"selfish|arrogant|boring|weird|creepy|jerk|asshole|bitch\w*|dick|idiot|moody|"
    r"flak(?:e|y)|unreliable|liar|lies|gossip\w*|clingy|needy|obnoxious|awkward|"
    r"cringe|lame|loser|mid|trash|hates? (?:everyone|people))\b", re.I)


def eligible_kb_fact(fact: str) -> bool:
    """Allow allergies, dietary needs, birthdays and events; reject secrets,
    contact details, injection attempts, and negative judgments about people."""
    if not isinstance(fact, str) or not fact or len(fact) > 180:
        return False
    if fact != fact.strip() or any(ord(c) < 32 for c in fact):
        return False
    return not any(p.search(fact) for p in
                   (_EMAIL, _PHONE, _URL, _PROMPT_INJECTION, _SECRETS, _NEGATIVE))


class KnowledgeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS kb_facts (
                    chat_id TEXT NOT NULL, subject_id TEXT NOT NULL, fact_key TEXT NOT NULL,
                    category TEXT NOT NULL, fact TEXT NOT NULL, source_message_id TEXT NOT NULL,
                    confidence REAL NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, subject_id, fact_key));
                CREATE TABLE IF NOT EXISTS kb_links (
                    chat_id TEXT NOT NULL, member_a TEXT NOT NULL, member_b TEXT NOT NULL,
                    shared TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, member_a, member_b, shared));
                CREATE TABLE IF NOT EXISTS kb_cursor (
                    chat_id TEXT PRIMARY KEY, last_message_at TEXT NOT NULL,
                    last_message_id TEXT NOT NULL, updated_at TEXT NOT NULL);
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def upsert_fact(self, chat_id: str, subject_id: str, key: str, category: str,
                    fact: str, source_message_id: str, confidence: float) -> bool:
        key = key.strip().casefold()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,79}", key) or not eligible_kb_fact(fact):
            return False
        category = category if category in CATEGORIES else "other"
        confidence = max(0.0, min(1.0, float(confidence)))
        now = datetime.now(timezone.utc).isoformat()
        cap = MAX_GROUP if subject_id == GROUP_SUBJECT else MAX_PER_PERSON
        with self._db() as db:
            db.execute("""INSERT INTO kb_facts VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(chat_id, subject_id, fact_key) DO UPDATE SET
                    category=excluded.category, fact=excluded.fact,
                    source_message_id=excluded.source_message_id,
                    confidence=excluded.confidence, updated_at=excluded.updated_at""",
                       (chat_id, subject_id, key, category, fact, source_message_id,
                        confidence, now, now))
            db.execute("""DELETE FROM kb_facts WHERE chat_id=? AND subject_id=? AND fact_key IN (
                    SELECT fact_key FROM kb_facts WHERE chat_id=? AND subject_id=?
                    ORDER BY confidence DESC, updated_at DESC LIMIT -1 OFFSET ?)""",
                       (chat_id, subject_id, chat_id, subject_id, cap))
        return True

    def remove_fact(self, chat_id: str, subject_id: str, key: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM kb_facts WHERE chat_id=? AND subject_id=? AND fact_key=?",
                              (chat_id, subject_id, key.strip().casefold())).rowcount > 0

    def forget_matching(self, chat_id: str, phrase: str, subject_id: str | None = None) -> int:
        phrase = phrase.strip().casefold()
        if len(phrase) < 3:
            return 0
        sql = "DELETE FROM kb_facts WHERE chat_id=? AND lower(fact) LIKE ?"
        args: list = [chat_id, f"%{phrase}%"]
        if subject_id:
            sql += " AND subject_id=?"
            args.append(subject_id)
        with self._db() as db:
            return db.execute(sql, args).rowcount

    def add_link(self, chat_id: str, member_a: str, member_b: str, shared: str) -> bool:
        if member_a == member_b or not eligible_kb_fact(shared):
            return False
        a, b = sorted((member_a, member_b))
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO kb_links VALUES (?,?,?,?,?)",
                       (chat_id, a, b, shared, datetime.now(timezone.utc).isoformat()))
        return True

    def facts(self, chat_id: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""SELECT subject_id, fact_key, category, fact, confidence, updated_at
                FROM kb_facts WHERE chat_id=? ORDER BY subject_id, category, confidence DESC""",
                              (chat_id,)).fetchall()
        return [dict(r) for r in rows]

    def links(self, chat_id: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT member_a, member_b, shared FROM kb_links WHERE chat_id=? "
                              "ORDER BY updated_at DESC LIMIT 30", (chat_id,)).fetchall()
        return [dict(r) for r in rows]

    def cursor(self, chat_id: str) -> tuple[str, str] | None:
        with self._db() as db:
            row = db.execute("SELECT last_message_at, last_message_id FROM kb_cursor WHERE chat_id=?",
                             (chat_id,)).fetchone()
        return (row["last_message_at"], row["last_message_id"]) if row else None

    def set_cursor(self, chat_id: str, sent_at: str, message_id: str) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO kb_cursor VALUES (?,?,?,?)",
                       (chat_id, sent_at, message_id, datetime.now(timezone.utc).isoformat()))


class KnowledgeBuilder:
    """Feed archive messages after the cursor to the model in batches; save validated facts."""

    def __init__(self, store: KnowledgeStore, portal_store, agent, *, batch_size: int = 50,
                 owner_id: str = "local-imessage-account", owner_name: str = ""):
        self.store = store
        self.portal_store = portal_store
        self.agent = agent
        self.batch_size = batch_size
        self.owner_id = owner_id
        self.owner_name = owner_name

    def _members(self, chat_id: str) -> dict[str, str]:
        members = {m["sender_id"]: m["display_name"] for m in self.portal_store.members(chat_id)}
        members.setdefault(self.owner_id, self.owner_name or "Group owner")
        return members

    def _pending(self, chat_id: str) -> list[dict]:
        cursor = self.store.cursor(chat_id)
        messages = []
        before = None
        while True:
            page = self.portal_store.list_messages(chat_id, before=before, limit=500)
            if not page:
                break
            for m in page:
                if cursor and (m["sent_at"], m["message_id"]) <= cursor:
                    return list(reversed(messages))
                text = (m.get("text") or "").strip()
                if (text and not m.get("reaction_type") and not m.get("is_deleted")
                        and not text.casefold().startswith("rally:")):
                    messages.append(m)
            last = page[-1]
            before = f'{last["sent_at"]}|{last["message_id"]}'
            if len(page) < 500:
                break
        return list(reversed(messages))

    def run(self, chat_id: str, max_batches: int | None = None) -> int:
        members = self._members(chat_id)
        pending = self._pending(chat_id)
        saved = 0
        for index in range(0, len(pending), self.batch_size):
            if max_batches is not None and index // self.batch_size >= max_batches:
                break
            batch = pending[index:index + self.batch_size]
            current = self.store.facts(chat_id)
            try:
                result = self.agent.extract_knowledge(
                    [{"id": m["message_id"], "sender_id": m["sender_id"],
                      "sender": members.get(m["sender_id"], m["sender_id"]),
                      "text": m["text"][:500]} for m in batch],
                    members, [{"subject_id": f["subject_id"], "key": f["fact_key"], "fact": f["fact"]}
                              for f in current])
            except Exception:
                # Don't let one slow/failed batch (e.g. a timeout) block every later batch in
                # this backlog; skip it, advance the cursor past it, and keep going.
                logger.exception("Knowledge extraction failed for one batch; skipping it")
                last = batch[-1]
                self.store.set_cursor(chat_id, last["sent_at"], last["message_id"])
                continue
            ids = {m["message_id"] for m in batch}
            valid_subjects = set(members) | {GROUP_SUBJECT}
            for item in result.facts:
                if item.subject_id in valid_subjects and item.source_message_id in ids:
                    saved += self.store.upsert_fact(chat_id, item.subject_id, item.key, item.category,
                                                    item.fact, item.source_message_id, item.confidence)
            for item in result.removals:
                if item.subject_id in valid_subjects:
                    self.store.remove_fact(chat_id, item.subject_id, item.key)
            for link in result.links:
                if link.member_a in members and link.member_b in members:
                    self.store.add_link(chat_id, link.member_a, link.member_b, link.shared)
            last = batch[-1]
            self.store.set_cursor(chat_id, last["sent_at"], last["message_id"])
        return saved


class DebouncedKnowledgeRunner:
    """Run incremental KB work off the message path, coalescing short bursts.

    A message that arrives during a run or cooldown marks the chat dirty and gets
    one trailing run. This prevents a busy group from creating one model request
    per text while ensuring the newest message is not silently skipped.
    """

    def __init__(self, builder: KnowledgeBuilder, on_change=None, interval: float = 60.0):
        self.builder = builder
        self.on_change = on_change
        self.interval = interval
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._dirty: set[str] = set()
        self._timers: dict[str, threading.Timer] = {}
        self._last: dict[str, float] = {}

    def __call__(self, chat_id: str) -> None:
        with self._lock:
            self._dirty.add(chat_id)
            self._start_or_schedule_locked(chat_id)

    def _start_or_schedule_locked(self, chat_id: str) -> None:
        if chat_id in self._running or chat_id not in self._dirty:
            return
        remaining = self.interval - (time.monotonic() - self._last.get(chat_id, float("-inf")))
        if remaining > 0:
            if chat_id not in self._timers:
                timer = threading.Timer(remaining, self._timer_fired, args=(chat_id,))
                timer.daemon = True
                self._timers[chat_id] = timer
                timer.start()
            return
        self._dirty.discard(chat_id)
        self._running.add(chat_id)
        self._last[chat_id] = time.monotonic()
        threading.Thread(target=self._run, args=(chat_id,), daemon=True,
                         name="rally-knowledge").start()

    def _timer_fired(self, chat_id: str) -> None:
        with self._lock:
            self._timers.pop(chat_id, None)
            self._start_or_schedule_locked(chat_id)

    def _run(self, chat_id: str) -> None:
        try:
            if self.builder.run(chat_id) and self.on_change:
                self.on_change()
        except Exception:
            logger.exception("Knowledge update failed")
        finally:
            with self._lock:
                self._running.discard(chat_id)
                self._start_or_schedule_locked(chat_id)
