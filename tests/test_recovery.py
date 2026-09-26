from datetime import datetime, timedelta, timezone

import pytest

from app.models import ChatMessage, PlanFacts, Proposal
from app.orchestrator import RallyService
from app.store import Store


NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


class Extractor:
    def __init__(self, facts):
        self.facts = facts
        self.calls = []
        self.fail = False

    def extract(self, messages, previous):
        self.calls.append(([message.message_id for message in messages], previous))
        if self.fail:
            raise RuntimeError('provider unavailable')
        return self.facts


def service(tmp_path, facts):
    store = Store(tmp_path/'rally.sqlite3')
    extractor = Extractor(facts)
    sent = []
    rally = RallyService(store, extractor, lambda _: [],
                         lambda chat, text: sent.append((chat, text)),
                         allowed_chat_ids={'chat-a'}, extractor=extractor)
    return rally, extractor, sent


def add(store, message_id, text, minute, processed=False):
    store.add_message(ChatMessage(message_id,'chat-a','member',text,
                                  NOW+timedelta(minutes=minute)))
    if processed:
        store.mark_processed(message_id)


def test_recovery_extracts_pending_and_later_processed_without_replies(tmp_path):
    rally, extractor, sent = service(tmp_path, PlanFacts(goal='Dinner',activity='dinner',
                                                        date='2026-09-27', confidence=0.9))
    add(rally.store,'old-direct','Rally, what is the plan?',0)
    rally.store.queue_message('chat-a','Rally: old answer','direct_reply','old-direct')
    add(rally.store,'changed','Dinner Sunday',1)
    add(rally.store,'later','Sunday works',2,processed=True)
    assert rally.recover_pending('chat-a') == 2
    assert extractor.calls[0][0] == ['old-direct','changed','later']
    assert rally.store.is_processed('old-direct') and rally.store.is_processed('changed')
    assert rally.store.get_plan('chat-a').facts.date == '2026-09-27'
    assert sent == []
    assert rally.recover_pending('chat-a') == 0
    assert len(extractor.calls) == 1


def test_failed_recovery_acks_nothing_and_disallowed_chat_is_rejected(tmp_path):
    rally, extractor, sent = service(tmp_path, PlanFacts())
    add(rally.store,'m1','Dinner?',0)
    extractor.fail=True
    with pytest.raises(RuntimeError):
        rally.recover_pending('chat-a')
    assert not rally.store.is_processed('m1')
    with pytest.raises(ValueError):
        rally.recover_pending('chat-b')
    assert sent == []


def test_failed_live_extraction_records_only_sanitized_diagnostics(tmp_path):
    from app.agent import GrokProviderError
    rally, extractor, _ = service(tmp_path, PlanFacts())
    message=ChatMessage('m1','chat-a','member','private message content',NOW)
    rally.store.add_message(message)
    extractor.fail=True
    extractor.extract=lambda *_: (_ for _ in ()).throw(GrokProviderError('timeout','extracted'))
    with pytest.raises(GrokProviderError):
        rally.receive(message)
    diagnostic=rally.store.pending_diagnostics('chat-a')
    assert diagnostic == {'pending':1,'failures':[{'stage':'extracted','kind':'timeout','status':None,'count':1}]}
    assert rally.store.recent_messages('chat-a')[0].text == 'private message content'
    assert 'private message content' not in str(diagnostic)


def test_recovery_refuses_partial_snapshot(tmp_path):
    rally, extractor, _ = service(tmp_path, PlanFacts())
    for i in range(4):
        add(rally.store,f'm{i}',f'message {i}',i)
    with pytest.raises(ValueError, match='bounded'):
        rally.recover_pending('chat-a',limit=3)
    assert extractor.calls == []
    assert not rally.store.is_processed('m0')


def test_recovered_change_invalidates_old_proposal_without_booking(tmp_path):
    old = PlanFacts(goal='Dinner',activity='dinner',date='2026-09-27',
                    location='Atlanta, GA',confidence=0.9)
    new = PlanFacts(goal='Dinner',activity='dinner',date='2026-09-28',
                    location='Atlanta, GA',confidence=0.9)
    rally, extractor, sent = service(tmp_path,new)
    plan = rally.store.save_plan('chat-a',old,NOW)
    proposal = Proposal('proposal-1',plan.id,plan.version,'venue','Venue','Address',
                        '2026-09-27','19:00',2)
    rally.store.save_proposal(proposal)
    add(rally.store,'changed','Make it Monday',1)
    assert rally.recover_pending('chat-a') == 1
    assert rally.store.get_proposal(proposal.id).status == 'stale'
    assert rally.store.get_plan('chat-a').facts.date == '2026-09-28'
    assert rally.store.reservation(proposal.id) is None
    assert sent == []


def test_local_recovery_cli_status_and_explicit_run_guard(tmp_path, monkeypatch, capsys):
    from scripts.recover_pending import main
    monkeypatch.setenv('RALLY_DATABASE_PATH',str(tmp_path/'rally.sqlite3'))
    monkeypatch.setenv('RALLY_ALLOWED_CHAT_GUIDS','chat-a')
    add(Store(tmp_path/'rally.sqlite3'),'m1','Dinner?',0)
    assert main(['status']) == 0
    assert '"pending": 1' in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(['run'])
    assert error.value.code == 2
    assert not Store(tmp_path/'rally.sqlite3').is_processed('m1')
