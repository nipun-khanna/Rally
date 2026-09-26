import json

import pytest

from scripts.configure_relationships import main
from app.relationships.store import RelationshipStore


def test_setup_status_and_source_controls(tmp_path, capsys):
    path = str(tmp_path / 'r.sqlite3')
    assert main(['--database', path, 'configure', '--destination', 'iMessage;-;private', '--zone', 'UTC', '--hour', '18']) == 0
    store = RelationshipStore(path)
    assert store.configs()[0]['owner'] == 'local-imessage-account'
    store.upsert('local-imessage-account', 'Friend', 'message', 7, __import__('datetime').datetime.now(__import__('datetime').timezone.utc))
    assert main(['--database', path, 'add-source', '--chat', 'iMessage;-;friend', '--relationship', 'Friend']) == 0
    main(['--database', path, 'status'])
    output = capsys.readouterr().out
    assert 'configured' in output
    assert 'password' not in output and 'text' not in output
    assert main(['--database', path, 'disable-source', '--chat', 'iMessage;-;friend']) == 0
    assert store.sources()[0]['enabled'] == 0
    assert main(['--database', path, 'remove-source', '--chat', 'iMessage;-;friend']) == 0
    assert store.sources() == []


def test_setup_rejects_group_destination(tmp_path, capsys):
    path = str(tmp_path / 'r.sqlite3')
    assert main(['--database', path, 'configure', '--destination', 'iMessage;+;group']) == 1
    assert RelationshipStore(path).configs() == []


def test_status_does_not_change_inflight_delivery(tmp_path, capsys):
    from datetime import datetime, timedelta, timezone
    path = str(tmp_path / 'r.sqlite3')
    store = RelationshipStore(path)
    store.configure('local-imessage-account', 'iMessage;-;private', 'UTC', 18)
    now = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
    store.upsert('local-imessage-account', 'Mom', 'call', 7, now)
    store.enqueue_due(now + timedelta(days=7))
    claimed = store.claim_delivery(now + timedelta(days=7))
    main(['--database', path, 'status'])
    assert store.delivery_valid(claimed['id'])
