"""Conservative local follow-up candidates from explicitly selected messages."""

from datetime import date, datetime, time, timedelta
from hashlib import sha256
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.relationships.store import stamp


def _window(match: str, at: datetime, zone: ZoneInfo):
    """Return a local due window; vague terms intentionally have no invented date."""
    local_at = at.astimezone(zone)
    day = local_at.date()
    key = match.casefold()
    if key == 'next week':
        start_day = day + timedelta(days=7 - day.weekday())
        start = datetime.combine(start_day, time.min, zone)
        return start, start + timedelta(days=7)
    if key == 'tomorrow':
        start = datetime.combine(day + timedelta(days=1), time.min, zone)
        return start, start + timedelta(days=1)
    if key == 'this weekend':
        days_until_saturday = (5 - day.weekday()) % 7
        start = datetime.combine(day + timedelta(days=days_until_saturday), time.min, zone)
        return start, start + timedelta(days=2)
    weekday = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
               'friday': 4, 'saturday': 5, 'sunday': 6}.get(key)
    if weekday is not None:
        offset = (weekday - day.weekday()) % 7 or 7
        start = datetime.combine(day + timedelta(days=offset), time.min, zone)
        return start, start + timedelta(days=1)
    return None, None


def detect_candidates(text: str, at: datetime, zone: str, *, outgoing: bool) -> list[dict]:
    """Extract a small set of owner-relevant obligations without inference calls."""
    if not isinstance(text, str) or not text.strip() or not isinstance(outgoing, bool):
        return []
    if at.tzinfo is None:
        raise ValueError('Message time must include a time zone')
    try:
        tz = ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        raise ValueError('Unknown time zone') from None
    body = text.strip()
    low = body.casefold()
    if re.match(r'^\s*(?:rally\s*:|example\s*:|>+)', body, re.I):
        return []
    if re.search(r"\b(?:won't|will not|can't|cannot|never)\b", low):
        return []
    # Quoted statements are usually examples or pasted text, not fresh commitments.
    if re.search(r'[“"].+[”"]', body):
        return []

    match = None
    kind, action, certainty = 'commitment', 'follow_up', 'medium'
    if re.search(r'\b(?:we should|let\s*\x27?s|let us)\s+(?:get|grab|do)\s+(?:dinner|lunch|coffee|food)\b|\b(?:we should|let\s*\x27?s|let us)\s+hang\b', low):
        kind, action, certainty = 'unfinished_plan', 'make_plan', 'high'
        match = re.search(r'\b(next week|tomorrow|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', low)
    elif re.search(r'\bwe should talk about this later\b|\bwe should talk later\b', low):
        kind, action, certainty = 'commitment', 'talk', 'medium'
        match = re.search(r'\b(next week|tomorrow|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', low)
    elif re.search(r"\bi(?:['’]ll| will)\s+(?:text|call|message|follow up|follow-up)\b", low):
        if not outgoing:
            return []
        kind, action, certainty = 'commitment', 'text', 'high'
        match = re.search(r'\b(next week|tomorrow|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', low)
    elif re.search(r'\blet me know\b', low):
        # Incoming requests assign the owner; outgoing requests assign the recipient.
        if outgoing:
            return []
        kind, action, certainty = 'commitment', 'follow_up', 'medium'
        match = re.search(r'\b(next week|tomorrow|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', low)
    elif re.search(r"\bi(?:['’]ll| will) follow up\b", low):
        if not outgoing:
            return []
        kind, action, certainty = 'commitment', 'follow_up', 'high'
        match = re.search(r'\b(next week|tomorrow|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', low)
    else:
        return []

    start, end = _window(match.group(0), at, tz) if match else (None, None)
    return [{'kind': kind, 'action': action, 'certainty': certainty,
             'window_start': start, 'window_end': end,
             'time_ambiguous': start is None}]


