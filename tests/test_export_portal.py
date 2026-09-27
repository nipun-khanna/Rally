import json
from pathlib import Path

from app.portal_store import PortalStore
from app.store import Store
from scripts.export_portal import export_portal


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
