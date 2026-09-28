import json
from pathlib import Path

from app.portal_store import PortalStore
from app.store import Store
from scripts.export_portal import export_group, export_portal


def test_selected_relationship_sources_are_never_exported(tmp_path):
    from datetime import datetime, timezone
    from app.relationships.store import RelationshipStore
    db = tmp_path / 'r.sqlite3'
    Store(db)
    portal = PortalStore(db)
    chat = 'iMessage;+;group'
    public_id = portal.ensure_group(chat)
    private = RelationshipStore(db)
    private.configure('owner', 'iMessage;-;private', 'UTC')
    private.upsert('owner', 'Secret Friend', 'message', 7, datetime.now(timezone.utc))
    private.add_source('owner', chat, 'Secret Friend')
    portal.upsert_messages(chat, [{'message_id': 'old', 'sender_id': 'person',
                                  'text': 'old private message', 'sent_at': '2026-09-25'}])
    output = tmp_path / 'portal_build'
    summary = export_portal(db, tmp_path / 'media', {chat}, output)
    assert summary['groups'] == 0
    assert not (output / public_id).exists()


def test_export_contains_all_pages_and_visible_media_only(tmp_path):
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    group = "iMessage;+;group"
    public_id = portal.ensure_group(group)
    media_root = tmp_path / "media"
    media_root.mkdir()
    image = media_root / "photo"
    image.write_bytes(b"\x89PNG\r\n\x1a\nimage bytes")
    rows = [{"message_id": f"m{i:03}", "sender_id": "person", "text": "Dinner next week" if i == 0 else f"text {i}",
             "sent_at": f"2026-09-25T12:{i // 60:02}:{i % 60:02}+00:00"} for i in range(101)]
    rows[0]["attachments"] = [{"attachment_id": "a1", "filename": "photo.png",
                                "mime_type": "image/png", "local_path": str(image), "status": "available"}]
    portal.upsert_messages(group, rows)
    output = tmp_path / "portal_build"
    summary = export_portal(db, media_root, {group}, output)
    assert summary == {"groups": 1, "pages": 3, "media": 1}
    assert (output / public_id / "index.html").exists()
    assert (output / public_id / "knowledge" / "index.html").exists()
    kb = json.loads((output / public_id / "kb.json").read_text(encoding="utf-8"))
    assert set(kb) >= {"people", "group", "links", "analytics"}
    assert (output / "api" / "chat.js").exists()
    assert "*/kb.json" in (output / "vercel.json").read_text()
    assert (output / public_id / "history" / "2.html").exists()
    assert len(list((output / public_id / "media").iterdir())) == 1
    assert any(item["text"] == "Dinner next week" for item in json.loads(
        (output / public_id / "history-index.json").read_text(encoding="utf-8")))
    portal.update_settings(group, sections={"media": False, "history": False})
    export_portal(db, media_root, {group}, output)
    assert not (output / public_id / "media").exists()
    assert not (output / public_id / "history-index.json").exists()


def test_active_attachment_is_download_only(tmp_path):
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    group = "iMessage;+;group"
    public_id = portal.ensure_group(group)
    media_root = tmp_path / "media"
    media_root.mkdir()
    file = media_root / "html"
    file.write_text("<script>alert('x')</script>")
    portal.upsert_messages(group, [{"message_id": "m", "sender_id": "a", "text": "file",
        "sent_at": "2026-09-25", "attachments": [{"attachment_id": "danger",
        "filename": "danger.svg", "mime_type": "image/svg+xml", "local_path": str(file),
        "status": "available"}]}])
    output = tmp_path / "portal_build"
    export_portal(db, media_root, {group}, output)
    assert list((output / public_id / "download").iterdir())[0].suffix == ".bin"
    assert not (output / public_id / "media").exists()
    config = json.loads((output / "vercel.json").read_text())
    assert any(rule["source"] == "/:group/download/:file" for rule in config["headers"])


def test_failed_group_refresh_preserves_previous_complete_page(tmp_path, monkeypatch):
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    chat = "iMessage;+;group"
    public_id = portal.ensure_group(chat)
    portal.upsert_messages(chat, [{"message_id": "m1", "sender_id": "a",
                                  "text": "First version", "sent_at": "2026-09-25"}])
    output = tmp_path / "portal_build"
    export_group(db, tmp_path / "media", chat, output)
    page = output / public_id / "index.html"
    original = page.read_bytes()
    portal.upsert_messages(chat, [{"message_id": "m2", "sender_id": "a",
                                  "text": "Second version", "sent_at": "2026-09-26"}])

    def fail_render(_data):
        raise RuntimeError("render interrupted")

    monkeypatch.setattr("scripts.export_portal.render_portal", fail_render)
    try:
        export_group(db, tmp_path / "media", chat, output)
    except RuntimeError as exc:
        assert str(exc) == "render interrupted"
    else:
        raise AssertionError("Expected an interrupted export")
    assert page.read_bytes() == original
    assert {p.name for p in output.iterdir()} == {".vercelignore", "index.html", public_id, "vercel.json"}


