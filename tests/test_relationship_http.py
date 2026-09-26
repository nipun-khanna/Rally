from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.bluebubbles import normalize_webhook
from app.main import create_app
from app.models import PlanFacts
from app.orchestrator import RallyService
from app.portal_store import PortalStore
from app.relationships.learning import RelationshipLearner
from app.relationships.service import RelationshipService
from app.relationships.store import RelationshipStore
from app.store import Store


DEST = 'iMessage;-;private'
SOURCE = 'iMessage;-;friend'
GROUP = 'iMessage;+;group'
NOW = datetime(2026, 9, 26, 22, tzinfo=timezone.utc)


class Agent:
    def extract(self, messages, previous):
        return PlanFacts()
    def answer_direct(self, *args):
        return 'group reply'


def payload(chat, text, ident='m1', mine=True):
    return {'type': 'new-message', 'data': {'guid': ident, 'text': text,
        'isFromMe': mine, 'dateCreated': int(NOW.timestamp() * 1000),
        'handle': {'address': 'intruder'}, 'chats': [{'guid': chat}]}}


def setup(tmp_path):
    path = tmp_path / 'r.sqlite3'
    group_store = Store(path)
    portal = PortalStore(path)
    private = RelationshipStore(path)
    private.configure('local-imessage-account', DEST, 'UTC', 18)
    sent = []
    group = RallyService(group_store, Agent(), lambda facts: [], lambda chat, text: sent.append((chat, text)), allowed_chat_ids={GROUP})
    learner = RelationshipLearner(private)
    relationships = RelationshipService(private, group.send_fn, learner)
    app = create_app(group, webhook_token='secret', schedule=False, portal_store=portal,
                     history_enabled=False, relationship_service=relationships)
    app.state.test_group_service = group
    return TestClient(app), private, group_store, portal, sent


def test_private_requests_do_not_enter_group_storage_or_portal(tmp_path):
    client, private, group, portal, sent = setup(tmp_path)
    response = client.post('/webhooks/bluebubbles?token=secret', json=payload(DEST, 'Hey Rally, remind me to call Secret Mom every week'))
    assert response.json()['accepted']
    assert len(private.list_relationships('local-imessage-account')) == 1
    assert group.recent_messages(DEST) == []
    assert group.actions_for_chat(DEST) == []
    assert portal.list_messages(DEST) == []
    assert sent[0][0] == DEST
    assert client.post('/webhooks/bluebubbles?token=secret', json=payload(DEST, 'Rally: output', 'm2')).json()['accepted'] is False


def test_unselected_or_unauthorized_private_requests_ignored(tmp_path):
    client, private, group, portal, sent = setup(tmp_path)
    for chat, mine in [(DEST, False), ('iMessage;-;unselected', True)]:
        result = client.post('/webhooks/bluebubbles?token=secret', json=payload(chat, 'Hey Rally, relationship status', mine=mine))
        assert not result.json()['accepted']
    assert sent == []
    assert client.post('/webhooks/bluebubbles', json=payload(DEST, 'Hey Rally, help')).status_code == 403


def test_selected_direct_source_observed_with_global_history_off(tmp_path):
    client, private, group, portal, sent = setup(tmp_path)
    private.upsert('local-imessage-account', 'Friend', 'message', 7, NOW)
    private.add_source('local-imessage-account', SOURCE, 'Friend')
    client.post('/webhooks/bluebubbles?token=secret', json=payload(SOURCE, 'personal text'))
    assert private.list_relationships('local-imessage-account')[0]['last_confirmed_at'] is not None
    assert portal.list_messages(SOURCE) == []
    assert group.recent_messages(SOURCE) == []
    assert sent == []
    private.set_source('local-imessage-account', SOURCE, 'disable')
    assert private.list_relationships('local-imessage-account')[0]['last_confirmed_at'] is None


def test_group_planning_unchanged_and_archive_disabled(tmp_path):
    client, private, group, portal, sent = setup(tmp_path)
    response = client.post('/webhooks/bluebubbles?token=secret', json=payload(GROUP, 'Hey Rally, whats the plan'))
    assert response.json()['accepted']
    assert sent == [(GROUP, 'Rally: group reply')]
    assert portal.list_messages(GROUP) == []
    assert client.post(f'/portal/admin/{GROUP}/import?token=secret').status_code == 404


def test_normalizer_accepts_only_selected_direct_chats():
    assert normalize_webhook(payload(DEST, 'Hey Rally, help')) is None
    assert normalize_webhook(payload(DEST, 'Hey Rally, help'), allowed_direct_chat_ids={DEST}).chat_id == DEST
    assert normalize_webhook(payload(SOURCE, 'Hey Rally, help'), allowed_direct_chat_ids={DEST}) is None


def test_selected_group_is_local_learning_only(tmp_path):
    client, private, group, portal, sent = setup(tmp_path)
    private.upsert('local-imessage-account', 'Friends', 'message', 7, NOW)
    private.add_source('local-imessage-account', GROUP, 'Friends')
    client.post('/webhooks/bluebubbles?token=secret', json=payload(GROUP, 'Hey Rally, personal monitoring content'))
    assert group.recent_messages(GROUP) == []
    assert portal.list_messages(GROUP) == []
    assert sent == []


def test_group_pending_delivery_exclusion_updates_without_scheduler_tick(tmp_path):
    client, private, group, portal, sent = setup(tmp_path)
    other = 'iMessage;+;other-group'
    client.app.state.test_group_service.allowed_chat_ids = {GROUP, other}
    group.queue_message(GROUP, 'pending group reply', 'ask', 'test-ref')
    private.upsert('local-imessage-account', 'Friends', 'message', 7, NOW)
    private.add_source('local-imessage-account', GROUP, 'Friends')
    client.post('/webhooks/bluebubbles?token=secret', json=payload(other, 'Hey Rally, whats the plan'))
    assert not any(chat == GROUP for chat, text in sent)
