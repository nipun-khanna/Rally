from app.portal_store import PortalStore


def test_hosted_group_public_id_prefers_c3jg_prefix(tmp_path):
    store = PortalStore(tmp_path / "db.sqlite")
    store.ensure_group("any;-;+15555550100")
    group = store.ensure_group("any;+;chat-one")
    with store._db() as db:
        db.execute("UPDATE portal_groups SET public_id=? WHERE chat_id=?",
                   ("C3JgTestHostedArchive000000000001", "any;+;chat-one"))
    assert store.hosted_group_public_id() == "C3JgTestHostedArchive000000000001"
    assert store.hosted_group_public_id("Nope") is None
    assert group != "C3JgTestHostedArchive000000000001"


def test_public_id_is_opaque_and_rotatable(tmp_path):
    store = PortalStore(tmp_path / "db.sqlite")
    first = store.ensure_group("iMessage;+;real-chat-guid")
    assert first == store.ensure_group("iMessage;+;real-chat-guid")
    assert "real-chat-guid" not in first
    assert store.get_group(first)["chat_id"] == "iMessage;+;real-chat-guid"
    second = store.rotate_group("iMessage;+;real-chat-guid")
    assert second != first
    assert store.get_group(first) is None
    assert store.get_group(second)["chat_id"] == "iMessage;+;real-chat-guid"


def test_settings_archive_attachments_and_analytics(tmp_path):
    store = PortalStore(tmp_path / "db.sqlite")
    chat = "chat"
    settings = store.update_settings(chat, title="Weekend", sections={"media": False})
    assert settings["title"] == "Weekend"
    assert settings["sections"]["media"] is False
    assert settings["sections"]["history"] is True
    store.set_member(chat, "a", "Akshit")
    messages = [
        {"message_id": "m1", "sender_id": "a", "text": "hello",
         "sent_at": "2020-01-01T12:00:00+00:00", "attachments": [
             {"attachment_id": "img1", "mime_type": "image/jpeg", "filename": "a.jpg",
              "size_bytes": 123, "local_path": "chat/img1", "status": "ready"}]},
        {"message_id": "m2", "sender_id": "b", "text": "hi",
         "sent_at": "2020-01-02T12:00:00+00:00"},
    ]
    assert store.upsert_messages(chat, messages) == 2
    assert store.upsert_messages(chat, messages) == 0
    assert [m["message_id"] for m in store.list_messages(chat)] == ["m2", "m1"]
    assert store.list_messages(chat, before="2020-01-02T12:00:00+00:00")[0]["message_id"] == "m1"
    assert store.get_attachment(chat, "img1")["local_path"] == "chat/img1"
    assert store.analytics(chat) == {
        "message_count": 2, "attachment_count": 1,
        "by_member": [
            {"sender_id": "a", "display_name": "Akshit", "message_count": 1},
            {"sender_id": "b", "display_name": "b", "message_count": 1},
        ],
        "laughs_received": [],
        "reactions_received": [],
        "busiest_day": {"day": "2020-01-02", "message_count": 1},
    }
    store.set_import_state(chat, cursor="2", status="running")
    assert store.import_state(chat)["imported_count"] == 2
    assert store.import_state(chat)["cursor"] == "2"
    store.set_import_state(chat, cursor=None, status="complete")
    assert store.import_state(chat)["status"] == "complete"


def test_archive_is_scoped_to_chat(tmp_path):
    store = PortalStore(tmp_path / "db.sqlite")
    message = {"message_id": "same", "sender_id": "a", "text": "one", "sent_at": "2020-01-01"}
    assert store.upsert_messages("one", [message]) == 1
    assert store.upsert_messages("two", [{**message, "text": "two"}]) == 1
    assert store.list_messages("one")[0]["text"] == "one"
    assert store.list_messages("two")[0]["text"] == "two"


def test_history_cursor_keeps_same_timestamp_messages_and_hides_deleted(tmp_path):
    store = PortalStore(tmp_path / "db.sqlite")
    chat = "chat"
    store.upsert_messages(chat, [
        {"message_id": f"m{i}", "sender_id": "a", "text": f"text {i}",
         "sent_at": "2020-01-01T12:00:00+00:00"} for i in range(4)
    ])
    newest = store.list_messages(chat, limit=2)
    assert [m["message_id"] for m in newest] == ["m3", "m2"]
    older = store.list_messages(chat, before=newest[-1]["sent_at"] + "|" + newest[-1]["message_id"], limit=2)
    assert [m["message_id"] for m in older] == ["m1", "m0"]
    store.upsert_messages(chat, [{"message_id": "m1", "sender_id": "a", "text": "text 1",
                                  "sent_at": "2020-01-01T12:00:00+00:00", "is_deleted": True}])
    assert "m1" not in [m["message_id"] for m in store.list_messages(chat)]
