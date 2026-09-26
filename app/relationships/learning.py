"""Selected text history and contact rhythms, computed entirely on this Mac."""

from datetime import datetime, timezone
import math
import re
from statistics import median
from zoneinfo import ZoneInfo

from app.relationships.store import stamp


class RelationshipLearner:
    def __init__(self, store, client=None):
        self.store = store
        self.client = client

    def _normalize(self, owner, item):
        guid, created, text = item.get('guid'), item.get('dateCreated'), item.get('text')
        if not isinstance(guid, str) or not guid or isinstance(created, bool) or not isinstance(created, (int, float)) or not isinstance(item.get('isFromMe'), bool):
            return None
        try:
            at = datetime.fromtimestamp(created / 1000, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
        text = text if isinstance(text, str) else ''
        sender = 'local-imessage-account' if item['isFromMe'] else (item.get('handle') or {}).get('address', '')
        deleted = bool(item.get('isDeleted') or item.get('dateRetracted'))
        usable = bool(sender == owner and text.strip() and not deleted and not item.get('associatedMessageType') and not re.match(r'^\s*Rally\s*:', text, re.I))
        return guid, '' if deleted else text, sender, stamp(at), int(usable)

    def _apply(self, db, source, rows):
        person = dict(db.execute('SELECT * FROM rel_people WHERE id=?', (source['person_id'],)).fetchone())
        old = self.store._anchor(db, person)
        for item in rows:
            normalized = self._normalize(source['owner'], item)
            if normalized:
                guid, text, sender, at, usable = normalized
                db.execute('''INSERT INTO rel_texts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(owner,chat_id,message_id)
                    DO UPDATE SET text=excluded.text,sender=excluded.sender,at=excluded.at,
                    eligible=excluded.eligible,scan=excluded.scan''',
                           (source['owner'], source['chat_id'], guid, text, sender, at, usable, source['scan']))
        return person, old

    def _refresh_anchor(self, db, person, old):
        if self.store._anchor(db, person) != old:
            self.store._cancel(db, person['id'])
            db.execute('UPDATE rel_people SET generation=generation+1,snooze_until=NULL WHERE id=?', (person['id'],))

    def import_page(self, owner: str, chat_id: str, limit: int = 100) -> int:
        if not self.client:
            return 0
        source = next((s for s in self.store.sources(owner) if s['chat_id'] == chat_id), None)
        if not source or not source['enabled'] or source['coverage'] == 'complete':
            return 0
        try:
            rows = self.client.fetch_messages(chat_id, limit=limit, offset=source['cursor'])
        except Exception:
            with self.store.db() as db:
                db.execute("UPDATE rel_sources SET error='History import failed',coverage='error' WHERE owner=? AND chat_id=? AND revision=? AND enabled=1",
                           (owner, chat_id, source['revision']))
            return 0
        with self.store.db() as db:
            current = db.execute('SELECT * FROM rel_sources WHERE owner=? AND chat_id=?', (owner, chat_id)).fetchone()
            if not current or not current['enabled'] or current['revision'] != source['revision'] or current['cursor'] != source['cursor']:
                return 0
            person, old = self._apply(db, source, rows)
            complete = len(rows) < limit
            if complete:
                db.execute('DELETE FROM rel_texts WHERE owner=? AND chat_id=? AND scan!=?', (owner, chat_id, source['scan']))
            self._refresh_anchor(db, person, old)
            db.execute('''UPDATE rel_sources SET cursor=cursor+?,rows_seen=rows_seen+?,coverage=?,last_sync=?,error=NULL
                          WHERE owner=? AND chat_id=?''',
                       (len(rows), len(rows), 'complete' if complete else 'pending', stamp(datetime.now(timezone.utc)), owner, chat_id))
        return len(rows)

    def observe(self, payload: dict) -> None:
        if payload.get('type') not in ('new-message', 'updated-message', 'message-updated'):
            return
        data = payload.get('data')
        if not isinstance(data, dict):
            return
        chats = {c.get('guid') for c in data.get('chats', []) if isinstance(c, dict)}
        with self.store.db() as db:
            for row in db.execute('SELECT * FROM rel_sources WHERE enabled=1').fetchall():
                source = dict(row)
                if source['chat_id'] in chats:
                    person, old = self._apply(db, source, [data])
                    self._refresh_anchor(db, person, old)

    def suggestion(self, owner: str, label: str) -> dict | None:
        person = self.store.person(owner, label)
        zone = ZoneInfo(self.store.config(owner)['zone'])
        dates = {datetime.fromisoformat(e['at']).astimezone(zone).date()
                 for e in self.store.contact_events(owner, label) if e['mode'] == person['mode']}
        source_names = ['confirmed ' + person['mode'] + ' events'] if dates else []
        if person['mode'] == 'message':
            sources = [s for s in self.store.sources(owner) if s['person_id'] == person['id'] and s['enabled']]
            if any(s['coverage'] != 'complete' for s in sources):
                return None
            with self.store.db() as db:
                rows = db.execute('''SELECT t.at FROM rel_texts t JOIN rel_sources s ON s.owner=t.owner AND s.chat_id=t.chat_id
                    WHERE s.owner=? AND s.person_id=? AND s.enabled=1 AND t.eligible=1''', (owner, person['id'])).fetchall()
            dates.update(datetime.fromisoformat(r['at']).astimezone(zone).date() for r in rows)
            if rows:
                source_names.append('selected conversations')
        dates = sorted(dates)
        if len(dates) < 4:
            return None
        days = max(1, min(90, math.floor(median((b - a).days for a, b in zip(dates, dates[1:])) + .5)))
        return {'days': days, 'sample_size': len(dates), 'mode': person['mode'],
                'source': ', '.join(source_names), 'coverage': 'available-history scan'}

    def sync(self, now=None):
        now = now or datetime.now(timezone.utc)
        for source in self.store.sources():
            if not source['enabled']:
                continue
            if source['coverage'] == 'complete':
                last = datetime.fromisoformat(source['last_sync']) if source['last_sync'] else None
                if last and (now - last).total_seconds() < 3600:
                    continue
                self.store.begin_rescan(source['owner'], source['chat_id'])
            self.import_page(source['owner'], source['chat_id'])
