from datetime import datetime, timezone

from app.adaptive.agent import AdaptivePlanner
from app.adaptive.handler import AdaptiveHandler, should_use_adaptive
from app.adaptive.store import AdaptiveStore
from app.adaptive.tools import ToolRegistry, ToolSpec
from app.models import ChatMessage


def test_adaptive_intent_does_not_steal_status_or_web_requests():
    assert should_use_adaptive('Rally, can you automate the follow-up?')
    assert should_use_adaptive('Hey Rally build me a tracker')
    assert not should_use_adaptive('Rally, what is the plan?')
    assert not should_use_adaptive('Rally find food nearby')


def test_missing_capability_recorded_once(tmp_path):
    calls=[]
    tools=ToolRegistry({'chat-a'})
    planner=AdaptivePlanner(lambda *_: calls.append(1) or
                            {'steps':[], 'missing_capability':'order_food'})
    handler=AdaptiveHandler(AdaptiveStore(tmp_path/'state.sqlite3'), planner, tools)
    message=ChatMessage('m1','chat-a','member','Rally, can you order food?',
                        datetime.now(timezone.utc))
    assert 'order_food' in handler.answer(message)
    assert 'order_food' in handler.answer(message)
    assert len(calls)==1


def test_read_step_is_executed_once_in_same_chat(tmp_path):
    calls=[]
    tools=ToolRegistry({'chat-a'})
    tools.register(ToolSpec('get_plan_status', {}, 'read',
                            lambda chat_id,args: calls.append(chat_id) or {'status':'none'}))
    planner=AdaptivePlanner(lambda *_: {'steps':[{'tool':'get_plan_status','args':{}}],
                                        'missing_capability':None})
    handler=AdaptiveHandler(AdaptiveStore(tmp_path/'state.sqlite3'),planner,tools)
    message=ChatMessage('m1','chat-a','member','Rally, use tools to check status',
                        datetime.now(timezone.utc))
    assert 'none' in handler.answer(message)
    assert 'complete' in handler.answer(message)
    assert calls==['chat-a']


def test_missing_capability_generates_inert_review_artifact(tmp_path):
    from app.adaptive.proposals import CapabilityProposalStore
    from app.adaptive.generator import CapabilityProposalGenerator
    tools=ToolRegistry({'chat-a'})
    planner=AdaptivePlanner(lambda *_: {'steps':[], 'missing_capability':'build_tracker'})
    proposals=CapabilityProposalStore(tmp_path/'proposals')
    generator=CapabilityProposalGenerator(lambda _: {
        'source':'open("/tmp/not-run", "w")', 'summary':'Draft tracker',
        'dependencies':[], 'proposed_tests':[], 'tool_schema':{'name':'build_tracker'}}, proposals)
    store=AdaptiveStore(tmp_path/'state.sqlite3')
    handler=AdaptiveHandler(store,planner,tools,generator)
    message=ChatMessage('m1','chat-a','member','Rally build me a tracker',
                        datetime.now(timezone.utc))
    assert 'developer review' in handler.answer(message)
    saved=store.create_request('chat-a','m1',message.text)
    assert saved['status']=='pending_review'
    assert proposals.get(saved['capability_proposal_id'])['status']=='pending_review'


def test_existing_direct_routes_keep_priority_and_adaptive_reply_is_same_chat(tmp_path):
    from app.orchestrator import RallyService
    from app.store import Store
    class Agent:
        def answer_direct(self, request, facts, messages):
            return 'normal reply'
        def extract(self, messages, previous):
            raise AssertionError('adaptive request should not enter group extraction')
    class Handler:
        def __init__(self): self.calls=[]
        def answer(self, message):
            self.calls.append(message.message_id)
            return 'adaptive reply'
    sent=[]
    handler=Handler()
    service=RallyService(Store(tmp_path/'messages.sqlite3'),Agent(),lambda _:[],
                         lambda chat,text:sent.append((chat,text)),
                         allowed_chat_ids={'chat-a'}, adaptive_handler=handler)
    message=ChatMessage('m1','chat-a','member','Rally build me a tracker',
                        datetime.now(timezone.utc))
    assert service.receive(message)
    assert not service.receive(message)
    assert handler.calls==['m1']
    assert sent==[('chat-a','Rally: adaptive reply')]


def test_review_route_requires_local_admin_token_and_excludes_public_portal(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.orchestrator import RallyService
    from app.store import Store
    class Agent: pass
    service=RallyService(Store(tmp_path/'messages.sqlite3'),Agent(),lambda _:[],
                         lambda chat,text:None,allowed_chat_ids={'chat-a'})
    adaptive_store=AdaptiveStore(tmp_path/'messages.sqlite3')
    request=adaptive_store.create_request('chat-a','m1','Rally build a tracker')
    service.adaptive_handler=AdaptiveHandler(adaptive_store, None, ToolRegistry({'chat-a'}))
    app=create_app(service,webhook_token='secret',admin_token='admin-secret',schedule=False)
    client=TestClient(app)
    path=f"/adaptive/admin/requests/{request['id']}"
    assert client.get(path).status_code==403
    assert client.get(path,params={'token':'secret'}).status_code==403
    response=client.get(path,headers={'X-Rally-Admin-Token':'admin-secret'})
    assert response.status_code==200
    assert response.json()['request']['id']==request['id']
    assert 'source' not in response.json()
