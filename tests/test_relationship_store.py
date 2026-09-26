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

