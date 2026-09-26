import json
from pathlib import Path

from app.portal_store import PortalStore
from app.store import Store
from scripts.export_portal import export_portal


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
    assert summary == {"groups": 1, "pages": 2, "media": 1}
    first = (output / public_id / "index.html").read_text()
    second = (output / public_id / "history" / "2.html").read_text()
    assert f"/{public_id}/history/2.html" in first
    assert "Dinner next week" in second
    assert len(list((output / public_id / "media").iterdir())) == 1
    assert any(item["text"] == "Dinner next week" for item in json.loads(
        (output / public_id / "history-index.json").read_text()))
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
    html = (output / public_id / "index.html").read_text()
    assert f"/{public_id}/download/" in html
    assert f"/{public_id}/media/" not in html
    assert list((output / public_id / "download").iterdir())[0].suffix == ".bin"
    config = json.loads((output / "vercel.json").read_text())
    assert any(rule["source"] == "/:group/download/:file" for rule in config["headers"])