def test_failed_full_refresh_preserves_previous_complete_site(tmp_path, monkeypatch):
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    chat = "iMessage;+;group"
    public_id = portal.ensure_group(chat)
    output = tmp_path / "portal_build"
    export_portal(db, tmp_path / "media", {chat}, output)
    original = (output / public_id / "index.html").read_bytes()

    def fail_render(_data):
        raise RuntimeError("render interrupted")

    monkeypatch.setattr("scripts.export_portal.render_portal", fail_render)
    try:
        export_portal(db, tmp_path / "media", {chat}, output)
    except RuntimeError as exc:
        assert str(exc) == "render interrupted"
    else:
        raise AssertionError("Expected an interrupted export")
    assert (output / public_id / "index.html").read_bytes() == original
    assert {p.name for p in tmp_path.iterdir() if p.is_dir()} == {"portal_build"}


def test_pending_groups_export_together_with_tracked_plans(tmp_path):
    from datetime import datetime, timezone
    from app.models import PlanFacts
    db = tmp_path / "rally.sqlite3"
    store = Store(db)
    portal = PortalStore(db)
    ready = "iMessage;+;ready"
    waiting = "iMessage;+;waiting"
    ready_id = portal.ensure_group(ready)
    waiting_id = portal.ensure_group(waiting)
    portal.set_import_state(ready, cursor="1", status="pending")
    portal.set_import_state(waiting, cursor="1", status="running")
    portal.upsert_messages(waiting, [{"message_id": "w", "sender_id": "a",
                                     "text": "still importing", "sent_at": "2026-09-25"}])
    store.save_plan(ready, PlanFacts(activity="dinner", location="taj, atlanta",
                                     preferred_cuisines=["indian"]),
                    datetime(2026, 9, 26, tzinfo=timezone.utc))
    output = tmp_path / "portal_build"
    summary = export_portal(db, tmp_path / "media", {ready, waiting}, output)
    assert summary["groups"] == 2
    ready_html = (output / ready_id / "index.html").read_text(encoding="utf-8")
    waiting_html = (output / waiting_id / "index.html").read_text(encoding="utf-8")
    assert "History import pending" in ready_html
    assert "Importing history" in waiting_html
    assert "still importing" in waiting_html
    lowered = ready_html.lower()
    assert "taj" in lowered and "atlanta" in lowered and "indian" in lowered
    assert "Rally plans" in ready_html and "Group analytics" in ready_html


def test_direct_chat_is_omitted_without_blocking_the_group(tmp_path):
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    group = "iMessage;+;group"
    direct = "iMessage;-;private-person"
    group_id = portal.ensure_group(group)
    direct_id = portal.ensure_group(direct)
    portal.upsert_messages(group, [{"message_id": "g", "sender_id": "a",
                                   "text": "group hello", "sent_at": "2026-09-25"}])
    portal.upsert_messages(direct, [{"message_id": "d", "sender_id": "a",
                                    "text": "direct only secret", "sent_at": "2026-09-25"}])
    output = tmp_path / "portal_build"
    summary = export_portal(db, tmp_path / "media", {group, direct}, output)
    assert summary["groups"] == 1
    assert not (output / direct_id).exists()
    built = "\n".join(path.read_text(encoding="utf-8")
                      for path in output.rglob("*") if path.is_file())
    assert "group hello" in built
    assert "direct only secret" not in built
    assert "History import pending" in (output / group_id / "index.html").read_text(encoding="utf-8")


def test_group_export_respects_hidden_sections(tmp_path):
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    chat = "iMessage;+;group"
    public_id = portal.ensure_group(chat)
    portal.upsert_messages(chat, [{"message_id": "m", "sender_id": "a",
                                  "text": "Hidden dinner secret", "sent_at": "2026-09-25"}])
    portal.update_settings(chat, sections={"history": False, "plans": False})
    output = tmp_path / "portal_build"
    export_group(db, tmp_path / "media", chat, output)
    html = (output / public_id / "index.html").read_text(encoding="utf-8")
    assert "Hidden dinner secret" not in html
    assert "History is hidden" in html
    assert "Plans are hidden" in html
    assert not (output / public_id / "history-index.json").exists()


