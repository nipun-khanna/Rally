from datetime import datetime, timedelta, timezone

from app.models import ChatMessage
from app.relationships.store import RelationshipStore
from app.relationships.service import RelationshipService


NOW = datetime(2026, 9, 26, 22, tzinfo=timezone.utc)
DEST = 'iMessage;-;owner-private'


def setup(tmp_path, send=None):
    store = RelationshipStore(tmp_path / 'r.sqlite3')
    store.configure('local-imessage-account', DEST, 'America/New_York', 18)
    sent = []
    service = RelationshipService(store, send or (lambda chat, text: sent.append((chat, text))))
    return store, service, sent


def request(service, text, message_id='m1', sender='local-imessage-account', chat=DEST, at=NOW):
    return service.receive(ChatMessage(message_id, chat, sender, text, at))


def test_setup_confirmation_and_duplicate_private_replies(tmp_path):
    store, service, sent = setup(tmp_path)
    assert request(service, 'Hey Rally, remind me to call Mom every week')
    assert request(service, 'Hey Rally, remind me to call Mom every week')
    assert len(sent) == 1
    assert store.list_relationships('local-imessage-account')[0]['days'] == 7
    assert request(service, 'Hey Rally, I called Mom today', 'm2')
    assert store.list_relationships('local-imessage-account')[0]['last_confirmed_at'][:10] == '2026-09-26'
    assert all(chat == DEST for chat, text in sent)


def test_status_cadence_and_controls(tmp_path):
    store, service, sent = setup(tmp_path)
    request(service, 'Hey Rally, remind me to call Mom every 7 days')
    request(service, 'Hey Rally, relationship status', 'm2')
    assert 'Mom' in sent[-1][1]
    request(service, 'Hey Rally, change Mom to every 10 days', 'm3')
    assert store.list_relationships('local-imessage-account')[0]['days'] == 10
    request(service, 'Hey Rally, pause reminders for Mom', 'm4')
    assert store.list_relationships('local-imessage-account')[0]['paused']
    request(service, 'Hey Rally, resume reminders for Mom', 'm5')
    assert not store.list_relationships('local-imessage-account')[0]['paused']
    request(service, 'Hey Rally, snooze Mom until Friday', 'm6')
    assert store.list_relationships('local-imessage-account')[0]['snooze_until'].startswith('2026-10-02')
    request(service, 'Hey Rally, remove Mom', 'm7')
    assert store.list_relationships('local-imessage-account') == []


def test_unauthorized_other_chats_and_output_ignored(tmp_path):
    store, service, sent = setup(tmp_path)
    assert not request(service, 'Hey Rally, relationship status', sender='intruder')
    assert not request(service, 'Hey Rally, relationship status', chat='iMessage;-;other')
    assert not request(service, 'Rally: Time to call Mom')
    assert not request(service, 'normal conversation')
    assert sent == []


def test_ambiguous_requests_do_not_change_state(tmp_path):
    store, service, sent = setup(tmp_path)
    request(service, 'Hey Rally, remind me to call Mom every week')
    for number, text in enumerate(('I called Mom tomorrow', 'snooze Mom until someday',
                                   'change Mom to every 0 days', 'I visited M yesterday')):
        request(service, 'Hey Rally, ' + text, str(number))
    person = store.list_relationships('local-imessage-account')[0]
    assert person['days'] == 7 and person['last_confirmed_at'] is None
    assert person['snooze_until'] is None


def test_transport_failure_is_not_retried(tmp_path):
    def fail(chat, text):
        raise TimeoutError('private credential must never appear')
    store, service, sent = setup(tmp_path, fail)
    request(service, 'Hey Rally, remind me to call Mom every week')
    assert store.deliveries('local-imessage-account')[0]['status'] == 'uncertain'
    service.tick(NOW)
    assert len(store.deliveries('local-imessage-account')) == 1


def test_confirm_future_date_rejected_and_yesterday_local(tmp_path):
    store, service, sent = setup(tmp_path)
    request(service, 'Hey Rally, remind me to call Mom every week')
    request(service, 'Hey Rally, I called Mom on 2027-01-01', 'future')
    assert store.contact_events('local-imessage-account', 'Mom') == []
    request(service, 'Hey Rally, I called Mom yesterday', 'past')
    assert store.contact_events('local-imessage-account', 'Mom')[0]['at'].startswith('2026-09-25')
