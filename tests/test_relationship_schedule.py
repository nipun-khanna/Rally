from datetime import datetime, timezone

from app.relationships.store import RelationshipStore


def test_calendar_days_across_dst_and_missed_window(tmp_path):
    store = RelationshipStore(tmp_path / 'r.sqlite3')
    store.configure('owner', 'iMessage;-;private', 'America/New_York', 18)
    # Oct 31 at 18:00 EDT. Seven calendar days later is Nov 7 18:00 EST.
    store.upsert('owner', 'Mom', 'call', 7,
                 datetime(2026, 10, 31, 22, tzinfo=timezone.utc))
    assert store.enqueue_due(datetime(2026, 11, 7, 22, 59, tzinfo=timezone.utc)) == 0
    assert store.enqueue_due(datetime(2026, 11, 7, 23, tzinfo=timezone.utc)) == 1


def test_missed_window_waits_until_next_local_window(tmp_path):
    store = RelationshipStore(tmp_path / 'r.sqlite3')
    store.configure('owner', 'iMessage;-;private', 'UTC', 18)
    store.upsert('owner', 'Mom', 'call', 7,
                 datetime(2026, 9, 1, 18, tzinfo=timezone.utc))
    assert store.enqueue_due(datetime(2026, 9, 9, 9, tzinfo=timezone.utc)) == 0
    assert store.enqueue_due(datetime(2026, 9, 9, 18, tzinfo=timezone.utc)) == 1
