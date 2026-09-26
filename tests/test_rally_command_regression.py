from types import SimpleNamespace
from app.policy import explicitly_addresses_rally
from app.portal_commands import portal_reply


def test_rally_turn_on_is_explicit():
    assert explicitly_addresses_rally('rally turn on history for this group chat')
    assert not explicitly_addresses_rally('Rally turned up yesterday')


def test_history_disabled_command_explains_without_mutating():
    class NoWrites:
        def update_settings(self, *args, **kwargs):
            raise AssertionError('Disabled history must not change settings')
    message = SimpleNamespace(text='rally turn on history for this group chat', chat_id='group')
    answer = portal_reply(message, NoWrites(), 'https://rallyplans.vercel.app', history_enabled=False)
    assert 'disabled' in answer.lower()
