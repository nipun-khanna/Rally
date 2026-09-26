from datetime import datetime, timedelta, timezone

import pytest

from app.relationships.store import RelationshipStore


NOW = datetime(2026, 9, 26, 22, tzinfo=timezone.utc)
DEST = 'iMessage;-;private-owner'


@pytest.fixture
def store(tmp_path):
    value = RelationshipStore(tmp_path / 'rally.sqlite3')
    value.configure('owner', DEST, 'America/New_York', 18)
    return value


def test_contact_channels_and_owner_isolation(store):
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    store.confirm('owner', 'Mom', 'message', NOW, 'event1')
    assert store.list_relationships('other') == []
    assert store.list_relationships('owner')[0]['last_confirmed_at'] is None
    assert store.enqueue_due(NOW + timedelta(days=7)) == 1
    assert store.enqueue_due(NOW + timedelta(days=7)) == 0
    item = store.claim_delivery(NOW + timedelta(days=7))
    assert item['destination'] == DEST
    assert 'Have you' in item['text']
    assert not item['text'].startswith('Rally:')
    store.finish_delivery(item['id'], 'sent', NOW + timedelta(days=7))
    assert store.enqueue_due(NOW + timedelta(days=14)) == 0


def test_confirmation_cancels_old_cycle_and_duplicates(store):
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    store.enqueue_due(NOW + timedelta(days=7))
    store.confirm('owner', 'mom', 'call', NOW + timedelta(days=7), 'call1')
    store.confirm('owner', 'Mom', 'call', NOW + timedelta(days=7), 'call1')
    assert store.claim_delivery(NOW + timedelta(days=7)) is None
    assert store.enqueue_due(NOW + timedelta(days=14)) == 1
    assert len(store.contact_events('owner', 'Mom')) == 1


def test_pause_snooze_resume_remove(store):
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    due = NOW + timedelta(days=7)
    store.enqueue_due(due)
    store.control('owner', 'Mom', 'pause', due)
    assert store.claim_delivery(due) is None
    assert store.enqueue_due(due + timedelta(days=1)) == 0
    store.control('owner', 'Mom', 'resume', due)
    store.control('owner', 'Mom', 'snooze', due, due + timedelta(days=3))
    assert store.enqueue_due(due + timedelta(days=2)) == 0
    assert store.enqueue_due(due + timedelta(days=3)) == 1
    store.control('owner', 'Mom', 'remove', due)
    assert store.claim_delivery(due + timedelta(days=3)) is None
    assert store.list_relationships('owner') == []


def test_crash_recovery_does_not_resend(store):
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    due = NOW + timedelta(days=7)
    store.enqueue_due(due)
    claimed = store.claim_delivery(due)
    reopened = RelationshipStore(store.path)
    assert reopened.claim_delivery(due) is None
    assert reopened.deliveries('owner')[0]['status'] == 'uncertain'
    assert reopened.enqueue_due(due + timedelta(days=1)) == 0
    assert claimed['id'] == reopened.deliveries('owner')[0]['id']


def test_reconfigure_cancels_old_destination_and_claims(store):
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    due = NOW + timedelta(days=7)
    store.enqueue_due(due)
    claimed = store.claim_delivery(due)
    store.configure('owner', 'iMessage;-;new', 'America/New_York', 18)
    assert not store.delivery_valid(claimed['id'])
    assert store.claim_delivery(due) is None


def test_configuration_and_frequency_validation(store):
    with pytest.raises(ValueError):
        store.configure('owner', 'iMessage;+;group', 'UTC')
    with pytest.raises(ValueError):
        store.configure('owner', DEST, 'bad/timezone')
    with pytest.raises(ValueError):
        store.upsert('owner', 'Mom', 'call', 0, NOW)
    with pytest.raises(ValueError):
        store.confirm('other', 'Mom', 'call', NOW, 'bad')


def test_pending_reminder_respects_window_after_restart(store):
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    due = NOW + timedelta(days=7)
    store.enqueue_due(due)
    assert store.claim_delivery(due + timedelta(hours=14)) is None
    assert store.claim_delivery(due + timedelta(days=1)) is not None


def test_local_profile_supports_relationship_setup_without_a_reminder_destination(tmp_path):
    store = RelationshipStore(tmp_path / 'local.sqlite3')
    profile = store.ensure_profile('owner', 'America/New_York', 19)
    assert profile['owner'] == 'owner'
    assert profile['zone'] == 'America/New_York'
    assert profile['hour'] == 19
    assert 'destination' not in profile
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    assert store.list_relationships('owner')[0]['label'] == 'Mom'
    assert store.configs() == []
    assert store.enqueue_due(NOW + timedelta(days=7)) == 0


def test_profile_reads_reminder_settings_and_metadata_migrates_existing_people(store):
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    assert store.profile('owner')['destination'] == DEST
    store.set_metadata('owner', 'Mom', category='parent', intention='Call every weekend',
                       contact_address='mom@example.test')
    person = store.person('owner', 'Mom')
    assert person['category'] == 'parent'
    assert person['intention'] == 'Call every weekend'
    assert person['contact_address'] == 'mom@example.test'
    with pytest.raises(ValueError):
        store.set_metadata('owner', 'Mom', category='unknown', intention='x')


def test_metadata_is_owner_scoped_and_address_is_optional(store):
    store.upsert('owner', 'Mom', 'call', 7, NOW)
    with pytest.raises(ValueError):
        store.set_metadata('other', 'Mom', category='parent', intention='Call weekly')
    store.set_metadata('owner', 'Mom', category='parent', intention='Call weekly')
    assert store.person('owner', 'Mom')['contact_address'] is None


def test_old_people_table_gets_metadata_columns_without_losing_rows(tmp_path):
    import sqlite3
    path = tmp_path / 'legacy.sqlite3'
    db = sqlite3.connect(path)
    db.execute('''CREATE TABLE rel_people (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, label TEXT NOT NULL,
        label_key TEXT NOT NULL, mode TEXT NOT NULL, days INTEGER NOT NULL,
        created_at TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0,
        snooze_until TEXT, generation INTEGER NOT NULL DEFAULT 1,
        UNIQUE(owner,label_key))''')
    db.execute('INSERT INTO rel_people(id,owner,label,label_key,mode,days,created_at) VALUES(?,?,?,?,?,?,?)',
               ('p1', 'owner', 'Mom', 'mom', 'call', 7, NOW.isoformat()))
    db.commit()
    db.close()
    store = RelationshipStore(path)
    person = store.person('owner', 'Mom')
    assert (person['category'], person['intention'], person['contact_address']) == ('other', '', None)
