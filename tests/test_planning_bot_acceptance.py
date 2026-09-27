"""Planning acceptance checks with synthetic chats; never send live iMessages."""

from datetime import datetime, timedelta, timezone

import pytest

from app.agent import AgentDecision, GroupConversationDecision
from app.group_memory import GroupMemoryStore
from app.group_turns import GroupTurnStore
from app.models import ChatMessage, PlanFacts
from app.message_text import add_rally_signature
from app.orchestrator import RallyService
from app.policy import explicitly_addresses_rally
from app.portal_commands import portal_reply
from app.portal_store import PortalStore
from app.store import Store


NOW = datetime(2026, 9, 26, 21, tzinfo=timezone.utc)
CHAT_A = "iMessage;+;acceptance-a"
CHAT_B = "iMessage;+;acceptance-b"


class StubAgent:
    """Only provider responses are stubbed; routing/storage remain production code."""

    def __init__(self):
        self.contexts = []
        self.reply = "Choose ramen: it fits the group's preference."
        self.relevant = True

    def extract(self, messages, previous):
        return previous or PlanFacts()

    def decide_conversation(self, request, facts, messages, *, memory_context="",
                            followup=False, proposal=None):
        self.contexts.append((facts, list(messages), memory_context))
        return GroupConversationDecision(
            relevant=self.relevant, safety="ok",
            message=self.reply if self.relevant else None,
            reaction="like" if self.relevant else None,
            memory_candidates=[],
        )

    def decide(self, facts, messages, venues):
        return AgentDecision(action="PROPOSE", reason="Choose a venue",
                             tool="search_places", confidence=0.9)


def make_service(tmp_path, *, history_fn=None):
    db = tmp_path / "acceptance.sqlite3"
    agent, sent, searched = StubAgent(), [], []
    service = RallyService(
        Store(db), agent, lambda facts: searched.append(facts) or [],
        lambda chat, text: sent.append((chat, text)),
        allowed_chat_ids={CHAT_A, CHAT_B}, group_memory=GroupMemoryStore(db),
        group_turns=GroupTurnStore(db), history_fn=history_fn,
    )
    return service, agent, sent, searched


def message(identifier, text, *, chat=CHAT_A, seconds=0, rally=False):
    return ChatMessage(identifier, chat, "Rally" if rally else "synthetic-member",
                       text, NOW + timedelta(seconds=seconds), rally)


@pytest.mark.parametrize("text", ["Rally, help us decide", "Hey Rally, dinner?",
                                 "@Rally help", "Ask Rally where we should eat"])
def test_explicit_invocations_are_recognized(text):
    assert explicitly_addresses_rally(text)


@pytest.mark.parametrize("text", ["We should ask Rally later", "That rally was fun"])
def test_incidental_mentions_do_not_invoke(text):
    assert not explicitly_addresses_rally(text)


def test_ask_rally_invocation_produces_a_reply(tmp_path):
    service, agent, sent, _ = make_service(tmp_path)
    service.receive(message("ask", "Ask Rally where we should eat"))
    assert len(sent) == 1
    assert len(agent.contexts) == 1