def test_group_export_removes_private_page_and_keeps_other_groups(tmp_path):
    from datetime import datetime, timezone
    from app.relationships.store import RelationshipStore
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    private_chat = "iMessage;+;private-group"
    other = "iMessage;+;other"
    private_id = portal.ensure_group(private_chat)
    other_id = portal.ensure_group(other)
    portal.upsert_messages(private_chat, [{"message_id": "p", "sender_id": "a",
                                          "text": "old private message", "sent_at": "2026-09-25"}])
    portal.upsert_messages(other, [{"message_id": "o", "sender_id": "a",
                                   "text": "other group stays", "sent_at": "2026-09-25"}])
    output = tmp_path / "portal_build"
    export_portal(db, tmp_path / "media", {private_chat, other}, output)
    assert (output / private_id / "index.html").exists()
    relationship = RelationshipStore(db)
    relationship.configure("owner", "iMessage;-;owner", "UTC")
    relationship.upsert("owner", "Secret Friend", "message", 7, datetime.now(timezone.utc))
    relationship.add_source("owner", private_chat, "Secret Friend")
    summary = export_group(db, tmp_path / "media", private_chat, output)
    assert summary == {"groups": 0, "pages": 0, "media": 0}
    assert not (output / private_id).exists()
    other_html = (output / other_id / "index.html").read_text(encoding="utf-8")
    assert "other group stays" in other_html
    built = "\n".join(path.read_text(encoding="utf-8")
                      for path in output.rglob("*") if path.is_file())
    assert "old private message" not in built


def test_failed_group_export_does_not_create_partial_site(tmp_path, monkeypatch):
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    chat = "iMessage;+;group"
    portal.ensure_group(chat)
    portal.upsert_messages(chat, [{"message_id": "m", "sender_id": "a",
                                  "text": "hello", "sent_at": "2026-09-25"}])

    def fail_render(_data):
        raise RuntimeError("render interrupted")

    monkeypatch.setattr("scripts.export_portal.render_portal", fail_render)
    try:
        export_group(db, tmp_path / "media", chat, tmp_path / "portal_build")
    except RuntimeError as exc:
        assert str(exc) == "render interrupted"
    else:
        raise AssertionError("Expected an interrupted export")
    assert not (tmp_path / "portal_build").exists()


def test_abandoned_backup_is_restored_before_the_next_export(tmp_path):
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    chat = "iMessage;+;group"
    public_id = portal.ensure_group(chat)
    portal.upsert_messages(chat, [{"message_id": "m1", "sender_id": "a",
                                  "text": "First version", "sent_at": "2026-09-25"}])
    output = tmp_path / "portal_build"
    export_portal(db, tmp_path / "media", {chat}, output)
    backup = tmp_path / ".portal_build.backup-dead"
    output.rename(backup)
    portal.upsert_messages(chat, [{"message_id": "m2", "sender_id": "a",
                                  "text": "Second version", "sent_at": "2026-09-26"}])
    export_portal(db, tmp_path / "media", {chat}, output)
    html = (output / public_id / "index.html").read_text(encoding="utf-8")
    assert "Second version" in html
    assert list(tmp_path.glob(".portal_build.backup-*")) == []
    assert {path.name for path in tmp_path.iterdir() if path.is_dir()} == {"portal_build"}


def test_concurrent_exports_do_not_overlap_or_drop_pages(tmp_path, monkeypatch):
    import threading
    import time
    db = tmp_path / "rally.sqlite3"
    Store(db)
    portal = PortalStore(db)
    first = "iMessage;+;one"
    second = "iMessage;+;two"
    first_id = portal.ensure_group(first)
    second_id = portal.ensure_group(second)
    portal.upsert_messages(first, [{"message_id": "a", "sender_id": "a",
                                   "text": "first group", "sent_at": "2026-09-25"}])
    portal.upsert_messages(second, [{"message_id": "b", "sender_id": "b",
                                    "text": "second group", "sent_at": "2026-09-25"}])
    output = tmp_path / "portal_build"
    state = {"inside": 0, "max": 0}
    guard = threading.Lock()
    original = __import__("scripts.export_portal", fromlist=["render_portal"]).render_portal

    def wrapped(data):
        with guard:
            state["inside"] += 1
            state["max"] = max(state["max"], state["inside"])
        try:
            time.sleep(0.05)
            return original(data)
        finally:
            with guard:
                state["inside"] -= 1

    monkeypatch.setattr("scripts.export_portal.render_portal", wrapped)
    errors = []

    def run_full():
        try:
            export_portal(db, tmp_path / "media", {first, second}, output)
        except Exception as exc:
            errors.append(exc)

    def run_one():
        try:
            export_group(db, tmp_path / "media", second, output)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run_full), threading.Thread(target=run_one)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert state["max"] == 1
    assert "first group" in (output / first_id / "index.html").read_text(encoding="utf-8")
    assert "second group" in (output / second_id / "index.html").read_text(encoding="utf-8")
    assert {path.name for path in tmp_path.iterdir() if path.is_dir()} == {"portal_build"}
