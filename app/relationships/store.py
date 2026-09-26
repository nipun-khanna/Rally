"""Transactional private records and outbox. No portal or group tables are used."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from threading import local
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.relationships.schedule import due_at, eligible


CATEGORIES = ('family', 'parent', 'grandparent', 'sibling', 'cousin',
             'close_friend', 'friend', 'other')

# Sensible default cadence (days) per category when the user doesn't state one.
# Not a claim about anyone's actual relationship -- just a starting point they
# can always override with an explicit "every N days".
DEFAULT_CADENCE_DAYS = {
    'family': 3, 'parent': 3, 'grandparent': 7, 'sibling': 7, 'cousin': 21,
    'close_friend': 7, 'friend': 14, 'other': 30,
}


def stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError('A time zone is required')
    return value.astimezone(timezone.utc).isoformat()


class RelationshipStore:
    def __init__(self, path: Path, *, recover: bool = True):
        self.path = Path(path)
        self._local = local()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS rel_config (
                    owner TEXT PRIMARY KEY, destination TEXT NOT NULL,
                    zone TEXT NOT NULL, hour INTEGER NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS rel_profiles (
                    owner TEXT PRIMARY KEY, zone TEXT NOT NULL, hour INTEGER NOT NULL,
                    revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS rel_people (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, label TEXT NOT NULL,
                    label_key TEXT NOT NULL, mode TEXT NOT NULL, days INTEGER NOT NULL,
                    created_at TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0,
                    snooze_until TEXT, generation INTEGER NOT NULL DEFAULT 1,
                    category TEXT NOT NULL DEFAULT 'other', intention TEXT NOT NULL DEFAULT '',
                    contact_address TEXT,
                    UNIQUE(owner,label_key));
                CREATE TABLE IF NOT EXISTS rel_contacts (
                    owner TEXT NOT NULL, event_id TEXT NOT NULL, person_id TEXT NOT NULL,
                    mode TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(owner,event_id));
                CREATE TABLE IF NOT EXISTS rel_requests (
                    owner TEXT NOT NULL, message_id TEXT NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(owner,message_id));
                CREATE TABLE IF NOT EXISTS rel_outbox (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, destination TEXT NOT NULL,
                    config_revision INTEGER NOT NULL, person_id TEXT,
                    generation INTEGER, cycle_key TEXT NOT NULL, text TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(owner,cycle_key));
                CREATE TABLE IF NOT EXISTS rel_sources (
                    owner TEXT NOT NULL, chat_id TEXT NOT NULL, person_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1,
                    cursor INTEGER NOT NULL DEFAULT 0, scan INTEGER NOT NULL DEFAULT 1,
                    coverage TEXT NOT NULL DEFAULT 'pending', rows_seen INTEGER NOT NULL DEFAULT 0,
                    last_sync TEXT, error TEXT, PRIMARY KEY(owner,chat_id));
                CREATE TABLE IF NOT EXISTS rel_texts (
                    owner TEXT NOT NULL, chat_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    text TEXT NOT NULL, sender TEXT NOT NULL, at TEXT NOT NULL,
                    eligible INTEGER NOT NULL, scan INTEGER NOT NULL,
                    PRIMARY KEY(owner,chat_id,message_id));
            ''')
            # Existing relationship databases predate profile metadata.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(rel_people)')}
            for name, declaration in (
                ('category', "TEXT NOT NULL DEFAULT 'other'"),
                ('intention', "TEXT NOT NULL DEFAULT ''"),
                ('contact_address', 'TEXT'),
            ):
                if name not in columns:
                    db.execute(f'ALTER TABLE rel_people ADD COLUMN {name} {declaration}')
            # A prior process may have died after the transport accepted a send.
            if recover:
                db.execute("UPDATE rel_outbox SET status='uncertain' WHERE status='sending'")

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

    def configure(self, owner: str, destination: str, zone: str, hour: int = 18):
        if not owner.strip() or not destination.startswith('iMessage;-;') or not destination.split(';')[-1] or not 0 <= hour <= 23:
            raise ValueError('Owner, private iMessage destination, and valid hour are required')
        try:
            ZoneInfo(zone)
        except ZoneInfoNotFoundError:
            raise ValueError('Unknown time zone') from None
        with self.db() as db:
            old = db.execute('SELECT * FROM rel_config WHERE owner=?', (owner,)).fetchone()
            if old and (old['destination'], old['zone'], old['hour']) == (destination, zone, hour):
                return
            revision = old['revision'] + 1 if old else 1
            db.execute('INSERT OR REPLACE INTO rel_config VALUES (?,?,?,?,?)',
                       (owner, destination, zone, hour, revision))
            db.execute("UPDATE rel_outbox SET status='canceled' WHERE owner=? AND status='pending'", (owner,))
            db.execute('UPDATE rel_people SET generation=generation+1 WHERE owner=?', (owner,))

    def configs(self) -> list[dict]:
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM rel_config')]

    def config(self, owner: str) -> dict:
        with self.db() as db:
            row = db.execute('SELECT * FROM rel_config WHERE owner=?', (owner,)).fetchone()
            if not row:
                raise ValueError('Personal reminders are not configured')
            return dict(row)

    def ensure_profile(self, owner: str, zone: str, hour: int = 18) -> dict:
        if not owner.strip() or not 0 <= hour <= 23:
            raise ValueError('Owner and valid local hour are required')
        try:
            ZoneInfo(zone)
        except ZoneInfoNotFoundError:
            raise ValueError('Unknown time zone') from None
        with self.db() as db:
            config = db.execute('SELECT * FROM rel_config WHERE owner=?', (owner,)).fetchone()
            if config:
                return dict(config)
            old = db.execute('SELECT * FROM rel_profiles WHERE owner=?', (owner,)).fetchone()
            if old:
                return dict(old)
            db.execute('INSERT INTO rel_profiles VALUES(?,?,?,?)', (owner, zone, hour, 1))
            return {'owner': owner, 'zone': zone, 'hour': hour, 'revision': 1}

    def profile(self, owner: str) -> dict:
        """Return the owner's local profile, preferring configured reminder settings."""
        with self.db() as db:
            row = db.execute('SELECT * FROM rel_config WHERE owner=?', (owner,)).fetchone()
            if row:
                return dict(row)
            row = db.execute('SELECT * FROM rel_profiles WHERE owner=?', (owner,)).fetchone()
            if row:
                return dict(row)
            raise ValueError('Relationship profile is not configured')

    def set_metadata(self, owner: str, label: str, *, category: str, intention: str,
                     contact_address: str | None = None) -> dict:
        categories = {'close_friend', 'family', 'parent', 'sibling', 'cousin',
                      'grandparent', 'friend', 'other'}
        category = category.strip().casefold()
        intention = intention.strip()
        if category not in categories or len(intention) > 500:
            raise ValueError('Choose a supported relationship category and an intention up to 500 characters')
        if contact_address is not None:
            contact_address = contact_address.strip() or None
            if contact_address and len(contact_address) > 320:
                raise ValueError('Contact address must be at most 320 characters')
        with self.db() as db:
            person = self._person(db, owner, label)
            db.execute('UPDATE rel_people SET category=?,intention=?,contact_address=?,generation=generation+1 WHERE id=? AND owner=?',
                       (category, intention, contact_address, person['id'], owner))
            return dict(db.execute('SELECT * FROM rel_people WHERE id=? AND owner=?',
                                   (person['id'], owner)).fetchone())

    def _person(self, db, owner, label):
        row = db.execute('SELECT * FROM rel_people WHERE owner=? AND label_key=?',
                         (owner, label.strip().casefold())).fetchone()
        if row is None:
            raise ValueError('No relationship with that exact name; set it up first')
        return dict(row)

    def person(self, owner, label):
        with self.db() as db:
            return self._person(db, owner, label)

    def _cancel(self, db, person_id):
        db.execute("UPDATE rel_outbox SET status='canceled' WHERE person_id=? AND status='pending'", (person_id,))

    def upsert(self, owner: str, label: str, mode: str, days: int, now: datetime,
               category: str | None = None):
        self.profile(owner)
        label = label.strip()
        if not label or len(label) > 80 or mode not in ('call', 'visit', 'message', 'other') or not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 90:
            raise ValueError('Use a name, a supported contact mode, and a cadence of 1–90 days')
        if category is not None and category not in CATEGORIES:
            raise ValueError('Unsupported relationship category')
        with self.db() as db:
            existing = db.execute('SELECT category FROM rel_people WHERE owner=? AND label_key=?',
                                  (owner, label.casefold())).fetchone()
            resolved_category = (category if category is not None else
                                 (existing['category'] or 'other' if existing else 'other'))
            db.execute('''INSERT INTO rel_people(id,owner,label,label_key,mode,days,created_at,category)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(owner,label_key) DO UPDATE SET
                mode=excluded.mode,days=excluded.days,category=excluded.category,
                generation=rel_people.generation+1,
                snooze_until=NULL''', (str(uuid4()), owner, label, label.casefold(), mode, days,
                                       stamp(now), resolved_category))
            self._cancel(db, self._person(db, owner, label)['id'])

    def set_category(self, owner: str, label: str, category: str):
        if category not in CATEGORIES:
            raise ValueError('Unsupported relationship category')
        with self.db() as db:
            person = self._person(db, owner, label)
            db.execute('UPDATE rel_people SET category=? WHERE id=?', (category, person['id']))

    def _anchor(self, db, person):
        manual = db.execute('SELECT MAX(at) FROM rel_contacts WHERE owner=? AND person_id=? AND mode=?',
                            (person['owner'], person['id'], person['mode'])).fetchone()[0]
        source = None
        if person['mode'] == 'message':
            source = db.execute('''SELECT MAX(t.at) FROM rel_texts t JOIN rel_sources s
                ON s.owner=t.owner AND s.chat_id=t.chat_id WHERE s.owner=? AND s.person_id=?
                AND s.enabled=1 AND t.eligible=1''', (person['owner'], person['id'])).fetchone()[0]
        values = [v for v in (manual, source) if v]
        return max(values) if values else None

    def list_relationships(self, owner: str) -> list[dict]:
        with self.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM rel_people WHERE owner=? ORDER BY label_key', (owner,))]
            for row in rows:
                row['last_confirmed_at'] = self._anchor(db, row)
            return rows

    def contact_stats(self, owner: str, label: str) -> dict:
        """Real message/contact-event frequency for one person; no estimate is invented."""
        with self.db() as db:
            person = self._person(db, owner, label)
            text_rows = db.execute('''SELECT t.at FROM rel_texts t JOIN rel_sources s
                ON s.owner=t.owner AND s.chat_id=t.chat_id WHERE s.owner=? AND s.person_id=?
                AND s.enabled=1 AND t.eligible=1 ORDER BY t.at''',
                (owner, person['id'])).fetchall()
            event_rows = db.execute('SELECT at FROM rel_contacts WHERE owner=? AND person_id=? ORDER BY at',
                                    (owner, person['id'])).fetchall()
        text_dates = [datetime.fromisoformat(r['at']) for r in text_rows]
        event_dates = [datetime.fromisoformat(r['at']) for r in event_rows]
        stats = {'label': person['label'], 'category': person['category'], 'mode': person['mode'],
                 'text_count': len(text_dates), 'confirmed_event_count': len(event_dates),
                 'last_text_at': text_dates[-1].isoformat() if text_dates else None,
                 'last_confirmed_event_at': event_dates[-1].isoformat() if event_dates else None,
                 'texts_per_day_avg': None}
        if len(text_dates) >= 2:
            span_days = max(1, (text_dates[-1] - text_dates[0]).days)
            stats['texts_per_day_avg'] = round(len(text_dates) / span_days, 2)
        return stats

    def confirm(self, owner: str, label: str, mode: str, at: datetime, event_id: str):
        if mode not in ('call', 'visit', 'message', 'other'):
            raise ValueError('Unsupported contact mode')
        with self.db() as db:
            person = self._person(db, owner, label)
            old_anchor = self._anchor(db, person)
            cursor = db.execute('INSERT OR IGNORE INTO rel_contacts VALUES(?,?,?,?,?)',
                                (owner, event_id, person['id'], mode, stamp(at)))
            if cursor.rowcount and self._anchor(db, person) != old_anchor:
                self._cancel(db, person['id'])
                db.execute('UPDATE rel_people SET generation=generation+1,snooze_until=NULL WHERE id=?', (person['id'],))

    def contact_events(self, owner, label) -> list[dict]:
        with self.db() as db:
            person = self._person(db, owner, label)
            return [dict(r) for r in db.execute('SELECT * FROM rel_contacts WHERE owner=? AND person_id=? ORDER BY at', (owner, person['id']))]

    def control(self, owner: str, label: str, action: str, now: datetime, until: datetime | None = None):
        if action not in ('pause', 'resume', 'remove', 'snooze') or (action == 'snooze' and (until is None or until <= now)):
            raise ValueError('Choose pause, resume, remove, or a future snooze date')
        with self.db() as db:
            person = self._person(db, owner, label)
            self._cancel(db, person['id'])
            if action == 'remove':
                db.execute('DELETE FROM rel_contacts WHERE person_id=?', (person['id'],))
                chats = db.execute('SELECT chat_id FROM rel_sources WHERE person_id=?', (person['id'],)).fetchall()
                for row in chats:
                    db.execute('DELETE FROM rel_texts WHERE owner=? AND chat_id=?', (owner, row['chat_id']))
                db.execute('DELETE FROM rel_sources WHERE person_id=?', (person['id'],))
                db.execute('DELETE FROM rel_people WHERE id=?', (person['id'],))
            else:
                paused = 1 if action == 'pause' else 0
                snooze = stamp(until) if action == 'snooze' else None
                db.execute('UPDATE rel_people SET paused=?,snooze_until=?,generation=generation+1 WHERE id=?',
                           (paused, snooze, person['id']))

    def enqueue_due(self, now: datetime) -> int:
        count = 0
        with self.db() as db:
            for row in db.execute('''SELECT p.*, c.destination,c.zone,c.hour,c.revision
                    FROM rel_people p JOIN rel_config c ON p.owner=c.owner WHERE p.paused=0''').fetchall():
                person = dict(row)
                anchor = self._anchor(db, person)
                due = due_at(datetime.fromisoformat(anchor or person['created_at']), person['days'], person['zone'], person['hour'])
                if person['snooze_until']:
                    due = max(due, datetime.fromisoformat(person['snooze_until']))
                if not eligible(now, due, person['zone'], person['hour']):
                    continue
                verb = {'call': 'called', 'visit': 'visited', 'message': 'messaged', 'other': 'connected with'}[person['mode']]
                text = (f"Time to {person['mode']} {person['label']}. Last recorded contact: {anchor[:10]}."
                        if anchor else f"Have you {verb} {person['label']} recently? Your {person['days']}-day reminder is due; I don't have confirmed contact yet.")
                key = f"due:{person['id']}:{person['generation']}:{anchor or person['created_at']}"
                cursor = db.execute('INSERT OR IGNORE INTO rel_outbox VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(uuid4()), person['owner'], person['destination'], person['revision'], person['id'], person['generation'], key, text, 'pending', stamp(now)))
                count += cursor.rowcount
        return count

    def _valid(self, db, row):
        config = db.execute('SELECT * FROM rel_config WHERE owner=?', (row['owner'],)).fetchone()
        if not config or config['revision'] != row['config_revision'] or config['destination'] != row['destination']:
            return False
        if row['person_id']:
            person = db.execute('SELECT * FROM rel_people WHERE owner=? AND id=?', (row['owner'], row['person_id'])).fetchone()
            if not person or person['paused'] or person['generation'] != row['generation']:
                return False
        return True

    def claim_delivery(self, now: datetime) -> dict | None:
        with self.db() as db:
            for row in db.execute("SELECT * FROM rel_outbox WHERE status='pending' ORDER BY rowid").fetchall():
                if not self._valid(db, row):
                    db.execute("UPDATE rel_outbox SET status='canceled' WHERE id=?", (row['id'],))
                    continue
                if row['person_id']:
                    config = db.execute('SELECT zone,hour FROM rel_config WHERE owner=?', (row['owner'],)).fetchone()
                    if now.astimezone(ZoneInfo(config['zone'])).hour < config['hour']:
                        continue
                db.execute("UPDATE rel_outbox SET status='sending' WHERE id=?", (row['id'],))
                return dict(row)
        return None

    def delivery_valid(self, delivery_id: str) -> bool:
        with self.db() as db:
            row = db.execute('SELECT * FROM rel_outbox WHERE id=?', (delivery_id,)).fetchone()
            return bool(row and row['status'] == 'sending' and self._valid(db, row))

    def finish_delivery(self, delivery_id: str, status: str, now: datetime):
        if status not in ('sent', 'uncertain', 'canceled', 'rejected'):
            raise ValueError('Invalid delivery outcome')
        with self.db() as db:
            db.execute("UPDATE rel_outbox SET status=? WHERE id=? AND status='sending'", (status, delivery_id))

    def deliveries(self, owner: str) -> list[dict]:
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM rel_outbox WHERE owner=? ORDER BY rowid', (owner,))]

    def sources(self, owner=None) -> list[dict]:
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM rel_sources' + (' WHERE owner=?' if owner else ''), (owner,) if owner else ())]

    def add_source(self, owner: str, chat_id: str, label: str):
        if not chat_id.startswith(('iMessage;-;', 'iMessage;+;')) or not chat_id.split(';')[-1]:
            raise ValueError('Select an exact iMessage conversation GUID')
        profile = self.profile(owner)
        if chat_id == profile.get('destination'):
            raise ValueError('The reminder conversation cannot be a learning source')
        with self.db() as db:
            person = self._person(db, owner, label)
            existing = db.execute('SELECT * FROM rel_sources WHERE owner=? AND chat_id=?', (owner, chat_id)).fetchone()
            if existing:
                raise ValueError('Source already selected; remove it before changing its relationship')
            # A fresh token prevents a removed/recreated selection matching an old fetch.
            token = uuid4().int & ((1 << 62) - 1)
            db.execute('INSERT INTO rel_sources(owner,chat_id,person_id,revision) VALUES(?,?,?,?)',
                       (owner, chat_id, person['id'], token))

    def set_source(self, owner: str, chat_id: str, action: str):
        if action not in ('disable', 'enable', 'remove'):
            raise ValueError('Choose enable, disable, or remove')
        with self.db() as db:
            row = db.execute('SELECT * FROM rel_sources WHERE owner=? AND chat_id=?', (owner, chat_id)).fetchone()
            if row is None:
                raise ValueError('Source not selected')
            self._cancel(db, row['person_id'])
            db.execute('UPDATE rel_people SET generation=generation+1 WHERE id=?', (row['person_id'],))
            if action == 'remove':
                db.execute('DELETE FROM rel_texts WHERE owner=? AND chat_id=?', (owner, chat_id))
                db.execute('DELETE FROM rel_sources WHERE owner=? AND chat_id=?', (owner, chat_id))
            else:
                db.execute('UPDATE rel_sources SET enabled=?,revision=revision+1 WHERE owner=? AND chat_id=?',
                           (int(action == 'enable'), owner, chat_id))

    def begin_rescan(self, owner: str, chat_id: str):
        with self.db() as db:
            db.execute("UPDATE rel_sources SET cursor=0,scan=scan+1,coverage='pending',rows_seen=0,revision=revision+1 WHERE owner=? AND chat_id=? AND enabled=1", (owner, chat_id))
