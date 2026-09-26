from datetime import datetime, timedelta, timezone

import pytest

from app.relationships.followups import FollowupStore, detect_candidates
from app.relationships.store import RelationshipStore


OWNER = 'local-imessage-account'
CHAT = 'iMessage;-;friend'
NOW = datetime(2026, 9, 23, 15, tzinfo=timezone.utc)


def setup(tmp_path, zone='UTC'):
    store = RelationshipStore(tmp_path / 'private.sqlite3')
    store.configure(OWNER, 'iMessage;-;private', zone, 18)
    store.upsert(OWNER, 'Friend', 'message', 7, NOW)
    store.add_source(OWNER, CHAT, 'Friend')
    return store, FollowupStore(store)


def source_text(store, *, text, ident='m1', at=NOW, sender=OWNER, eligible=1):
    with store.db() as db:
        db.execute('''INSERT OR REPLACE INTO rel_texts
            (owner,chat_id,message_id,text,sender,at,eligible,scan)
            VALUES(?,?,?,?,?,?,?,1)''',
            (OWNER, CHAT, ident, text, sender, at.isoformat(), eligible))


@pytest.mark.parametrize('text,action,outgoing', [
    ('I’ll text you later', 'text', True),
    ('Let me know how your interview goes', 'follow_up', False),
    ('We should talk about this later', 'talk', True),
    ('We should get dinner', 'make_plan', True),
    ("Let's hang next week", 'make_plan', False),
])
def test_detects_prd_commitments_and_unfinished_plans(text, action, outgoing):
    candidates = detect_candidates(text, NOW, 'UTC', outgoing=outgoing)
    assert candidates
    assert candidates[0]['action'] == action
    assert candidates[0]['certainty'] in {'medium', 'high'}


def test_next_week_window_uses_owner_timezone():
    local = datetime(2026, 9, 23, 23, 30, tzinfo=timezone.utc)
    candidate = detect_candidates("Let's hang next week", local, 'America/Los_Angeles', outgoing=True)[0]
    assert candidate['window_start'].tzinfo is not None
    assert candidate['window_start'].astimezone(timezone.utc) == datetime(2026, 9, 28, 7, tzinfo=timezone.utc)
    assert candidate['window_end'] > candidate['window_start']


def test_only_owner_obligations_become_followups():
    # An incoming promise belongs to the other person; it must not become the owner's task.
    assert detect_candidates('I’ll text you later', NOW, 'UTC', outgoing=False) == []
    # An incoming request for an update does assign the owner an action.
    assert detect_candidates('Let me know how your interview goes', NOW, 'UTC', outgoing=False)
    # An outgoing request assigns the other person, not the owner.
    assert detect_candidates('Let me know how your interview goes', NOW, 'UTC', outgoing=True) == []


@pytest.mark.parametrize('text', [
    "I won't text you later",
    'Example: “I’ll text you later”',
    'I texted you yesterday',
    'Rally: I’ll text you later',
])
def test_ignores_negation_examples_completed_actions_and_bot_output(text):
    assert detect_candidates(text, NOW, 'UTC', outgoing=True) == []


