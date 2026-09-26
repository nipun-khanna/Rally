from types import SimpleNamespace
from app.policy import explicitly_addresses_rally
from app.portal_commands import portal_reply


def test_rally_turn_on_is_explicit():
    assert explicitly_addresses_rally('rally turn on history for this group chat')
    assert explicitly_addresses_rally('Rally')


def test_history_disabled_command_explains_without_mutating():
    class NoWrites:
        def update_settings(self, *args, **kwargs):
            raise AssertionError('Disabled history must not change settings')
    message = SimpleNamespace(text='rally turn on history for this group chat', chat_id='group')
    answer = portal_reply(message, NoWrites(), 'https://rallyplans.vercel.app', history_enabled=False)
    assert 'disabled' in answer.lower()


def test_rally_natural_context_request_is_explicit():
    assert explicitly_addresses_rally('rally we are currently in rambler atlanta apartments and wanna get some eats nearby where should we go?')
    assert explicitly_addresses_rally('rally I need help figuring out dinner')
    assert explicitly_addresses_rally('rally dinner nearby?')
    assert explicitly_addresses_rally('Rally is a helpful bot')
    assert not explicitly_addresses_rally('We should ask Rally for help')


def test_any_addressed_wording_replies():
    for text in ["Rally pizza", "@Rally 👋", "yo rally sup", "Rally thanks", "rally we need dinner"]:
        assert explicitly_addresses_rally(text)
