import logging
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agent import GrokProviderError
from app.config import Settings, build_service
from app.main import create_app


def test_configurable_extraction_timeout_is_wired(tmp_path):
    settings = Settings.from_env({'RALLY_DATABASE_PATH': str(tmp_path / 'state.sqlite3'),
                                  'RALLY_GROK_EXTRACTION_TIMEOUT': '90'})
    assert settings.grok_extraction_timeout == 90
    assert build_service(settings).agent.extraction_timeout == 90
    for invalid in ('0', '121', 'nan'):
        try:
            Settings.from_env({'RALLY_GROK_EXTRACTION_TIMEOUT': invalid})
        except ValueError:
            continue
        raise AssertionError('Invalid extraction budget accepted')


def test_webhook_provider_failure_logs_only_safe_stage(tmp_path, caplog):
    settings = Settings.from_env({'RALLY_DATABASE_PATH': str(tmp_path / 'state.sqlite3')})
    service = build_service(settings)
    payload = {'type': 'new-message', 'data': {'guid': 'diagnostic-1', 'text': 'secret conversation',
               'isFromMe': False, 'handle': {'address': 'secret sender'},
               'chats': [{'guid': 'iMessage;+;test'}], 'dateCreated': 1790438400000}}
    with TestClient(create_app(service, webhook_token='secret-token', schedule=False)) as client:
        with patch.object(service, 'receive', side_effect=GrokProviderError('timeout', 'extracted')):
            with caplog.at_level(logging.WARNING, logger='app.main'):
                response = client.post('/webhooks/bluebubbles?token=secret-token', json=payload)
    assert response.status_code == 503
    assert 'extracted' in caplog.text and 'timeout' in caplog.text
    assert 'secret' not in caplog.text


def test_private_monitor_failure_does_not_skip_reminders_or_group_tick(caplog):
    import asyncio
    from types import SimpleNamespace
    from app.main import _run_scheduled_checks

    calls = []
    def broken_monitor():
        calls.append('monitor')
        raise RuntimeError('secret private text')
    private = SimpleNamespace(learner=SimpleNamespace(sync=broken_monitor),
                              tick=lambda: calls.append('reminders'))
    group = SimpleNamespace(tick=lambda: calls.append('groups'))
    with caplog.at_level(logging.WARNING, logger='app.main'):
        asyncio.run(_run_scheduled_checks(private, group))
    assert calls == ['monitor', 'reminders', 'groups']
    assert 'RuntimeError' in caplog.text
    assert 'secret' not in caplog.text
