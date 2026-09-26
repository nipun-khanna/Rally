from datetime import datetime, timezone
from unittest.mock import patch

from app.config import Settings, build_service
from app.models import ChatMessage


def test_configured_service_records_missing_capability_and_private_code_proposal(tmp_path):
    settings=Settings.from_env({'RALLY_DATABASE_PATH':str(tmp_path/'rally.sqlite3'),
                                'RALLY_XAI_API_KEY':'test-key',
                                'RALLY_ALLOWED_CHAT_GUIDS':'chat-a'})
    calls=[]
    def model_call(self,schema,prompt,data):
        calls.append((schema.__name__,data))
        if schema.__name__=='PlanningDecision':
            return {'steps':[], 'missing_capability':'build_tracker'}
        return {'source':'raise RuntimeError("never executed")',
                'summary':'Proposed tracker','dependencies':[],
                'proposed_tests':['test tracker'],
                'tool_schema':{'name':'build_tracker'}}
    sent=[]
    with patch('app.agent.GrokClient._call',model_call):
        service=build_service(settings)
        service.send_fn=lambda chat,text:sent.append((chat,text))
        message=ChatMessage('m1','chat-a','member','Rally build me a tracker',
                            datetime.now(timezone.utc))
        assert service.receive(message)
        assert not service.receive(message)
    assert len(calls)==2
    assert set(calls[0][1])=={'request','tools'}
    assert sent[0][0]=='chat-a'
    assert 'not been run' in sent[0][1]
    request=service.adaptive_handler.store.create_request('chat-a','m1',message.text)
    assert request['status']=='pending_review'
    assert service.adaptive_handler.proposal_generator.store.get(
        request['capability_proposal_id'])['status']=='pending_review'
