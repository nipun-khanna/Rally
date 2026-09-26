import unittest
from unittest.mock import patch
import httpx
from app.agent import GrokProviderError
from app.web import GrokWebClient


def result(text='Public result', annotations=None):
    return {'status': 'completed', 'output': [
        {'type': 'reasoning', 'content': [{'type': 'output_text', 'text': 'SECRET'}]},
        {'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [
            {'type': 'output_text', 'text': text, 'annotations': annotations or []}]}]}


class WebTests(unittest.TestCase):
    def test_request_only_permits_bounded_web_search(self):
        calls = []
        client = GrokWebClient('key', transport=lambda payload: calls.append(payload) or result())
        self.assertEqual(client.answer('Find dinner', None, []), 'Public result')
        payload = calls[0]
        self.assertEqual(payload['tools'], [{'type': 'web_search'}])
        self.assertEqual(payload['tool_choice'], 'auto')
        self.assertFalse(payload['store'])
        self.assertEqual(payload['max_tool_calls'], 3)
        self.assertLessEqual(payload['max_output_tokens'], 1500)
        self.assertIn('personal identifiers', payload['input'][0]['content'])

    def test_citations_become_plain_urls_and_annotations_deduplicate(self):
        url = 'https://example.com/place'
        annotations = [{'type': 'url_citation', 'url': url}, {'type': 'url_citation', 'url': 'https://example.org/source'}]
        text = 'Try [Place](https://example.com/place) [[1]](https://example.com/place).'
        reply = GrokWebClient('key', transport=lambda _: result(text, annotations)).answer('dinner', None, [])
        self.assertIn(url, reply)
        self.assertIn('https://example.org/source', reply)
        self.assertNotIn('](', reply)
        self.assertEqual(reply.count('https://example.org/source'), 1)
        self.assertNotIn('SECRET', reply)

    def test_unsafe_citations_fail_safe(self):
        for url in ('http://localhost/a', 'http://127.0.0.1/a', 'http://192.168.1.1/a', 'http://[::1]/a', 'https://user:password@example.com/a', 'javascript:alert(1)', 'http://host.local/a'):
            with self.subTest(url=url), self.assertRaises(GrokProviderError):
                GrokWebClient('key', transport=lambda _: result('Answer', [{'type':'url_citation', 'url':url}])).answer('q', None, [])

    def test_incomplete_and_malformed_outputs_fail_safe(self):
        for raw in ({}, {'status':'incomplete','output':[]}, {'status':'completed','output':[]}, {'status':'completed','output':[{'type':'message','role':'assistant','status':'in_progress','content':[]}]}):
            with self.subTest(raw=raw), self.assertRaises(GrokProviderError):
                GrokWebClient('key', transport=lambda _:raw).answer('q', None, [])

    def test_timeout_is_redacted_and_never_retried(self):
        with patch('app.web.httpx.post', side_effect=httpx.ReadTimeout('SECRET KEY')) as post:
            with self.assertRaises(GrokProviderError) as error:
                GrokWebClient('secret').answer('q', None, [])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(error.exception.kind, 'timeout')
        self.assertEqual(error.exception.stage, 'webanswer')
        self.assertNotIn('SECRET', str(error.exception))

    def test_missing_key_never_calls_provider(self):
        with patch('app.web.httpx.post') as post, self.assertRaises(GrokProviderError):
            GrokWebClient('').answer('q', None, [])
        post.assert_not_called()

    def test_long_reply_keeps_complete_citation_urls(self):
        url='https://example.com/' + 'a'*180
        reply=GrokWebClient('key', transport=lambda _:result('word '*2000,[{'type':'url_citation','url':url}])).answer('q',None,[])
        self.assertLessEqual(len(reply), 4000)
        self.assertIn(url, reply)


def test_web_request_classifier_catches_public_lookup_without_chat_context():
    from app.web import should_search_web
    assert should_search_web('rally we are in atlanta and want eats nearby where should we go?')
    assert should_search_web('Hey Rally, search the web for a concert')
    assert should_search_web('Rally, what is the weather today?')
    assert not should_search_web('Rally, what is our plan?')
    assert not should_search_web('Rally, hi')


def test_web_tone_is_abstract_label_not_history():
    calls=[]
    client=GrokWebClient('key',transport=lambda payload:calls.append(payload) or result())
    client.answer('Rally find food nearby', None, [], tone='casual')
    assert 'casual' in calls[0]['input'][0]['content']
    assert len(calls[0]['input']) == 2


def test_web_quota_is_separate_atomic_daily_budget(tmp_path):
    from app.store import Store
    store=Store(tmp_path/'quota.sqlite3')
    assert store.consume_web_quota('2026-09-26',1)
    assert not store.consume_web_quota('2026-09-26',1)
    assert store.consume_web_quota('2026-09-27',1)


def test_web_quota_zero_disables_local_daily_cap(tmp_path):
    from app.config import Settings
    from app.store import Store
    store=Store(tmp_path/'quota.sqlite3')
    assert Settings.from_env({}).web_daily_limit == 0
    assert store.consume_web_quota('2026-09-26',0)
    assert store.consume_web_quota('2026-09-26',0)
    assert store.consume_web_quota('2026-09-26',1)
    assert not store.consume_web_quota('2026-09-26',1)


def test_service_config_wires_web_budget(tmp_path):
    from app.config import Settings, build_service
    from unittest.mock import patch
    settings=Settings.from_env({'RALLY_DATABASE_PATH':str(tmp_path/'db.sqlite3'),
                                'RALLY_XAI_API_KEY':'key', 'RALLY_WEB_ENABLED':'1',
                                'RALLY_WEB_DAILY_LIMIT':'1', 'RALLY_WEB_MAX_TOOL_CALLS':'2'})
    assert settings.web_enabled and settings.web_daily_limit==1 and settings.web_max_tool_calls==2
    with patch('app.config.GrokWebClient') as web:
        web.return_value.answer.return_value='Found something'
        service=build_service(settings)
        assert service.web_answer_fn('Rally find food',tone='casual')=='Found something'
        assert 'limit' in service.web_answer_fn('Rally find food',tone='casual').lower()
        web.assert_called_once()
        assert web.call_args.kwargs['max_tool_calls']==2
        assert web.return_value.answer.call_count==1
