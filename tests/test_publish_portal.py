import pytest
from types import SimpleNamespace

from app.config import Settings
from app.portal_store import PortalStore
from app.store import Store
from scripts.publish_portal import publish


def test_publication_requires_explicit_enablement(tmp_path, monkeypatch):
    monkeypatch.delenv("RALLY_PORTAL_PUBLISH_APPROVED", raising=False)
    settings = Settings.from_env({"RALLY_DATABASE_PATH": str(tmp_path / "rally.sqlite3")})
    with pytest.raises(RuntimeError, match="not been enabled"):
        publish(settings, output_dir=tmp_path / "portal_build")


def test_publication_skips_unchanged_and_retires_previous_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("RALLY_PORTAL_PUBLISH_APPROVED", "1")
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    chat = "iMessage;+;group"
    portal.ensure_group(chat)
    portal.upsert_messages(chat, [{"message_id": "m1", "sender_id": "a", "text": "Dinner?",
                                  "sent_at": "2026-09-25"}])
    portal.set_import_state(chat, cursor="1", status="complete")
    settings = Settings.from_env({"RALLY_DATABASE_PATH": str(db),
                                  "RALLY_ALLOWED_CHAT_GUIDS": chat})
    calls = []
    deployments = iter(["https://rallyplans-one.vercel.app", "https://rallyplans-two.vercel.app"])

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=next(deployments) if command[1] == "deploy" else "")

    monkeypatch.setattr("scripts.publish_portal.subprocess.run", fake_run)
    output = tmp_path / "portal_build"
    assert publish(settings, output_dir=output) == "published"
    assert publish(settings, output_dir=output) == "unchanged"
    portal.upsert_messages(chat, [{"message_id": "m2", "sender_id": "a", "text": "Tomorrow?",
                                  "sent_at": "2026-09-26"}])
    assert publish(settings, output_dir=output) == "published"
    assert [command[1] for command in calls] == ["link", "deploy", "link", "deploy", "rm"]
    assert calls[-1][2] == "https://rallyplans-one.vercel.app"


def test_live_publish_does_not_wait_for_complete_import(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from app.models import ChatMessage, PlanFacts
    from scripts.publish_portal import publish_live

    monkeypatch.setenv("RALLY_PORTAL_PUBLISH_APPROVED", "1")
    db = tmp_path / "rally.sqlite3"
    store = Store(db)
    portal = PortalStore(db)
    chat = "iMessage;+;group"
    other = "iMessage;+;pending"
    portal.ensure_group(chat)
    portal.ensure_group(other)
    portal.set_import_state(chat, cursor="1", status="pending")
    portal.set_import_state(other, cursor="1", status="pending")
    store.add_message(ChatMessage("m1", chat, "a", "dinner near taj, atlanta, indian",
                                  datetime(2026, 9, 26, tzinfo=timezone.utc)))
    store.save_plan(chat, PlanFacts(activity="dinner", location="taj, atlanta",
                                    preferred_cuisines=["indian"]),
                    datetime(2026, 9, 26, tzinfo=timezone.utc))
    settings = Settings.from_env({"RALLY_DATABASE_PATH": str(db),
                                  "RALLY_ALLOWED_CHAT_GUIDS": f"{chat},{other}"})
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="https://rallyplans-live.vercel.app")

    monkeypatch.setattr("scripts.publish_portal.subprocess.run", fake_run)
    output = tmp_path / "portal_build"
    assert publish(settings, output_dir=output) == "waiting for complete history import"
    assert publish_live(settings, chat, output_dir=output) == "published"
    public_id = portal.ensure_group(chat)
    html = (output / public_id / "index.html").read_text(encoding="utf-8").lower()
    assert "taj" in html and "atlanta" in html and "indian" in html
    assert [command[1] for command in calls] == ["link", "deploy"]
