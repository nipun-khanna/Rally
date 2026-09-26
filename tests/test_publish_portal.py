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
