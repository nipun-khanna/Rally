from app.group_admin_commands import admin_dashboard_reply
from app.message_text import add_rally_signature, remove_rally_signature
from app.models import ChatMessage
from datetime import datetime, timezone


PUBLIC_ID = "C3JgCmcFInfygNdeMdkM3RhbFfr8Kern"
DASHBOARD_URL = f"https://rallyplans.vercel.app/{PUBLIC_ID}"
GROUP = "any;+;chat536074477903103142"


class _Portal:
    def ensure_group(self, chat_id):
        return PUBLIC_ID


def test_add_rally_signature_preserves_mixed_case_public_id():
    outbound = add_rally_signature(f"here's the group page: {DASHBOARD_URL}")
    assert DASHBOARD_URL in outbound
    assert PUBLIC_ID in outbound
    assert PUBLIC_ID.lower() not in outbound.replace(PUBLIC_ID, "")


def test_add_rally_signature_keeps_url_case_in_the_middle_of_text():
    outbound = add_rally_signature(
        f"here's the group page: {DASHBOARD_URL} the admin desk stays on the Mac.")
    assert DASHBOARD_URL in outbound
    assert outbound.startswith("here's the group page: ")
    assert not outbound.lower().startswith("rally:")
    assert outbound.endswith("the admin desk stays on the Mac.")


def test_dashboard_reply_keeps_mixed_case_url_after_signature():
    reply = admin_dashboard_reply(
        ChatMessage("m1", GROUP, "nick", "Rally, send the dashboard",
                    datetime.now(timezone.utc)),
        _Portal(), "https://rallyplans.vercel.app")
    outbound = add_rally_signature(reply)
    assert DASHBOARD_URL in outbound
    assert PUBLIC_ID in outbound
    assert "group page" in outbound.lower()


def test_add_rally_signature_keeps_case_and_confirmation_codes():
    assert add_rally_signature("Dinner Friday at 8") == "Dinner Friday at 8"
    assert add_rally_signature("Rally: Dinner Friday") == "Dinner Friday"
    code = "A1B2C3"
    outbound = add_rally_signature(f"Rally: Reply approve {code} or cancel {code}.")
    assert outbound == f"Reply approve {code} or cancel {code}."
    assert code in outbound
    assert code.lower() not in outbound.replace(code, "")


def test_remove_rally_signature_strips_prefix():
    assert remove_rally_signature("Rally: Our group page") == "Our group page"
