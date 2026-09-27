import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.browser.store import BrowserStore


NOW = datetime(2026, 9, 26, 21, 0, tzinfo=timezone.utc)
OWNER = "iMessage;-;owner"
SENDER = "+15555550123"


def store(tmp_path) -> BrowserStore:
    return BrowserStore(tmp_path / "rally.sqlite3")


def test_request_is_deduplicated_by_chat_and_message(tmp_path):
    db = store(tmp_path)
    first = db.create_request(OWNER, "m1", "Open public.test", sender_id=SENDER)
    second = db.create_request(OWNER, "m1", "Open public.test", sender_id=SENDER)
    assert first["id"] == second["id"]
    assert first["status"] == "pending"
    with pytest.raises(ValueError):
        db.create_request(OWNER, "m1", "Different text", sender_id=SENDER)


def test_owner_rows_cannot_be_read_or_approved_from_another_chat(tmp_path):
    db = store(tmp_path)
    row = db.create_request(OWNER, "m1", "Open public.test", sender_id=SENDER)
    db.create_approval(row["id"], "ABCD12", "digest-1", NOW + timedelta(minutes=10))
    with pytest.raises(PermissionError):
        db.get_request("iMessage;+;group", "m1")
    with pytest.raises(PermissionError):
        db.resolve_approval("iMessage;+;group", SENDER, "ABCD12", True)
    with pytest.raises(PermissionError):
        db.resolve_approval(OWNER, "intruder", "ABCD12", True)


def test_approval_codes_are_hashed_and_not_stored_in_cleartext(tmp_path):
    db = store(tmp_path)
    row = db.create_request(OWNER, "m1", "Submit the form", sender_id=SENDER)
    db.create_approval(row["id"], "ZX9K2Q", "digest-1", NOW + timedelta(minutes=10))
    raw = (tmp_path / "rally.sqlite3").read_bytes()
    assert b"ZX9K2Q" not in raw
    expected = hashlib.sha256(b"ZX9K2Q").hexdigest()
    assert db.approval_code_hash(row["id"]) == expected


def test_changed_digest_or_expiry_or_cancel_blocks_approval(tmp_path):
    db = store(tmp_path)
    row = db.create_request(OWNER, "m1", "Submit the form", sender_id=SENDER)
    db.set_action_digest(row["id"], "digest-old")
    db.create_approval(row["id"], "CODE01", "digest-old", NOW + timedelta(minutes=10))
    with pytest.raises(PermissionError):
        db.resolve_approval(OWNER, SENDER, "CODE01", True, expected_digest="digest-new")
    db.create_approval(row["id"], "CODE02", "digest-old", NOW - timedelta(seconds=1))
    with pytest.raises(PermissionError):
        db.resolve_approval(OWNER, SENDER, "CODE02", True, now=NOW)
    db.create_approval(row["id"], "CODE03", "digest-old", NOW + timedelta(minutes=10))
    cancelled = db.resolve_approval(OWNER, SENDER, "CODE03", False, now=NOW)
    assert cancelled["status"] == "cancelled"
    with pytest.raises(PermissionError):
        db.resolve_approval(OWNER, SENDER, "CODE03", True, now=NOW)


def test_failed_request_can_be_retried_for_same_message(tmp_path):
    db = store(tmp_path)
    row = db.create_request(OWNER, "m1", "Search italian midtown", sender_id=SENDER)
    db.mark_status(row["id"], "failed")
    retried = db.create_request(OWNER, "m1", "Search italian midtown", sender_id=SENDER)
    assert retried["id"] == row["id"]
    assert retried["status"] == "pending"


def test_running_requests_become_uncertain_on_restart_and_are_not_replayed(tmp_path):
    path = tmp_path / "rally.sqlite3"
    db = BrowserStore(path)
    row = db.create_request(OWNER, "m1", "Click submit", sender_id=SENDER)
    db.mark_running(row["id"])
    recovered = BrowserStore(path)
    loaded = recovered.get_request(OWNER, "m1")
    assert loaded["status"] == "uncertain"
    assert recovered.take_replayable(OWNER, "m1") is None
