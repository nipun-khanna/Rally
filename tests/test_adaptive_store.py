import pytest

from app.adaptive.store import AdaptiveStore


def test_request_is_durable_and_idempotent(tmp_path):
    path = tmp_path / 'state.sqlite3'
    store = AdaptiveStore(path)
    first = store.create_request('iMessage;+;group', 'message-1', 'Rally find a place')
    second = AdaptiveStore(path).create_request('iMessage;+;group', 'message-1', 'Rally find a place')
    assert first['id'] == second['id']
    assert first['status'] == 'pending'
    assert store.get_request(first['id'])['chat_id'] == 'iMessage;+;group'
    with pytest.raises(ValueError):
        store.create_request('iMessage;+;group', 'message-1', 'Different text for same ID')


def test_plan_revision_and_exact_approval(tmp_path):
    store = AdaptiveStore(tmp_path/'state.sqlite3')
    request = store.create_request('iMessage;+;group', 'm1', 'Rally help')
    plan = store.set_plan(request['id'], 1, [{'tool':'send_message','args':{'text':'Hi'},'effect':'commitment'}])
    assert plan['revision'] == 2 and plan['status'] == 'awaiting_approval'
    with pytest.raises(ValueError):
        store.claim_step(request['id'], 0, 2)
    assert store.approve_step(request['id'], 0, 2, plan['steps'][0]['args_hash'], 'approval-1')
    assert not store.approve_step(request['id'], 0, 2, plan['steps'][0]['args_hash'], 'approval-1')
    claimed = store.claim_step(request['id'], 0, 2)
    assert claimed['status'] == 'running'
    with pytest.raises(ValueError):
        store.approve_step(request['id'], 0, 2, 'wrong-hash', 'approval-2')
    store.complete_step(request['id'], 0, 'complete', {'sent':True})
    assert store.get_request(request['id'])['steps'][0]['status'] == 'complete'


def test_new_plan_invalidates_old_approval_and_stale_revision(tmp_path):
    store = AdaptiveStore(tmp_path/'state.sqlite3')
    request = store.create_request('iMessage;+;group', 'm1', 'Rally help')
    old = store.set_plan(request['id'], 1, [{'tool':'send_message','args':{'text':'Old'},'effect':'commitment'}])
    store.approve_step(request['id'], 0, 2, old['steps'][0]['args_hash'], 'approval-1')
    new = store.set_plan(request['id'], 2, [{'tool':'send_message','args':{'text':'New'},'effect':'commitment'}])
    assert new['revision'] == 3
    with pytest.raises(ValueError):
        store.claim_step(request['id'], 0, 2)
    with pytest.raises(ValueError):
        store.claim_step(request['id'], 0, 3)
    assert not store.approve_step(request['id'], 0, 3, old['steps'][0]['args_hash'], 'approval-1')


def test_restart_quarantines_running_step_and_workflow_has_no_approval(tmp_path):
    path = tmp_path/'state.sqlite3'
    store = AdaptiveStore(path)
    request = store.create_request('iMessage;+;group', 'm1', 'Rally status')
    plan = store.set_plan(request['id'], 1, [{'tool':'plan_status','args':{},'effect':'read'}])
    store.claim_step(request['id'], 0, plan['revision'])
    recovered = AdaptiveStore(path)
    assert recovered.get_request(request['id'])['status'] == 'uncertain'
    assert recovered.get_request(request['id'])['steps'][0]['status'] == 'uncertain'
    with pytest.raises(ValueError):
        recovered.claim_step(request['id'], 0, plan['revision'])
    workflow = recovered.save_workflow('iMessage;+;group','status',[{'tool':'plan_status','args':{},'effect':'read'}])
    assert workflow['steps'][0]['tool'] == 'plan_status'
    assert 'approved' not in str(workflow).lower()
    with pytest.raises(ValueError):
        recovered.get_workflow(workflow['id'], 'iMessage;+;other')
    with pytest.raises(ValueError):
        recovered.save_workflow('iMessage;+;group', 'invalid',
                                [{'tool':'plan_status','args':{},'effect':'read','approved':True}])


def test_missing_capability_is_durable_and_chat_scoped(tmp_path):
    store = AdaptiveStore(tmp_path/'state.sqlite3')
    request = store.create_request('chat-a', 'm1', 'Rally order food')
    store.record_missing(request['id'], 1, 'order_food')
    saved = AdaptiveStore(tmp_path/'state.sqlite3').get_request(request['id'])
    assert saved['status'] == 'blocked'
    assert saved['missing_capability'] == 'order_food'
    assert saved['chat_id'] == 'chat-a'
    with pytest.raises(ValueError):
        store.record_missing(request['id'], 1, 'different')
