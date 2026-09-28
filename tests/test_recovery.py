import os
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
    assert rally.store.pending_diagnostics('chat-a')['failures'] == [
        {'stage':'extract','kind':'other','status':None,'count':1}]
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


def test_recovery_prefix_marks_only_included_pending_ids(tmp_path):
    rally, extractor, sent = service(tmp_path, PlanFacts(goal='Dinner', activity='dinner',
                                                        confidence=0.9))
    rally.store.add_message(ChatMessage('a','chat-a','member','earlier tie',NOW))
    rally.store.mark_processed('a')
    rally.store.add_message(ChatMessage('b','chat-a','member','oldest pending',NOW))
    rally.store.add_message(ChatMessage('rally-1','chat-a','rally','bot line',
                                        NOW+timedelta(minutes=1), True))
    add(rally.store,'c','next pending',2)
    add(rally.store,'d','replied later',3)
    reply_id = rally.store.queue_message('chat-a','already answered','direct_reply','d')
    rally.store.set_delivery(reply_id,'sent')
    assert rally.recover_pending('chat-a', limit=2) == 1
    assert extractor.calls == [(['b','rally-1'], None)]
    assert rally.store.is_processed('b')
    assert not rally.store.is_processed('c')
    assert not rally.store.is_processed('d')
    assert not rally.store.is_processed('rally-1')
    plan = rally.store.get_plan('chat-a')
    assert plan.facts.activity == 'dinner'
    assert plan.last_human_at == NOW
    assert sent == []


def test_next_recovery_starts_at_the_new_oldest_pending_row(tmp_path):
    rally, extractor, sent = service(tmp_path, PlanFacts(goal='Dinner', activity='dinner',
                                                        confidence=0.9))
    add(rally.store,'m0','first',0)
    add(rally.store,'m1','second',1)
    add(rally.store,'m2','third',2)
    assert rally.recover_pending('chat-a', limit=2) == 2
    assert extractor.calls[0][0] == ['m0','m1']
    assert not rally.store.is_processed('m2')
    assert rally.recover_pending('chat-a', limit=2) == 1
    assert extractor.calls[1][0] == ['m2']
    assert rally.store.is_processed('m2')
    assert sent == []


def test_failed_extraction_does_not_clear_a_replied_row(tmp_path):
    rally, extractor, sent = service(tmp_path, PlanFacts())
    add(rally.store,'replied','Rally, what is up',0)
    reply_id = rally.store.queue_message('chat-a','answer','direct_reply','replied')
    rally.store.set_delivery(reply_id,'sent')
    add(rally.store,'later','still pending',1)
    extractor.fail = True
    with pytest.raises(RuntimeError, match='provider unavailable'):
        rally.recover_pending('chat-a', limit=1)
    assert extractor.calls == [(['replied'], None)]
    assert not rally.store.is_processed('replied')
    assert not rally.store.is_processed('later')
    assert sent == []


def test_default_recovery_limit_leaves_the_76th_message_pending(tmp_path):
    rally, extractor, sent = service(tmp_path, PlanFacts())
    for i in range(76):
        add(rally.store, f'{i:02d}', f'message {i}', i)
    assert rally.recover_pending('chat-a') == 75
    assert extractor.calls[0][0] == [f'{i:02d}' for i in range(75)]
    assert not rally.store.is_processed('75')
    assert sent == []


def test_recovery_limit_200_takes_the_oldest_prefix_and_201_does_not_extract(tmp_path):
    rally, extractor, sent = service(tmp_path, PlanFacts())
    for i in range(201):
        add(rally.store, f'{i:03d}', f'message {i}', i)
    assert rally.recover_pending('chat-a', limit=200) == 200
    assert extractor.calls[0][0] == [f'{i:03d}' for i in range(200)]
    assert not rally.store.is_processed('200')
    with pytest.raises(ValueError, match='Invalid recovery limit'):
        rally.recover_pending('chat-a', limit=201)
    assert len(extractor.calls) == 1
    assert not rally.store.is_processed('200')
    assert sent == []


