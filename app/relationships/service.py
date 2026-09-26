"""Private command handling and durable reminder delivery."""

from datetime import datetime, timezone
import re
from threading import RLock
from uuid import uuid4

from app.policy import explicitly_addresses_rally
from app.relationships.commands import reply
from app.relationships.store import stamp


class RelationshipService:
    def __init__(self, store, send_fn, learner=None):
        self.store = store
        self.send_fn = send_fn
        self.learner = learner
        self._lock = RLock()

    def receive(self, message) -> bool:
        if message.is_from_rally or re.match(r'^\s*Rally\s*:', message.text, re.I) or not explicitly_addresses_rally(message.text):
            return False
        config = next((c for c in self.store.configs() if c['owner'] == message.sender_id and c['destination'] == message.chat_id), None)
        if config is None:
            return False
        with self._lock, self.store.db() as db:
            if db.execute('SELECT 1 FROM rel_requests WHERE owner=? AND message_id=?', (message.sender_id, message.message_id)).fetchone():
                return True
            result = reply(self.store, message.sender_id, message.text, message.message_id, message.sent_at, self.learner)
            db.execute('INSERT INTO rel_requests VALUES(?,?,?)', (message.sender_id, message.message_id, result))
            db.execute('INSERT INTO rel_outbox VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (str(uuid4()), message.sender_id, config['destination'], config['revision'], None, None,
                        'reply:' + message.message_id, 'Rally: ' + result, 'pending', stamp(message.sent_at)))
        self.deliver(message.sent_at)
        return True

    def deliver(self, now):
        with self._lock:
            while item := self.store.claim_delivery(now):
                if not self.store.delivery_valid(item['id']):
                    self.store.finish_delivery(item['id'], 'canceled', now)
                    continue
                try:
                    self.send_fn(item['destination'], item['text'])
                except Exception:
                    # Never persist raw exceptions: URLs can contain credentials.
                    self.store.finish_delivery(item['id'], 'uncertain', now)
                else:
                    self.store.finish_delivery(item['id'], 'sent', now)

    def tick(self, now=None) -> int:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            count = self.store.enqueue_due(now)
            self.deliver(now)
            return count