class FollowupStore:
    """Source-owned projections and durable, owner-scoped decisions.

    Integration API: construct with a RelationshipStore, call sync_source(owner, chat_id)
    after a successful source import/rescan transaction, and pass list_for_owner(owner)
    into the private attention projection. decide() uses the candidate's opaque id and
    revision to reject stale UI submissions. This class performs no provider calls.
    """

    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS rel_followups (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL, kind TEXT NOT NULL, action TEXT NOT NULL,
                    certainty TEXT NOT NULL, source_revision TEXT NOT NULL,
                    window_start TEXT, window_end TEXT, time_ambiguous INTEGER NOT NULL,
                    UNIQUE(owner,chat_id,message_id,kind));
                CREATE TABLE IF NOT EXISTS rel_followup_decisions (
                    owner TEXT NOT NULL, followup_id TEXT NOT NULL, source_revision TEXT NOT NULL,
                    status TEXT NOT NULL, due_at TEXT, updated_at TEXT NOT NULL,
                    PRIMARY KEY(owner,followup_id,source_revision));
                CREATE TABLE IF NOT EXISTS rel_followup_source_state (
                    owner TEXT NOT NULL, chat_id TEXT NOT NULL, last_revision INTEGER NOT NULL,
                    PRIMARY KEY(owner,chat_id));
            ''')

    @staticmethod
    def _id(owner, chat_id, message_id, kind):
        value = '\0'.join((owner, chat_id, message_id, kind)).encode()
        return sha256(value).hexdigest()

    @staticmethod
    def _revision(text, sender, at):
        return sha256('\0'.join((text, sender, at)).encode()).hexdigest()

    def sync_source(self, owner: str, chat_id: str):
        with self.store.db() as db:
            source = db.execute('SELECT * FROM rel_sources WHERE owner=? AND chat_id=?',
                                (owner, chat_id)).fetchone()
            if not source:
                old_ids = db.execute('SELECT id FROM rel_followups WHERE owner=? AND chat_id=?',
                                     (owner, chat_id)).fetchall()
                db.executemany('DELETE FROM rel_followup_decisions WHERE owner=? AND followup_id=?',
                               [(owner, row['id']) for row in old_ids])
                db.execute('DELETE FROM rel_followups WHERE owner=? AND chat_id=?', (owner, chat_id))
                db.execute('DELETE FROM rel_followup_source_state WHERE owner=? AND chat_id=?', (owner, chat_id))
                return
            state = db.execute('SELECT last_revision FROM rel_followup_source_state WHERE owner=? AND chat_id=?',
                               (owner, chat_id)).fetchone()
            if state and abs(source['revision'] - state['last_revision']) > 1000:
                # Source registration uses a random revision token; ordinary rescan,
                # enable, and disable transitions increment it by one.
                old_ids = db.execute('SELECT id FROM rel_followups WHERE owner=? AND chat_id=?',
                                     (owner, chat_id)).fetchall()
                db.executemany('DELETE FROM rel_followup_decisions WHERE owner=? AND followup_id=?',
                               [(owner, row['id']) for row in old_ids])
                db.execute('DELETE FROM rel_followups WHERE owner=? AND chat_id=?', (owner, chat_id))
            db.execute('''INSERT INTO rel_followup_source_state(owner,chat_id,last_revision) VALUES(?,?,?)
                ON CONFLICT(owner,chat_id) DO UPDATE SET last_revision=excluded.last_revision''',
                (owner, chat_id, source['revision']))
            if not source['enabled']:
                db.execute('DELETE FROM rel_followups WHERE owner=? AND chat_id=?', (owner, chat_id))
                return
            config = db.execute('SELECT zone FROM rel_config WHERE owner=?', (owner,)).fetchone()
            if not config:
                raise ValueError('Relationship owner has no configured time zone')
            rows = db.execute('''SELECT * FROM rel_texts WHERE owner=? AND chat_id=?
                AND (eligible=1 OR sender<>?) ORDER BY at,message_id''',
                (owner, chat_id, owner)).fetchall()
            current_ids = set()
            for row in rows:
                if not row['text'].strip() or re.match(r'^\s*Rally\s*:', row['text'], re.I):
                    continue
                candidates = detect_candidates(row['text'], datetime.fromisoformat(row['at']),
                                               config['zone'], outgoing=row['sender'] == owner)
                for candidate in candidates:
                    revision = self._revision(row['text'], row['sender'], row['at'])
                    ident = self._id(owner, chat_id, row['message_id'], candidate['kind'])
                    current_ids.add(ident)
                    previous = db.execute('SELECT source_revision FROM rel_followups WHERE id=?',
                                          (ident,)).fetchone()
                    if previous and previous['source_revision'] != revision:
                        db.execute('DELETE FROM rel_followup_decisions WHERE owner=? AND followup_id=?',
                                   (owner, ident))
                    db.execute('''INSERT INTO rel_followups
                        (id,owner,chat_id,message_id,kind,action,certainty,source_revision,
                         window_start,window_end,time_ambiguous)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(owner,chat_id,message_id,kind)
                        DO UPDATE SET action=excluded.action,certainty=excluded.certainty,
                          source_revision=excluded.source_revision,window_start=excluded.window_start,
                          window_end=excluded.window_end,time_ambiguous=excluded.time_ambiguous''',
                        (ident, owner, chat_id, row['message_id'], candidate['kind'], candidate['action'],
                         candidate['certainty'], revision,
                         stamp(candidate['window_start']) if candidate['window_start'] else None,
                         stamp(candidate['window_end']) if candidate['window_end'] else None,
                         int(candidate['time_ambiguous'])) )
            existing = db.execute('SELECT id FROM rel_followups WHERE owner=? AND chat_id=?',
                                  (owner, chat_id)).fetchall()
            for row in existing:
                if row['id'] not in current_ids:
                    db.execute('DELETE FROM rel_followup_decisions WHERE owner=? AND followup_id=?',
                               (owner, row['id']))
                    db.execute('DELETE FROM rel_followups WHERE id=?', (row['id'],))

    def list_for_owner(self, owner: str, *, now: datetime | None = None) -> list[dict]:
        del now  # Kept in the API for dashboard projections that evaluate due windows.
        with self.store.db() as db:
            rows = db.execute('''SELECT f.*, s.revision AS current_source_revision,
                    t.text AS source_text,t.sender AS source_sender,t.at AS source_at,
                    d.status,d.due_at
                FROM rel_followups f JOIN rel_sources s ON s.owner=f.owner AND s.chat_id=f.chat_id
                JOIN rel_texts t ON t.owner=f.owner AND t.chat_id=f.chat_id AND t.message_id=f.message_id
                LEFT JOIN rel_followup_decisions d ON d.owner=f.owner AND d.followup_id=f.id
                    AND d.source_revision=f.source_revision
                WHERE f.owner=? AND s.enabled=1 AND t.text<>''
                  AND (t.eligible=1 OR t.sender<>?) ORDER BY f.window_start,f.message_id''',
                (owner, owner)).fetchall()
            result = []
            for raw in rows:
                row = dict(raw)
                revision = self._revision(row['source_text'], row['source_sender'], row['source_at'])
                if revision != row['source_revision']:
                    continue
                status = row['status'] or 'open'
                if status in ('dismissed', 'done', 'completed'):
                    continue
                result.append({
                    'id': row['id'], 'owner': row['owner'], 'kind': row['kind'],
                    'action': row['action'], 'certainty': row['certainty'],
                    'revision': row['source_revision'],
                    'window_start': datetime.fromisoformat(row['window_start']) if row['window_start'] else None,
                    'window_end': datetime.fromisoformat(row['window_end']) if row['window_end'] else None,
                    'time_ambiguous': bool(row['time_ambiguous']), 'status': status,
                    'due_at': datetime.fromisoformat(row['due_at']) if row['due_at'] else None,
                    'source': {'chat_id': row['chat_id'], 'message_id': row['message_id'],
                               'text': row['source_text'], 'sender': row['source_sender'],
                               'at': datetime.fromisoformat(row['source_at']),
                               'revision': row['current_source_revision']},
                })
            return result

    def decide(self, owner: str, followup_id: str, *, expected_revision: str,
               status: str, due_at: datetime | None = None):
        if status not in ('done', 'completed', 'dismissed', 'snoozed'):
            raise ValueError('Choose done, dismissed, or snoozed')
        if status == 'snoozed' and (due_at is None or due_at.tzinfo is None):
            raise ValueError('Snoozing requires a time-zoned due date')
        with self.store.db() as db:
            row = db.execute('''SELECT f.*,s.enabled,t.text,t.sender,t.at FROM rel_followups f
                JOIN rel_sources s ON s.owner=f.owner AND s.chat_id=f.chat_id
                JOIN rel_texts t ON t.owner=f.owner AND t.chat_id=f.chat_id AND t.message_id=f.message_id
                WHERE f.owner=? AND f.id=?''', (owner, followup_id)).fetchone()
            if not row or not row['enabled'] or row['source_revision'] != expected_revision:
                raise ValueError('Follow-up is no longer current')
            if self._revision(row['text'], row['sender'], row['at']) != expected_revision:
                raise ValueError('Follow-up source has changed')
            db.execute('''INSERT INTO rel_followup_decisions
                (owner,followup_id,source_revision,status,due_at,updated_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(owner,followup_id,source_revision) DO UPDATE SET
                status=excluded.status,due_at=excluded.due_at,updated_at=excluded.updated_at''',
                (owner, followup_id, expected_revision, status,
                 stamp(due_at) if due_at else None, stamp(datetime.now().astimezone())))
