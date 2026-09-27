import logging

from app.browser.log import action_summary, chat_label, configure_browser_logging, safe_url
from app.browser.runtime import death_reason


def test_chat_label_redacts_guid_and_marks_self_dm():
    label = chat_label("any;-;+15555550100")
    assert "kind=self-dm" in label
    assert "50100" in label
    assert "+15555550100" not in label
    assert "any;-;" not in label


def test_chat_label_marks_group():
    label = chat_label("any;+;chat000000000000000001")
    assert "kind=group" in label
    assert "000001" in label
    assert "chat000000000000000001" not in label


def test_safe_url_drops_userinfo_and_query():
    assert safe_url("https://user:token@example.com/path?q=secret") == "https://example.com/path"
    assert safe_url("") == ""


def test_action_summary_redacts_fill_text():
    text = action_summary({
        "action": "fill", "role": "textbox", "name": "Password", "text": "stolen",
    })
    assert "stolen" not in text
    assert "text=redacted" in text
    assert "action=fill" in text


def test_death_reason_matches_closed_target():
    assert death_reason(RuntimeError("TargetClosedError: browser has been closed")) == "targetclosed"
    assert death_reason(ValueError("unsupported")) is None
    assert death_reason(RuntimeError("Playwright Sync API inside the asyncio loop")) is None


def test_debug_flag_sets_logger_level(monkeypatch):
    monkeypatch.setenv("RALLY_BROWSER_DEBUG", "1")
    logger = configure_browser_logging()
    assert logger.level == logging.DEBUG
    monkeypatch.setenv("RALLY_BROWSER_DEBUG", "0")
    logger = configure_browser_logging()
    assert logger.level == logging.INFO
