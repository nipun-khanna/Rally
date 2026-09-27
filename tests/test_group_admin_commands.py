from types import SimpleNamespace

from app.group_admin_commands import admin_dashboard_reply
from app.models import ChatMessage
from app.portal_commands import portal_reply
from datetime import datetime, timezone


NOW = datetime(2026, 9, 26, 21, 40, tzinfo=timezone.utc)
GROUP = "any;+;chat536074477903103142"
PUBLIC = "portalPublicIdExample"
OWNER = "local-imessage-account"
APP = "https://rallyplans.vercel.app"


class Portal:
    def __init__(self, public_id=PUBLIC):
        self.public_id = public_id
        self.seen = []

    def ensure_group(self, chat_id):
        self.seen.append(chat_id)
        return self.public_id


def message(text, *, sender=OWNER, chat=GROUP):
    return ChatMessage("m1", chat, sender, text, NOW)


def handle(text, *, sender=OWNER, app_url=APP, portal=None):
    portal = portal or Portal()
    return admin_dashboard_reply(message(text, sender=sender), portal, app_url), portal


def test_page_link_command_still_returns_public_archive_not_admin_desk():
    class Store:
        def ensure_group(self, chat_id):
            return "public-id"
        def update_settings(self, *args, **kwargs):
            raise AssertionError("page link must not change settings")
        def rotate_group(self, chat_id):
            raise AssertionError("page link must not rotate")
    reply = portal_reply(SimpleNamespace(text="Hey Rally, send our page link", chat_id=GROUP),
                         Store(), APP)
    assert f"{APP}/public-id" in reply
    assert "group page" in reply.lower(), reply
    assert admin_dashboard_reply(message("Hey Rally, send our page link"), Portal(), APP) is None


def test_dashboard_phrases_send_hosted_archive_not_local_admin_or_chat_guid():
    for text in ("Rally, send the dashboard", "Hey Rally, send me the dashboard",
                 "Rally dashboard"):
        reply, portal = handle(text)
        assert f"{APP}/{PUBLIC}" in reply, text
        assert "group page" in reply.lower(), reply
        assert portal.seen == [GROUP]
        assert "127.0.0.1" not in reply
        assert "admin/groups" not in reply
        assert "token=" not in reply
        assert GROUP not in reply
        assert "chat536074477903103142" not in reply


def test_admin_dashboard_mentions_mac_desk_but_link_is_vercel():
    reply, _ = handle("Rally, admin dashboard")
    assert f"{APP}/{PUBLIC}" in reply
    assert "group page" in reply.lower(), reply
    assert "Mac" in reply
    assert "token" in reply.lower()
    assert "127.0.0.1" not in reply
    assert "token=" not in reply
    assert GROUP not in reply


def test_members_get_the_same_hosted_link_without_a_token():
    reply, _ = handle("Rally, send the dashboard", sender="member")
    assert f"{APP}/{PUBLIC}" in reply
    assert "group page" in reply.lower(), reply
    assert "token=" not in reply


def test_missing_app_url_does_not_text_localhost():
    reply, portal = handle("Rally, send the dashboard", app_url="")
    assert reply is not None
    assert reply.strip() != "", reply
    assert "page" in reply.lower()
    assert "127.0.0.1" not in reply
    assert "http" not in reply.lower()
    assert "token=" not in reply
    assert portal.seen == []
