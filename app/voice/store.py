"""Pending voice-drafted actions. Shares the main SQLite file; own table only."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import local
from uuid import uuid4


class VoiceActionStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = local()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS voice_actions (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                chat_id TEXT, label TEXT, summary TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)''')

    @contextmanager
    def db(self):
        existing = getattr(self._local, 'db', None)
        if existing is not None:
            yield existing
            return
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            self._local.db = db
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            self._local.db = None
            db.close()

    def create(self, owner: str, kind: str, *, chat_id: str | None, label: str | None,
                summary: str, payload: dict) -> dict:
        if kind not in ('send_message', 'trigger_plan'):
            raise ValueError('Unknown action kind')
        action_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.db() as db:
            db.execute('INSERT INTO voice_actions VALUES (?,?,?,?,?,?,?,?,?)',
                       (action_id, owner, kind, chat_id, label, summary,
                        json.dumps(payload), 'pending', now))
        return {'id': action_id, 'kind': kind, 'chat_id': chat_id, 'label': label,
                'summary': summary, 'payload': payload, 'status': 'pending'}

    def get(self, owner: str, action_id: str) -> dict | None:
        with self.db() as db:
            row = db.execute('SELECT * FROM voice_actions WHERE id=? AND owner=?',
                             (action_id, owner)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        return result

    def resolve(self, owner: str, action_id: str, status: str) -> bool:
        if status not in ('done', 'failed', 'canceled'):
            raise ValueError('Invalid resolution status')
        with self.db() as db:
            cursor = db.execute(
                "UPDATE voice_actions SET status=? WHERE id=? AND owner=? AND status='pending'",
                (status, action_id, owner))
            return cursor.rowcount > 0
