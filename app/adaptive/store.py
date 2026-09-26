"""SQLite state for adaptive requests and reusable, unapproved workflows."""

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class AdaptiveStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS adaptive_requests (
                    id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    text TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL,
                    missing_capability TEXT, capability_proposal_id TEXT,
                    UNIQUE(chat_id, message_id));
                CREATE TABLE IF NOT EXISTS adaptive_steps (
                    request_id TEXT NOT NULL, revision INTEGER NOT NULL, step_index INTEGER NOT NULL,
                    tool TEXT NOT NULL, args TEXT NOT NULL, args_hash TEXT NOT NULL,
                    effect TEXT NOT NULL, status TEXT NOT NULL, approval_message_id TEXT,
                    outcome TEXT, PRIMARY KEY(request_id, revision, step_index),
                    FOREIGN KEY(request_id) REFERENCES adaptive_requests(id));
                CREATE UNIQUE INDEX IF NOT EXISTS adaptive_approval_message
                    ON adaptive_steps(approval_message_id) WHERE approval_message_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS adaptive_workflows (
                    id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, name TEXT NOT NULL,
                    steps TEXT NOT NULL);
            """)
            if 'missing_capability' not in {row['name'] for row in db.execute('PRAGMA table_info(adaptive_requests)')}:
                db.execute('ALTER TABLE adaptive_requests ADD COLUMN missing_capability TEXT')
            if 'capability_proposal_id' not in {row['name'] for row in db.execute('PRAGMA table_info(adaptive_requests)')}:
                db.execute('ALTER TABLE adaptive_requests ADD COLUMN capability_proposal_id TEXT')
            # An in-flight effect may have completed before the process died. Never replay it.
            db.execute("UPDATE adaptive_steps SET status='uncertain' WHERE status='running'")
            db.execute("""UPDATE adaptive_requests SET status='uncertain' WHERE id IN
                (SELECT request_id FROM adaptive_steps WHERE status='uncertain')""")

    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _request(self, db, request_id):
        row = db.execute("SELECT * FROM adaptive_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown request")
        steps = db.execute("""SELECT step_index,tool,args,args_hash,effect,status,approval_message_id,outcome
            FROM adaptive_steps WHERE request_id=? AND revision=? ORDER BY step_index""",
            (request_id, row['revision'])).fetchall()
        return {
            'id': row['id'], 'chat_id': row['chat_id'], 'message_id': row['message_id'],
            'text': row['text'], 'revision': row['revision'], 'status': row['status'],
            'missing_capability': row['missing_capability'],
            'capability_proposal_id': row['capability_proposal_id'],
            'steps': [{**dict(step), 'args': json.loads(step['args']),
                       'outcome': json.loads(step['outcome']) if step['outcome'] else None}
                      for step in steps],
        }

    def create_request(self, chat_id: str, message_id: str, text: str):
        if not all((chat_id, message_id, text)):
            raise ValueError("Request fields must be nonempty")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT OR IGNORE INTO adaptive_requests
                (id, chat_id, message_id, text, revision, status) VALUES (?,?,?,?,1,'pending')""",
                (str(uuid4()), chat_id, message_id, text))
            row = db.execute("SELECT id,text FROM adaptive_requests WHERE chat_id=? AND message_id=?",
                             (chat_id, message_id)).fetchone()
            if row['text'] != text:
                raise ValueError("Message ID already used with different text")
            return self._request(db, row['id'])

    def get_request(self, request_id: str):
        with self._db() as db:
            return self._request(db, request_id)

    def record_missing(self, request_id: str, revision: int, capability: str):
        if not isinstance(capability, str) or not capability.strip() or len(capability) > 120:
            raise ValueError('Invalid missing capability')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            request = self._request(db, request_id)
            if request['revision'] != revision or request['status'] != 'pending':
                raise ValueError('Request is no longer pending')
            db.execute("UPDATE adaptive_requests SET status='blocked',missing_capability=? WHERE id=?",
                       (capability, request_id))
            return self._request(db, request_id)

    def link_proposal(self, request_id: str, revision: int, proposal_id: str):
        if not isinstance(proposal_id, str) or not proposal_id:
            raise ValueError('Invalid proposal ID')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            request = self._request(db, request_id)
            if request['revision'] != revision or request['status'] != 'blocked' or request['capability_proposal_id']:
                raise ValueError('Request cannot link proposal')
            db.execute("""UPDATE adaptive_requests SET status='pending_review',
                capability_proposal_id=? WHERE id=?""", (proposal_id, request_id))
            return self._request(db, request_id)

    def _step(self, db, request_id, index, revision):
        request = self._request(db, request_id)
        if request['revision'] != revision:
            raise ValueError("Stale request revision")
        if index < 0 or index >= len(request['steps']):
            raise ValueError("Unknown step")
        return request, request['steps'][index]

    def set_plan(self, request_id: str, expected_revision: int, steps: list[dict]):
        if not steps or len(steps) > 3:
            raise ValueError("Plan must have one to three steps")
        normalized = []
        for step in steps:
            if set(step) != {'tool', 'args', 'effect'} or step['effect'] not in ('read', 'commitment'):
                raise ValueError("Invalid step")
            if not isinstance(step['tool'], str) or not step['tool'] or not isinstance(step['args'], dict):
                raise ValueError("Invalid step arguments")
            args = _json(step['args'])
            normalized.append((step['tool'], args, hashlib.sha256(args.encode()).hexdigest(), step['effect']))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._request(db, request_id)
            if current['revision'] != expected_revision:
                raise ValueError("Stale request revision")
            if any(step['status'] in ('running', 'uncertain') for step in current['steps']):
                raise ValueError("Cannot replace an in-flight or uncertain plan")
            revision = expected_revision + 1
            db.execute("""UPDATE adaptive_requests SET revision=?, status=?,
                missing_capability=NULL, capability_proposal_id=NULL WHERE id=?""",
                       (revision, 'awaiting_approval' if any(s[3] == 'commitment' for s in normalized)
                        else 'planned', request_id))
            for index, (tool, args, args_hash, effect) in enumerate(normalized):
                db.execute("""INSERT INTO adaptive_steps
                    (request_id,revision,step_index,tool,args,args_hash,effect,status)
                    VALUES (?,?,?,?,?,?,?,'pending')""",
                    (request_id, revision, index, tool, args, args_hash, effect))
            return self._request(db, request_id)

    def approve_step(self, request_id: str, index: int, revision: int,
                     args_hash: str, approval_message_id: str) -> bool:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            _, step = self._step(db, request_id, index, revision)
            if step['args_hash'] != args_hash:
                if step['approval_message_id']:
                    raise ValueError("Approval argument mismatch")
                return False
            if step['effect'] != 'commitment':
                raise ValueError("Read step needs no approval")
            if step['approval_message_id'] == approval_message_id:
                return False
            if step['approval_message_id'] or step['status'] != 'pending':
                raise ValueError("Step already approved or started")
            if not approval_message_id:
                raise ValueError("Approval message required")
            try:
                db.execute("""UPDATE adaptive_steps SET approval_message_id=?
                    WHERE request_id=? AND revision=? AND step_index=?""",
                    (approval_message_id, request_id, revision, index))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Approval message already used") from exc
            return True

    def claim_step(self, request_id: str, index: int, revision: int):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            _, step = self._step(db, request_id, index, revision)
            if step['status'] != 'pending':
                raise ValueError("Step already claimed")
            if step['effect'] == 'commitment' and not step['approval_message_id']:
                raise ValueError("Approval required")
            db.execute("""UPDATE adaptive_steps SET status='running' WHERE
                request_id=? AND revision=? AND step_index=? AND status='pending'""",
                (request_id, revision, index))
            db.execute("UPDATE adaptive_requests SET status='running' WHERE id=?", (request_id,))
            return self._request(db, request_id)['steps'][index]

    def complete_step(self, request_id: str, index: int, status: str, outcome: dict):
        if status not in ('complete', 'failed', 'uncertain') or not isinstance(outcome, dict):
            raise ValueError("Invalid outcome")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            request, step = self._step(db, request_id, index, self._request(db, request_id)['revision'])
            if step['status'] != 'running':
                raise ValueError("Step is not running")
            db.execute("""UPDATE adaptive_steps SET status=?,outcome=?
                WHERE request_id=? AND revision=? AND step_index=?""",
                (status, _json(outcome), request_id, request['revision'], index))
            remaining = db.execute("""SELECT status FROM adaptive_steps WHERE request_id=? AND revision=?""",
                                   (request_id, request['revision'])).fetchall()
            overall = 'failed' if status == 'failed' else ('uncertain' if status == 'uncertain' else
                      ('complete' if all(row['status'] == 'complete' for row in remaining) else
                       'awaiting_approval' if any(s['effect'] == 'commitment' and s['status'] == 'pending'
                                                  for s in request['steps']) else 'planned'))
            db.execute("UPDATE adaptive_requests SET status=? WHERE id=?", (overall, request_id))
            return self._request(db, request_id)

    def save_workflow(self, chat_id: str, name: str, steps: list[dict]):
        if not chat_id or not name or not steps or len(steps) > 3:
            raise ValueError("Invalid workflow")
        sanitized = []
        for step in steps:
            if (set(step) != {'tool', 'args', 'effect'} or
                not isinstance(step['tool'], str) or not step['tool'] or
                not isinstance(step['args'], dict) or step['effect'] not in ('read', 'commitment')):
                raise ValueError("Invalid workflow step")
            sanitized.append({key: step[key] for key in ('tool', 'args', 'effect')})
        workflow_id = str(uuid4())
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO adaptive_workflows VALUES (?,?,?,?)",
                       (workflow_id, chat_id, name, _json(sanitized)))
        return self.get_workflow(workflow_id, chat_id)

    def get_workflow(self, workflow_id: str, chat_id: str):
        with self._db() as db:
            row = db.execute("SELECT * FROM adaptive_workflows WHERE id=? AND chat_id=?",
                             (workflow_id, chat_id)).fetchone()
            if row is None:
                raise ValueError("Unknown workflow")
            return {'id': row['id'], 'chat_id': row['chat_id'], 'name': row['name'],
                    'steps': json.loads(row['steps'])}
