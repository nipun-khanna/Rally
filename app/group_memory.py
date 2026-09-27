"""Small, group-scoped fact memory for chat replies.

Callers must pass a distilled fact, never a full message transcript. This module
also applies a conservative privacy filter before anything is written to disk.
"""

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\w)")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_SENSITIVE = re.compile(
    r"\b(?:passwords?|passcodes?|api[\s_-]?keys?|secret[\s_-]?keys?|access[\s_-]?tokens?|"
    r"social security|ssn|routing number|bank account|credit cards?|debit cards?|"
    r"home address|street address|date of birth|birthday|"
    r"debt|salary|income|mortgage|medical|medication|diagnos(?:is|ed)|diabetes|"
    r"therapy|therapist|pregnan(?:t|cy)|std|sti|hiv|cancer|disabilit(?:y|ies)|"
    r"sexual|sex life|intimat(?:e|ely)|nudes?|porn|"
    r"how to (?:steal|shoplift|rob|hack)|"
    r"shoplift|burgle|counterfeit|hack(?:ing)? into|bypass security|"
    r"forge (?:a )?(?:passport|id|check)|"
    r"make (?:a )?(?:bomb|weapon|bioweapon)|"
    r"buy (?:illegal )?drugs?|sell (?:illegal )?drugs?|"
    r"ricin|anthrax|sarin|csam|child porn)\b",
    re.I,
)
_PROMPT_INJECTION = re.compile(
    r"\b(?:ignore (?:all |any )?(?:previous |prior )?instructions|"
    r"reveal (?:your |the )?(?:system prompt|secrets?)|"
    r"(?:system|developer) (?:message|instruction|prompt))\b",
    re.I,
)


@dataclass(frozen=True)
class MemoryFact:
    chat_id: str
    key: str
    fact: str
    source_message_id: str
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


def eligible_fact(fact: str) -> bool:
    """Reject personal secrets, sensitive topics, unsafe acts and raw-looking text."""
    if not isinstance(fact, str) or not fact or len(fact) > 180:
        return False
    if fact != fact.strip() or any(ord(char) < 32 for char in fact):
        return False
    return not any(pattern.search(fact) for pattern in
                   (_EMAIL, _PHONE, _URL, _SENSITIVE, _PROMPT_INJECTION))


class GroupMemoryStore:
    def __init__(self, path: str | Path, *, max_facts_per_chat: int = 30):
        if type(max_facts_per_chat) is not int or not 1 <= max_facts_per_chat <= 100:
            raise ValueError("max_facts_per_chat must be between 1 and 100")
        self.path = Path(path)
        self.max_facts_per_chat = max_facts_per_chat
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS group_memory_facts (
                    chat_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, fact_key)
                );
                CREATE INDEX IF NOT EXISTS group_memory_recency
                    ON group_memory_facts(chat_id, updated_at DESC);
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

    @staticmethod
    def _identifier(value: str, label: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError(f"invalid {label}")
        if any(ord(char) < 32 for char in value):
            raise ValueError(f"invalid {label}")
        return value.strip()

    @staticmethod
    def _time(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must have a timezone")
        return value.astimezone(timezone.utc).isoformat()

    def upsert_fact(self, chat_id: str, key: str, fact: str,
                    source_message_id: str, observed_at: datetime) -> bool:
        """Save a distilled fact; return False for rejected or unchanged content."""
        chat_id = self._identifier(chat_id, "chat_id")
        key = self._identifier(key, "key").casefold()
        source_message_id = self._identifier(source_message_id, "source_message_id")
        if (len(key) > 80 or not re.fullmatch(r"[a-z0-9][a-z0-9._:-]*", key) or
                _SENSITIVE.search(key.replace("_", " ").replace(".", " "))):
            raise ValueError("key must be a short stable identifier")
        observed = self._time(observed_at)
        if not eligible_fact(fact):
            return False
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT fact, source_message_id, observed_at FROM group_memory_facts "
                "WHERE chat_id=? AND fact_key=?", (chat_id, key),
            ).fetchone()
            if existing and (existing["observed_at"] > observed or
                             (existing["fact"] == fact and
                              existing["source_message_id"] == source_message_id)):
                return False
            if not existing:
                duplicate = db.execute(
                    "SELECT 1 FROM group_memory_facts WHERE chat_id=? AND fact=?",
                    (chat_id, fact),
                ).fetchone()
                if duplicate:
                    return False
            db.execute("""
                INSERT INTO group_memory_facts
                    (chat_id, fact_key, fact, source_message_id, observed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, fact_key) DO UPDATE SET
                    fact=excluded.fact,
                    source_message_id=excluded.source_message_id,
                    observed_at=excluded.observed_at,
                    updated_at=excluded.updated_at
            """, (chat_id, key, fact, source_message_id, observed, now, now))
            db.execute("""
                DELETE FROM group_memory_facts
                WHERE chat_id=? AND fact_key NOT IN (
                    SELECT fact_key FROM group_memory_facts WHERE chat_id=?
                    ORDER BY updated_at DESC, observed_at DESC, fact_key DESC LIMIT ?
                )
            """, (chat_id, chat_id, self.max_facts_per_chat))
        return True

    def list_facts(self, chat_id: str, *, limit: int | None = None) -> list[MemoryFact]:
        chat_id = self._identifier(chat_id, "chat_id")
        if limit is None:
            limit = self.max_facts_per_chat
        if type(limit) is not int or not 1 <= limit <= self.max_facts_per_chat:
            raise ValueError("invalid limit")
        with self._db() as db:
            rows = db.execute("""
                SELECT * FROM group_memory_facts WHERE chat_id=?
                ORDER BY updated_at DESC, observed_at DESC, fact_key DESC LIMIT ?
            """, (chat_id, limit)).fetchall()
        return [MemoryFact(row["chat_id"], row["fact_key"], row["fact"],
                           row["source_message_id"],
                           datetime.fromisoformat(row["observed_at"]),
                           datetime.fromisoformat(row["created_at"]),
                           datetime.fromisoformat(row["updated_at"])) for row in rows]

    def prompt_context(self, chat_id: str, *, limit: int = 12) -> str:
        """Return compact facts for a prompt without source identifiers."""
        limit = min(limit, self.max_facts_per_chat)
        return "\n".join(f"- {item.fact}" for item in self.list_facts(chat_id, limit=limit))

    def forget(self, chat_id: str, key: str | None = None) -> int:
        """Remove one fact or all facts in a group; return number removed."""
        chat_id = self._identifier(chat_id, "chat_id")
        if key is not None:
            key = self._identifier(key, "key").casefold()
        with self._db() as db:
            if key is None:
                result = db.execute("DELETE FROM group_memory_facts WHERE chat_id=?", (chat_id,))
            else:
                result = db.execute("DELETE FROM group_memory_facts WHERE chat_id=? AND fact_key=?",
                                    (chat_id, key))
            return result.rowcount

    def forget_fact(self, chat_id: str, fact: str) -> int:
        """Remove facts whose stored text equals this phrase. Substrings do not match."""
        chat_id = self._identifier(chat_id, "chat_id")
        if not isinstance(fact, str) or not fact.strip() or len(fact) > 180:
            return 0
        needle = fact.strip()
        with self._db() as db:
            result = db.execute(
                "DELETE FROM group_memory_facts WHERE chat_id=? AND lower(fact)=lower(?)",
                (chat_id, needle),
            )
            return result.rowcount
