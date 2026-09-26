from datetime import datetime, timedelta, timezone

from app.relationships.store import RelationshipStore
from app.relationships.learning import RelationshipLearner


OWNER = 'local-imessage-account'
CHAT = 'iMessage;-;friend'
NOW = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)


def item(day, ident=None, mine=True, **extra):
    return {'guid': ident or f'm{day}', 'text': 'hello', 'isFromMe': mine,
            'dateCreated': int((NOW + timedelta(days=day)).timestamp() * 1000),
            'handle': {'address': 'friend'}, 'chats': [{'guid': CHAT}], **extra}


def setup(tmp_path, client=None):
    store = RelationshipStore(tmp_path / 'r.sqlite3')
    store.configure(OWNER, 'iMessage;-;private', 'UTC', 18)
    store.upsert(OWNER, 'Friend', 'message', 7, NOW)
    store.add_source(OWNER, CHAT, 'Friend')
    return store, RelationshipLearner(store, client)


class Pages:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_messages(self, chat_id, limit, offset):
        self.calls.append((chat_id, offset))
        return self.rows[offset:offset + limit]


def test_full_pages_restart_and_local_pattern(tmp_path):
    client = Pages([item(day) for day in (0, 7, 14, 21)])
    store, learner = setup(tmp_path, client)
    assert learner.import_page(OWNER, CHAT, 2) == 2
    assert learner.suggestion(OWNER, 'Friend') is None
    learner = RelationshipLearner(store, client)
    assert learner.import_page(OWNER, CHAT, 2) == 2
    assert learner.import_page(OWNER, CHAT, 2) == 0
    suggestion = learner.suggestion(OWNER, 'Friend')
    assert suggestion['days'] == 7 and suggestion['sample_size'] == 4
    assert store.sources(OWNER)[0]['coverage'] == 'complete'
    assert client.calls == [(CHAT, 0), (CHAT, 2), (CHAT, 4)]
    assert store.list_relationships(OWNER)[0]['last_confirmed_at'].startswith('2026-09-22')


def test_only_outbound_human_days_are_evidence(tmp_path):
    rows = [item(day) for day in (0, 7, 14, 21)] + [item(28, mine=False),
        item(35, text='Rally: reminder'), item(42, associatedMessageType=2001),
        item(49, isDeleted=True), item(21, ident='duplicate-day')]
    store, learner = setup(tmp_path, Pages(rows))
    learner.import_page(OWNER, CHAT)
    suggestion = learner.suggestion(OWNER, 'Friend')
    assert suggestion['sample_size'] == 4
    assert suggestion['days'] == 7
    learner.observe({'type': 'new-message', 'data': item(56, mine=False)})
    assert learner.suggestion(OWNER, 'Friend')['sample_size'] == 4


def test_disable_remove_and_manual_events(tmp_path):
    store, learner = setup(tmp_path, Pages([item(day) for day in (0, 7, 14, 21)]))
    learner.import_page(OWNER, CHAT)
    store.confirm(OWNER, 'Friend', 'message', NOW, 'manual')
    store.set_source(OWNER, CHAT, 'disable')
    assert learner.suggestion(OWNER, 'Friend') is None
    learner.observe({'type': 'new-message', 'data': item(56)})
    assert store.list_relationships(OWNER)[0]['last_confirmed_at'].startswith('2026-09-01')
    assert learner.import_page(OWNER, CHAT) == 0
    store.set_source(OWNER, CHAT, 'remove')
    assert store.sources(OWNER) == []
    with store.db() as db:
        assert db.execute('SELECT COUNT(*) FROM rel_texts').fetchone()[0] == 0
    assert len(store.contact_events(OWNER, 'Friend')) == 1


def test_disabling_during_fetch_prevents_ingestion(tmp_path):
    store, learner = setup(tmp_path)
    class DisablingClient:
        def fetch_messages(self, chat_id, limit, offset):
            store.set_source(OWNER, CHAT, 'disable')
            return [item(1)]
    learner.client = DisablingClient()
    assert learner.import_page(OWNER, CHAT) == 0
    with store.db() as db:
        assert db.execute('SELECT COUNT(*) FROM rel_texts').fetchone()[0] == 0


def test_live_contact_cancels_stale_due_message_only(tmp_path):
    store, learner = setup(tmp_path, Pages([]))
    learner.import_page(OWNER, CHAT)
    store.upsert(OWNER, 'Mom', 'call', 7, NOW)
    due = NOW + timedelta(days=7)
    assert store.enqueue_due(due) == 2
    learner.observe({'type': 'new-message', 'data': item(7)})
    rows = store.deliveries(OWNER)
    assert next(r for r in rows if 'Friend' in r['text'])['status'] == 'canceled'
    assert next(r for r in rows if 'Mom' in r['text'])['status'] == 'pending'


def test_complete_reconciliation_removes_missing_evidence(tmp_path):
    client = Pages([item(day) for day in (0, 7, 14, 21)])
    store, learner = setup(tmp_path, client)
    learner.import_page(OWNER, CHAT)
    client.rows = [item(day) for day in (0, 7, 14)]
    store.begin_rescan(OWNER, CHAT)
    learner.import_page(OWNER, CHAT, 2)
    # Missing evidence survives until successful final page.
    assert store.list_relationships(OWNER)[0]['last_confirmed_at'].startswith('2026-09-22')
    learner.import_page(OWNER, CHAT, 2)
    assert store.list_relationships(OWNER)[0]['last_confirmed_at'].startswith('2026-09-15')
    assert learner.suggestion(OWNER, 'Friend') is None


def test_suggestions_require_acceptance_and_stay_channel_specific(tmp_path):
    from app.relationships.commands import reply
    store, learner = setup(tmp_path, Pages([item(day) for day in (0, 10, 20, 30)]))
    learner.import_page(OWNER, CHAT)
    assert '10' in reply(store, OWNER, 'Hey Rally, suggest cadence for Friend', 's1', NOW, learner)
    assert store.person(OWNER, 'Friend')['days'] == 7
    reply(store, OWNER, 'Hey Rally, accept cadence for Friend', 's2', NOW, learner)
    assert store.person(OWNER, 'Friend')['days'] == 10
    store.upsert(OWNER, 'Friend', 'call', 7, NOW)
    assert learner.suggestion(OWNER, 'Friend') is None
    for day in (0, 5, 10, 15):
        store.confirm(OWNER, 'Friend', 'call', NOW + timedelta(days=day), f'call{day}')
    assert learner.suggestion(OWNER, 'Friend')['days'] == 5
