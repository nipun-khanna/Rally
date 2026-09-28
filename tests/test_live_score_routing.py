from datetime import datetime, timedelta, timezone

from app.browser.handler import BrowserInbound
from app.group_turns import GroupTurnStore
from app.models import ChatMessage
from app.orchestrator import RallyService
from app.store import Store
from app.web import GrokWebClient

NOW = datetime(2026, 9, 27, 12, 41, tzinfo=timezone.utc)
GROUP = 'iMessage;+;sports'
QUESTION = 'rally whats the score of the georgia ech standford game'

class NoConversation:
    def answer_direct(self, *args):
        return 'UNVERIFIED 31-28'
    def extract(self, *args):
        from app.models import PlanFacts
        return PlanFacts()

def build(tmp_path):
    store = Store(tmp_path / 'r.sqlite3')
    queries, sent = [], []
    service = RallyService(store, NoConversation(), lambda _: [],
        lambda chat, text: sent.append((chat, text)),
        group_turns=GroupTurnStore(tmp_path / 'r.sqlite3'),
        web_answer_fn=lambda request, **kwargs: queries.append(request) or 'Verified result: https://sports.example.com/game')
    return service, queries, sent

def test_initial_score_and_two_followups_retain_matchup(tmp_path):
    service, queries, sent = build(tmp_path)
    for i, text in enumerate((QUESTION, 'can you pull it live', 'just search for the scores')):
        assert service.receive(ChatMessage(f'm{i}', GROUP, 'friend', text, NOW + timedelta(seconds=i*20)))
    assert len(queries) == 3
    assert all('georgia' in q.lower() and 'standford' in q.lower() for q in queries)
    assert all('UNVERIFIED' not in text for _, text in sent)

def test_score_search_bypasses_generic_browser_interception(tmp_path):
    class NoBrowser:
        def run(self, *args):
            raise AssertionError('score request must reach grounded web answer, not open generic Bing')
    inbound = BrowserInbound('', '', NoBrowser(), lambda *args: None,
        allowed_chat_ids={GROUP}, group_turns=GroupTurnStore(tmp_path/'r.sqlite3'))
    payload = {'type':'new-message','data':{'guid':'score','text':'Rally just search for the scores',
        'isFromMe':False,'dateCreated':int(NOW.timestamp()*1000),'handle':{'address':'friend'},'chats':[{'guid':GROUP}]}}
    assert inbound.try_receive(payload) is None


def test_place_lookup_bypasses_browser_for_web_search():
    class NoBrowser:
        def run(self, *args):
            raise AssertionError('place lookup must use web search, not the browser')
    inbound = BrowserInbound('', '', NoBrowser(), lambda *args: None, allowed_chat_ids={GROUP})
    payload = {'type':'new-message','data':{'guid':'pizza','text':'Rally, name one pizza place near downtown Atlanta',
        'isFromMe':False,'dateCreated':int(NOW.timestamp()*1000),'handle':{'address':'friend'},'chats':[{'guid':GROUP}]}}
    assert inbound.try_receive(payload) is None

def test_context_never_comes_from_other_chat_or_expired_request(tmp_path):
    service, queries, sent = build(tmp_path)
    service.store.add_message(ChatMessage('old', GROUP, 'friend', QUESTION, NOW-timedelta(minutes=6)))
    service.store.add_message(ChatMessage('other', 'iMessage;+;other', 'friend', QUESTION, NOW))
    assert service.receive(ChatMessage('new', GROUP, 'friend','Rally search for the scores',NOW))
    assert all('georgia' not in q.lower() for q in queries)

def provider_result(text, *, searched=False, cited=False):
    outputs = [{'type':'web_search_call','status':'completed'}] if searched else []
    outputs.append({'type':'message','role':'assistant','status':'completed','content':[
        {'type':'output_text','text':text,'annotations':[{'type':'url_citation','url':'https://sports.example.com/game'}] if cited else []}]})
    return {'status':'completed','output':outputs}

def test_score_answers_require_real_search_and_source():
    for searched, cited in ((False,False),(False,True),(True,False)):
        calls = []
        client = GrokWebClient('key',transport=lambda p:calls.append(p) or provider_result('Tech leads 31-28',searched=searched,cited=cited))
        answer = client.answer(QUESTION)
        assert '31-28' not in answer
        assert 'verify' in answer.lower()
        assert calls[0]['tool_choice'] == 'required'

def test_retrieved_score_has_source_and_check_time():
    client = GrokWebClient('key',transport=lambda _:provider_result('Tech leads 31-28, fourth quarter.',searched=True,cited=True))
    answer = client.answer(QUESTION)
    assert '31-28' in answer and 'https://sports.example.com/game' in answer
    assert 'UTC' in answer

def test_webhook_entire_score_followup_chain_uses_research_not_browser(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    service, queries, sent = build(tmp_path)
    class NoBrowser:
        def run(self, *args):
            raise AssertionError('must not open generic search results')
    inbound = BrowserInbound('', '', NoBrowser(), lambda *args: None,
        allowed_chat_ids={GROUP}, group_turns=service.group_turns)
    with TestClient(create_app(service, webhook_token='secret', schedule=False,
                              browser_inbound=inbound)) as client:
        for i, text in enumerate((QUESTION, 'can you pull it live', 'just search for the scores')):
            p = {'type':'new-message','data':{'guid':f'http-{i}','text':text,
                'isFromMe':False,'dateCreated':int((NOW+timedelta(seconds=i*20)).timestamp()*1000),
                'handle':{'address':'friend'},'chats':[{'guid':GROUP}]}}
            assert client.post('/webhooks/bluebubbles?token=secret',json=p).json()['accepted']
    assert len(queries) == 3
    assert all('georgia' in q.lower() and 'standford' in q.lower() for q in queries)
    assert len(sent) == 3
    assert all('Source' in text or 'https://' in text for _, text in sent)


def test_unrelated_intervening_topic_does_not_reuse_sports_request(tmp_path):
    service, queries, sent = build(tmp_path)
    service.store.add_message(ChatMessage('old', GROUP, 'friend', QUESTION, NOW-timedelta(seconds=30)))
    service.store.add_message(ChatMessage('topic',GROUP,'friend','Rally what is our dinner plan?',NOW-timedelta(seconds=10)))
    service.receive(ChatMessage('new',GROUP,'friend','Rally search for the scores',NOW))
    assert all('georgia' not in q.lower() for q in queries)


def test_web_disabled_never_invents_a_score(tmp_path):
    service, queries, sent = build(tmp_path)
    service.web_answer_fn = None
    service.receive(ChatMessage('score',GROUP,'friend',QUESTION,NOW))
    assert len(sent) == 1
    assert 'verify' in sent[0][1] and 'UNVERIFIED' not in sent[0][1]