def test_sync_lists_source_owned_evidence_and_durable_dismissal(tmp_path):
    store, followups = setup(tmp_path)
    source_text(store, text="Let's get dinner next week")
    followups.sync_source(OWNER, CHAT)
    rows = followups.list_for_owner(OWNER, now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row['source']['chat_id'] == CHAT
    assert row['source']['message_id'] == 'm1'
    followups.decide(OWNER, row['id'], expected_revision=row['revision'], status='dismissed')
    assert followups.list_for_owner(OWNER, now=NOW) == []

    # A rescan changes the source scan/revision, but identical evidence preserves the choice.
    store.begin_rescan(OWNER, CHAT)
    followups.sync_source(OWNER, CHAT)
    assert followups.list_for_owner(OWNER, now=NOW) == []


def test_source_edit_invalidates_old_decision_and_projects_new_evidence(tmp_path):
    store, followups = setup(tmp_path)
    source_text(store, text='I’ll text you later')
    followups.sync_source(OWNER, CHAT)
    original = followups.list_for_owner(OWNER)[0]
    followups.decide(OWNER, original['id'], expected_revision=original['revision'], status='dismissed')

    source_text(store, text='We should get dinner', ident='m1')
    followups.sync_source(OWNER, CHAT)
    current = followups.list_for_owner(OWNER)
    assert len(current) == 1
    assert current[0]['revision'] != original['revision']
    assert current[0]['status'] == 'open'
    with pytest.raises(ValueError):
        followups.decide(OWNER, original['id'], expected_revision=original['revision'], status='done')


def test_edit_away_and_back_does_not_resurrect_a_dismissal(tmp_path):
    store, followups = setup(tmp_path)
    source_text(store, text='I’ll text you later')
    followups.sync_source(OWNER, CHAT)
    old = followups.list_for_owner(OWNER)[0]
    followups.decide(OWNER, old['id'], expected_revision=old['revision'], status='dismissed')
    source_text(store, text='A different ordinary message')
    followups.sync_source(OWNER, CHAT)
    source_text(store, text='I’ll text you later')
    followups.sync_source(OWNER, CHAT)
    assert followups.list_for_owner(OWNER)[0]['status'] == 'open'


def test_complete_snooze_and_stale_revision_are_durable(tmp_path):
    store, followups = setup(tmp_path)
    source_text(store, text='I’ll text you later')
    followups.sync_source(OWNER, CHAT)
    row = followups.list_for_owner(OWNER)[0]
    due = NOW + timedelta(days=3)
    followups.decide(OWNER, row['id'], expected_revision=row['revision'], status='snoozed', due_at=due)
    snoozed = followups.list_for_owner(OWNER, now=NOW)[0]
    assert snoozed['status'] == 'snoozed'
    assert snoozed['due_at'] == due
    with pytest.raises(ValueError):
        followups.decide(OWNER, row['id'], expected_revision='stale', status='done')
    followups.decide(OWNER, row['id'], expected_revision=row['revision'], status='done')
    assert followups.list_for_owner(OWNER) == []


@pytest.mark.parametrize('action', ['disable', 'remove'])
def test_disabled_or_removed_source_never_surfaces_or_resurrects_decision(tmp_path, action):
    store, followups = setup(tmp_path)
    source_text(store, text='I’ll text you later')
    followups.sync_source(OWNER, CHAT)
    row = followups.list_for_owner(OWNER)[0]
    followups.decide(OWNER, row['id'], expected_revision=row['revision'], status='dismissed')
    store.set_source(OWNER, CHAT, action)
    assert followups.list_for_owner(OWNER) == []
    if action == 'disable':
        store.set_source(OWNER, CHAT, 'enable')
        followups.sync_source(OWNER, CHAT)
        assert followups.list_for_owner(OWNER) == []


def test_remove_and_reselect_source_does_not_reuse_old_decisions(tmp_path):
    store, followups = setup(tmp_path)
    source_text(store, text='I’ll text you later')
    followups.sync_source(OWNER, CHAT)
    old = followups.list_for_owner(OWNER)[0]
    followups.decide(OWNER, old['id'], expected_revision=old['revision'], status='dismissed')
    store.set_source(OWNER, CHAT, 'remove')
    store.add_source(OWNER, CHAT, 'Friend')
    source_text(store, text='I’ll text you later')
    followups.sync_source(OWNER, CHAT)
    assert followups.list_for_owner(OWNER)[0]['status'] == 'open'


def test_decisions_are_owner_scoped_and_stale_messages_disappear(tmp_path):
    store, followups = setup(tmp_path)
    source_text(store, text="Let's get dinner next week")
    followups.sync_source(OWNER, CHAT)
    row = followups.list_for_owner(OWNER)[0]
    with pytest.raises(ValueError):
        followups.decide('someone-else', row['id'], expected_revision=row['revision'], status='done')
    with store.db() as db:
        db.execute('DELETE FROM rel_texts WHERE owner=? AND chat_id=? AND message_id=?', (OWNER, CHAT, 'm1'))
    followups.sync_source(OWNER, CHAT)
    assert followups.list_for_owner(OWNER) == []