def test_historical_prefix_keeps_newer_plan_and_acks_old_pending(tmp_path):
    newer = PlanFacts(goal='Dinner', activity='dinner', date='2026-09-28',
                      location='Decatur, GA', confidence=0.9)
    historical = PlanFacts(goal='Lunch', activity='lunch', date='2026-09-20',
                           location='Atlanta, GA', confidence=0.9)
    rally, extractor, sent = service(tmp_path, historical)
    add(rally.store, 'old-pending', 'Lunch Friday', 0)
    add(rally.store, 'newer-human', 'Dinner Monday in Decatur', 10, processed=True)
    plan = rally.store.save_plan('chat-a', newer, NOW + timedelta(minutes=10))
    proposal = Proposal('proposal-1', plan.id, plan.version, 'venue', 'Newer Venue', 'Address',
                        '2026-09-28', '19:00', 2)
    rally.store.save_proposal(proposal)
    assert rally.recover_pending('chat-a', limit=1) == 1
    assert extractor.calls == [(['old-pending'], newer)]
    kept = rally.store.get_plan('chat-a')
    assert kept.id == plan.id
    assert kept.version == plan.version
    assert kept.state == 'READY'
    assert kept.facts.date == '2026-09-28'
    assert kept.facts.location == 'Decatur, GA'
    assert kept.facts.activity == 'dinner'
    assert kept.last_human_at == NOW + timedelta(minutes=10)
    assert rally.store.get_proposal(proposal.id).status == 'pending'
    assert rally.store.is_processed('old-pending')
    assert rally.store.is_processed('newer-human')
    assert sent == []


def test_historical_prefix_does_not_revive_abandoned_plan(tmp_path):
    abandoned = PlanFacts(goal='Dinner', activity='dinner', date='2026-09-28',
                          location='Decatur, GA', confidence=0.9, abandoned=True)
    historical = PlanFacts(goal='Dinner', activity='dinner', date='2026-09-21',
                           location='Atlanta, GA', confidence=0.9)
    rally, extractor, sent = service(tmp_path, historical)
    add(rally.store, 'old-pending', 'Dinner Friday', 0)
    add(rally.store, 'newer-human', 'Cancel the plan', 10, processed=True)
    plan = rally.store.save_plan('chat-a', abandoned, NOW + timedelta(minutes=10))
    assert plan.state == 'ABANDONED'
    assert rally.recover_pending('chat-a', limit=1) == 1
    assert extractor.calls == [(['old-pending'], abandoned)]
    kept = rally.store.get_plan('chat-a')
    assert kept.id == plan.id
    assert kept.version == plan.version
    assert kept.state == 'ABANDONED'
    assert kept.facts.abandoned is True
    assert kept.facts.date == '2026-09-28'
    assert kept.last_human_at == NOW + timedelta(minutes=10)
    assert len(rally.store.plans_for_chat('chat-a')) == 1
    assert rally.store.is_processed('old-pending')
    assert sent == []


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
    monkeypatch.setattr('app.config.resolve_settings_env',
                        lambda env=None, dotenv_path=None: dict(os.environ))
    monkeypatch.setenv('RALLY_DATABASE_PATH',str(tmp_path/'rally.sqlite3'))
    monkeypatch.setenv('RALLY_ALLOWED_CHAT_GUIDS','chat-a')
    add(Store(tmp_path/'rally.sqlite3'),'m1','Dinner?',0)
    assert main(['status']) == 0
    assert '"pending": 1' in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(['run'])
    assert error.value.code == 2
    assert not Store(tmp_path/'rally.sqlite3').is_processed('m1')


def test_cli_run_without_apply_does_not_load_settings_or_call_the_model(monkeypatch, capsys):
    from scripts.recover_pending import main

    def explode(*_args, **_kwargs):
        raise AssertionError('must not load settings or build the service')

    monkeypatch.setattr('scripts.recover_pending.Settings.from_env', explode)
    monkeypatch.setattr('scripts.recover_pending.build_service', explode)
    with pytest.raises(SystemExit) as error:
        main(['run', '--limit', '200'])
    assert error.value.code == 2
    assert 'requires --apply' in capsys.readouterr().err


def test_cli_limit_outside_1_through_200_does_not_load_settings(monkeypatch, capsys):
    from scripts.recover_pending import main

    def explode(*_args, **_kwargs):
        raise AssertionError('must not load settings or build the service')

    monkeypatch.setattr('scripts.recover_pending.Settings.from_env', explode)
    monkeypatch.setattr('scripts.recover_pending.build_service', explode)
    with pytest.raises(SystemExit) as over:
        main(['run', '--apply', '--limit', '201'])
    assert over.value.code == 2
    assert '1 through 200' in capsys.readouterr().err
    with pytest.raises(SystemExit) as zero:
        main(['run', '--apply', '--limit', '0'])
    assert zero.value.code == 2