def test_recap_preserves_addressed_prior_human_facts_without_saved_plan(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    service.store.add_message(message(
        "prior", "Hey Rally, dinner Friday at 8 near Midtown for four; ramen or tacos."))
    service.receive(message("recap", "Rally, recap the plan", seconds=30))
    body = sent[-1][1].lower()
    for known in ("friday", "midtown", "four", "ramen", "tacos"):
        assert known in body, f"recap lost known detail: {known}"


def test_recap_preserves_unaddressed_prior_human_facts_without_saved_plan(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    service.store.add_message(message(
        "prior", "Dinner Friday at 8 near Midtown for four; ramen or tacos."))
    service.receive(message("recap", "Rally, recap the plan", seconds=30))
    assert all(known in sent[-1][1].lower() for known in ("friday", "midtown", "ramen"))


def test_no_answer_followup_stays_silent(tmp_path):
    service, agent, sent, _ = make_service(tmp_path)
    service.receive(message("direct", "Rally, help us choose dinner"))
    agent.relevant = False
    before = len(sent)
    service.receive(message("unrelated", "Did anyone see the game?", seconds=30))
    assert len(sent) == before


def test_no_answer_marker_is_not_sent_as_a_reply(tmp_path):
    service, agent, sent, _ = make_service(tmp_path)
    agent.reply = "NO ANSWER"
    service.receive(message("direct", "Rally, help us choose dinner"))
    assert sent == []


@pytest.mark.parametrize("activity", ["dinner", "museum visit"])
def test_venue_search_only_runs_for_restaurant_plans(tmp_path, activity):
    service, _, _, searched = make_service(tmp_path)
    service.store.save_plan(CHAT_A, PlanFacts(
        activity=activity, goal=activity, participants=["alice", "bob"],
        date="2099-10-02", time="20:00", location="Midtown",
        blockers=["venue missing"], confidence=0.9,
    ), NOW)
    service.evaluate(CHAT_A, NOW + timedelta(minutes=31))
    assert bool(searched) is (activity == "dinner")


def test_plan_and_memory_are_isolated_and_survive_restart(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    service.store.save_plan(CHAT_A, PlanFacts(activity="dinner", location="Midtown"), NOW)
    service.store.save_plan(CHAT_B, PlanFacts(activity="museum visit", location="Uptown"), NOW)
    service.group_memory.upsert_fact(CHAT_A, "food.preference", "The group prefers ramen", "a", NOW)
    service.group_memory.upsert_fact(CHAT_B, "food.preference", "The group prefers tacos", "b", NOW)
    reopened, agent, _, _ = make_service(tmp_path)
    assert reopened.store.get_plan(CHAT_A).facts.location == "Midtown"
    assert reopened.store.get_plan(CHAT_B).facts.location == "Uptown"
    reopened.receive(message("context", "Rally, help us choose a cuisine"))
    facts, _, memory = agent.contexts[-1]
    assert facts.location == "Midtown"
    assert "ramen" in memory and "tacos" not in memory


def test_reply_context_contains_humans_rally_memory_and_plan(tmp_path):
    service, agent, _, _ = make_service(tmp_path)
    service.store.add_message(message("human", "Dinner Friday in Midtown"))
    service.store.add_message(message("bot", "Rally: ramen would work", seconds=1, rally=True))
    service.store.save_plan(CHAT_A, PlanFacts(activity="dinner", location="Midtown"), NOW)
    service.group_memory.upsert_fact(CHAT_A, "food.preference", "The group prefers ramen", "a", NOW)
    service.receive(message("context", "Rally, what cuisine would work?", seconds=30))
    facts, messages, memory = agent.contexts[-1]
    assert facts.location == "Midtown"
    assert any(item.message_id == "human" for item in messages)
    assert any(item.message_id == "bot" and item.is_from_rally for item in messages)
    assert "ramen" in memory


def test_first_invocation_hydrates_preexisting_chat_history(tmp_path):
    prior = message("history", "Dinner Friday at 8 in Midtown")
    service, agent, _, _ = make_service(tmp_path, history_fn=lambda chat, limit: [prior])
    service.receive(message("context", "Rally, what cuisine would work?", seconds=30))
    assert any(item.message_id == "history" for item in agent.contexts[-1][1])


def test_disallowed_chat_cannot_ingest_or_reply(tmp_path):
    service, agent, sent, _ = make_service(tmp_path)
    assert not service.receive(message("outside", "Rally, help", chat="iMessage;+;outside"))
    assert sent == [] and agent.contexts == []
    assert service.store.recent_messages("iMessage;+;outside") == []


@pytest.mark.parametrize("body", ["Dinner at 8", "Rally: Existing recap",
                                 "Our page: https://rallyplans.vercel.app/CaseSensitiveId"])
def test_production_transport_identity_preserves_public_urls(body):
    outgoing = add_rally_signature(body)
    assert outgoing.startswith("Rally: ")
    assert outgoing.count("Rally:") == 1
    if "https://" in body:
        assert "https://rallyplans.vercel.app/CaseSensitiveId" in outgoing


def test_public_archive_is_current_chat_and_has_no_admin_credentials(tmp_path):
    portal = PortalStore(tmp_path / "portal.sqlite3")
    first, other = portal.ensure_group(CHAT_A), portal.ensure_group(CHAT_B)
    reply = portal_reply(message("archive", "Rally, send our page link"), portal,
                         "https://rallyplans.vercel.app")
    assert f"https://rallyplans.vercel.app/{first}" in reply
    assert other not in reply
    assert CHAT_A not in reply and CHAT_B not in reply
    assert "token=" not in reply and "admin/groups" not in reply


def test_forget_removes_exact_fact_from_subsequent_context(tmp_path):
    service, agent, _, _ = make_service(tmp_path)
    service.group_memory.upsert_fact(CHAT_A, "jake.diet", "Jake is vegetarian", "a", NOW)
    service.group_memory.upsert_fact(CHAT_A, "group.area", "The group prefers Midtown", "b", NOW)
    service.receive(message("forget", "Rally, forget jake.diet"))
    service.receive(message("next", "Rally, what cuisine would work?", seconds=30))
    memory = agent.contexts[-1][2]
    assert "vegetarian" not in memory
    assert "Midtown" in memory


def test_p0_ordinary_planning_then_ask_rally_grounded_recap(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    service.receive(message("planning", "Dinner Saturday at 8 near Midtown for four. Jake is vegetarian."))
    assert sent == [], "ordinary planning must stay silent"
    service.receive(message("recap", "Ask Rally what have we decided?", seconds=30))
    assert len(sent) == 1, "Ask Rally must invoke a grounded recap"
    assert all(known in sent[-1][1].lower() for known in ("saturday", "midtown", "vegetarian"))


def test_newer_saturday_override_does_not_recap_friday_as_current(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    service.store.add_message(message("old", "Dinner Friday at 8 near Midtown."))
    service.store.add_message(message("new", "Actually Saturday instead of Friday; Friday is cancelled.", seconds=10))
    service.receive(message("recap", "Rally, recap the current plan", seconds=30))
    body = sent[-1][1].lower()
    assert "saturday" in body
    assert "dinner friday at 8" not in body, "superseded Friday is still presented as current"


def test_five_member_burst_is_not_five_replies(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    for index in range(5):
        inbound = ChatMessage(f"burst-{index}", CHAT_A, f"member-{index}",
                              "Rally, help us choose dinner", NOW + timedelta(seconds=index))
        service.receive(inbound)
    assert len(sent) == 1


def test_restaurant_ask_names_a_place_from_thread_constraints(tmp_path):
    service, agent, sent, searched = make_service(tmp_path)

    def search(facts):
        searched.append(facts)
        from app.places import Venue
        return [Venue("steak-1", "Blood & Bone Steakhouse", "1 Meat St, Midtown",
                      40.75, -73.98, ("steak",)),
                Venue("veg-1", "Green Table", "88 Midtown Ave",
                      40.75, -73.98, ("vegetarian", "vegan"))]

    service.search_fn = search
    service.store.add_message(message(
        "planted", "Dinner Saturday at 8 near Midtown. Jake is vegetarian."))
    service.receive(message("ask", "Ask Rally where should we eat?", seconds=30))
    assert sent and agent.contexts == []
    body = sent[-1][1].lower()
    assert "green table" in body
    assert "midtown" in body or "vegetarian" in body
    assert "blood" not in body
    assert "not a booking" in body


def test_recap_does_not_invent_a_restaurant(tmp_path):
    service, _, sent, searched = make_service(tmp_path)
    service.store.add_message(message(
        "planted", "Dinner Saturday at 8 near Midtown. Jake is vegetarian."))
    service.receive(message("recap", "Ask Rally what have we decided?", seconds=30))
    body = sent[-1][1].lower()
    assert "saturday" in body and "midtown" in body and "vegetarian" in body
    assert "green table" not in body
    assert "coward" not in body
    assert "won't fake a damn restaurant" not in body
    assert "locked-in chaos" not in body
    assert searched == []


def test_duplicate_invocation_does_not_send_twice(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    inbound = message("duplicate", "Ask Rally where should we eat?")
    assert service.receive(inbound)
    assert not service.receive(inbound)
    assert len(sent) == 1, "one addressed invocation must produce exactly one reply"


def test_second_invoke_still_hydrates_thread_history(tmp_path):
    fetched = []
    prior = message("history", "eat out saturday indian near midtown")

    def history(chat_id, limit=50):
        fetched.append((chat_id, limit))
        return [prior]

    service, _, sent, _ = make_service(tmp_path, history_fn=history)
    service.receive(message("first", "Rally, recap the plan", seconds=0))
    assert fetched == [(CHAT_A, 50)]
    fetched.clear()
    service.receive(message("second", "Rally, recap again", seconds=30))
    assert fetched == [(CHAT_A, 50)]
    body = sent[-1][1].lower()
    assert "saturday" in body and "indian" in body
    assert "coward" not in body
    assert "won't fake a damn restaurant" not in body


def test_unfinished_plan_stall_sends_one_unsolicited_revival(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    service.store.save_plan(CHAT_A, PlanFacts(
        activity="eat out", date="2026-09-26", location="Midtown",
        preferred_cuisines=["indian"]), NOW - timedelta(minutes=20))
    before = len(sent)
    service.receive(message("stall", "we still need to pick a spot", seconds=0))
    assert len(sent) == before + 1
    body = sent[-1][1].lower()
    assert "coward" not in body
    assert "won't fake a damn restaurant" not in body
    assert any(token in body for token in ("table", "indian", "midtown", "spot"))
    service.receive(message("again", "pick a place already", seconds=20))
    assert len(sent) == before + 1


def test_idle_chatter_without_a_stall_does_not_nudge(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    service.store.save_plan(CHAT_A, PlanFacts(
        activity="eat out", date="2026-09-26", location="Midtown",
        preferred_cuisines=["indian"]), NOW - timedelta(minutes=20))
    service.receive(message("idle", "lol", seconds=0))
    assert sent == []


def test_active_turn_answers_followup_without_saying_rally(tmp_path):
    service, _, sent, _ = make_service(tmp_path)
    service.receive(message("invoke", "Rally, recap?"))
    before = len(sent)
    service.receive(message("songs", "name me 5 weekend songs", seconds=30))
    assert len(sent) == before + 1
    assert "blinding lights" in sent[-1][1].lower()
    service.receive(message("late", "name me 5 weekend songs", seconds=6 * 60))
    assert len(sent) == before + 1
