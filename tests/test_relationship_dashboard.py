from datetime import datetime, timedelta, timezone

from app.relationships.dashboard import build_attention
from app.relationships.store import RelationshipStore
from app.relationships.view import render_dashboard


NOW = datetime(2026, 9, 26, 22, tzinfo=timezone.utc)


def setup(tmp_path):
    store = RelationshipStore(tmp_path / 'r.sqlite3')
    store.ensure_profile('owner', 'UTC', 18)
    return store


def test_confirmed_overdue_relationship_has_evidence(tmp_path):
    store = setup(tmp_path)
    store.upsert('owner', 'Mom', 'call', 7, NOW - timedelta(days=14))
    store.confirm('owner', 'Mom', 'call', NOW - timedelta(days=10), 'call-1')
    result = build_attention(store, 'owner', NOW)
    card = result['cards'][0]
    assert card['label'] == 'Mom'
    assert card['state'] == 'overdue'
    assert card['evidence']['kind'] == 'confirmed_contact'
    assert card['evidence']['mode'] == 'call'
    assert card['evidence']['at'].startswith('2026-09-16')


def test_unknown_anchor_is_not_claimed_as_overdue(tmp_path):
    store = setup(tmp_path)
    store.upsert('owner', 'Alex', 'call', 7, NOW)
    card = build_attention(store, 'owner', NOW)['cards'][0]
    assert card['state'] == 'unknown'
    assert card['evidence']['kind'] == 'none'


def test_message_history_never_becomes_call_or_visit_evidence(tmp_path):
    store = setup(tmp_path)
    store.upsert('owner', 'Alex', 'call', 7, NOW - timedelta(days=20))
    store.add_source('owner', 'iMessage;-;alex', 'Alex')
    with store.db() as db:
        db.execute("INSERT INTO rel_texts(owner,chat_id,message_id,text,sender,at,eligible,scan) VALUES(?,?,?,?,?,?,?,?)",
                   ('owner', 'iMessage;-;alex', 'msg1', 'hey', 'me', (NOW - timedelta(days=1)).isoformat(), 1, 1))
    card = build_attention(store, 'owner', NOW)['cards'][0]
    assert card['state'] == 'unknown'
    assert card['evidence']['kind'] == 'none'


def test_selected_message_history_is_labeled_as_message_evidence(tmp_path):
    store = setup(tmp_path)
    store.upsert('owner', 'Alex', 'message', 7, NOW - timedelta(days=20))
    store.add_source('owner', 'iMessage;-;alex', 'Alex')
    with store.db() as db:
        db.execute("INSERT INTO rel_texts(owner,chat_id,message_id,text,sender,at,eligible,scan) VALUES(?,?,?,?,?,?,?,?)",
                   ('owner', 'iMessage;-;alex', 'msg1', 'hey', 'me', (NOW - timedelta(days=10)).isoformat(), 1, 1))
    card = build_attention(store, 'owner', NOW)['cards'][0]
    assert card['evidence']['kind'] == 'selected_message'
    assert card['evidence']['mode'] == 'message'


def test_pause_and_snooze_suppress_attention(tmp_path):
    store = setup(tmp_path)
    store.upsert('owner', 'Mom', 'call', 7, NOW - timedelta(days=20))
    store.confirm('owner', 'Mom', 'call', NOW - timedelta(days=10), 'call-1')
    store.upsert('owner', 'Dad', 'call', 7, NOW - timedelta(days=20))
    store.confirm('owner', 'Dad', 'call', NOW - timedelta(days=10), 'call-2')
    store.control('owner', 'Mom', 'pause', NOW)
    store.control('owner', 'Dad', 'snooze', NOW, NOW + timedelta(days=3))
    result = build_attention(store, 'owner', NOW)
    assert result['cards'] == []
    later = build_attention(store, 'owner', NOW + timedelta(days=4))
    assert [c['label'] for c in later['cards']] == ['Dad']


def test_owner_isolation_and_plan_references(tmp_path):
    store = setup(tmp_path)
    store.upsert('owner', 'Mom', 'call', 7, NOW - timedelta(days=20))
    store.confirm('owner', 'Mom', 'call', NOW - timedelta(days=10), 'call-1')
    plan = {'id': 'plan-1', 'title': 'Dinner', 'status': 'stalled', 'group_id': 'g1'}
    store.ensure_profile('other', 'UTC')
    assert build_attention(store, 'other', NOW, plans=[plan])['cards'] == []
    assert build_attention(store, 'other', NOW, plans=[plan])['plans'] == [plan]
    assert [c['label'] for c in build_attention(store, 'owner', NOW)['cards']] == ['Mom']


def test_dashboard_html_escapes_profile_and_plan_content():
    html = render_dashboard({
        'cards': [{'label': '<script>alert(1)</script>', 'category': 'friend',
                   'intention': 'Say "hi" & <b>soon</b>', 'state': 'overdue',
                   'evidence': {'summary': '<img src=x onerror=alert(1)>'}}],
        'plans': [{'title': '<svg onload=alert(1)>', 'status': 'stalled'}],
    }, 'csrf<&')
    assert '<script>' not in html and '<img' not in html and '<svg' not in html
    assert '&lt;script&gt;' in html and 'csrf&lt;&amp;' in html


def test_dashboard_has_accessible_responsive_relationship_layout():
    html = render_dashboard({
        'cards': [{'label': 'Maya Patel', 'category': 'friend', 'state': 'overdue',
                   'intention': 'Meet every other week', 'mode': 'visit',
                   'cadence_days': 14, 'evidence': {'summary': 'Last confirmed visit: 3 weeks ago.'}}],
        'plans': [{'title': 'Dinner with Maya', 'status': 'stalled'}],
    }, 'csrf-token')
    assert '<main' in html and 'aria-label="Relationships needing attention"' in html
    assert 'class="attention-card' in html and 'class="plans-panel' in html
    assert 'prefers-reduced-motion: reduce' in html
    assert ':focus-visible' in html and 'viewport' in html
