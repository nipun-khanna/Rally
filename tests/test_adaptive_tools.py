import pytest

from app.adaptive.tools import ToolRegistry, ToolSpec, build_default_registry


def test_unknown_tool_and_strict_arguments():
    registry = ToolRegistry({'chat-a'})
    registry.register(ToolSpec('echo', {'text': str}, 'read', lambda chat_id, args: args['text']))
    with pytest.raises(ValueError):
        registry.execute('missing', {}, chat_id='chat-a')
    with pytest.raises(ValueError):
        registry.execute('echo', {'text': 'hi', 'extra': 'leak'}, chat_id='chat-a')
    with pytest.raises(ValueError):
        registry.execute('echo', {'text': 1}, chat_id='chat-a')
    with pytest.raises(ValueError):
        registry.execute('echo', {}, chat_id='chat-a')


def test_cross_chat_rejected_before_handler():
    calls = []
    registry = ToolRegistry({'chat-a'})
    registry.register(ToolSpec('echo', {'text': str}, 'read', lambda chat_id, args: calls.append(chat_id)))
    with pytest.raises(PermissionError):
        registry.execute('echo', {'text': 'hi'}, chat_id='chat-b')
    assert calls == []


def test_commitment_requires_exact_approval():
    calls = []
    registry = ToolRegistry({'chat-a'})
    registry.register(ToolSpec('send', {'text': str}, 'commitment', lambda chat_id, args: calls.append(args['text'])))
    with pytest.raises(PermissionError):
        registry.execute('send', {'text': 'hi'}, chat_id='chat-a')
    with pytest.raises(PermissionError):
        registry.execute('send', {'text': 'hi'}, chat_id='chat-a', approval=lambda *args: False,
                         request_id='req', step_index=0, revision=2)
    assert calls == []
    seen = []
    def approval(chat_id, request_id, step_index, revision, args_hash):
        seen.append((chat_id, request_id, step_index, revision, args_hash))
        return True
    registry.execute('send', {'text': 'hi'}, chat_id='chat-a', approval=approval,
                     request_id='req', step_index=0, revision=2)
    assert calls == ['hi']
    assert seen[0][:4] == ('chat-a', 'req', 0, 2)
    assert len(seen[0][4]) == 64


def test_default_tools_are_read_only_and_scoped():
    calls = []
    class Store:
        def get_plan(self, chat_id):
            calls.append(('plan', chat_id))
            return None
    def web(request, *, tone):
        calls.append(('web', request, tone))
        return 'answer'
    registry = build_default_registry({'chat-a'}, plan_store=Store(), web_answer_fn=web)
    assert registry.names() == ('get_plan_status', 'web_research')
    assert registry.execute('get_plan_status', {}, chat_id='chat-a') == {'status': 'none'}
    assert registry.execute('web_research', {'request': 'pizza in Atlanta', 'tone': 'casual'},
                            chat_id='chat-a', current_request='pizza in Atlanta') == 'answer'
    assert calls == [('plan', 'chat-a'), ('web', 'pizza in Atlanta', 'casual')]
    with pytest.raises(ValueError):
        registry.execute('web_research', {'request': 'x', 'tone': 'robot'}, chat_id='chat-a',
                         current_request='x')
    with pytest.raises(PermissionError):
        registry.execute('web_research', {'request': 'other text', 'tone': 'casual'}, chat_id='chat-a',
                         current_request='pizza in Atlanta')
    with pytest.raises(PermissionError):
        registry.execute('get_plan_status', {}, chat_id='chat-b')
