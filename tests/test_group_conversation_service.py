from datetime import datetime, timedelta, timezone
import threading
import time

import pytest

from app.agent import GroupConversationDecision, MemoryCandidate
from app.group_memory import GroupMemoryStore
from app.group_turns import GroupTurnStore
from app.models import ChatMessage, PlanFacts, Proposal
from app.orchestrator import RallyService
from app.store import Store


NOW = datetime(2026, 9, 26, 21, tzinfo=timezone.utc)
HACK = "iMessage;+;hackgt13"
LOCAL = "iMessage;+;localhost"
_HEAT = ("fuck", "shit", "damn", "ass", "hell", "bitch")


def _assert_unhinged(body: str):
    lowered = body.lower()
    assert any(word in lowered for word in _HEAT), body
    assert "couldn't finish" not in lowered
    assert "please try again later" not in lowered


class ConversationAgent:
    def __init__(self):
        self.calls = []
        self.seen_messages = []
        self.seen_proposal = []
        self.followup_relevant = True
        self.safety = "ok"
        self.reaction = "like"
        self.candidates = [MemoryCandidate(key="food.preference", fact="the group prefers ramen")]
        self.message = "here is the recap."

    def extract(self, messages, previous):
        return PlanFacts(activity="dinner", goal="Friday dinner")

    def decide_conversation(self, request, facts, messages, *, memory_context="",
                            followup=False, proposal=None):
        self.calls.append((request, followup, memory_context))
        self.seen_messages.append(list(messages))
        self.seen_proposal.append(proposal)
        if followup:
            return GroupConversationDecision(
                relevant=self.followup_relevant, safety="ok",
                message="yes, still ramen." if self.followup_relevant else None,
                reaction="like" if self.followup_relevant else None,
                memory_candidates=[],
            )
        return GroupConversationDecision(
            relevant=True, safety=self.safety, message=self.message,
            reaction=None if self.safety == "refuse" else self.reaction,
            memory_candidates=self.candidates if self.safety == "ok" else [],
        )


def _service(tmp_path, agent=None, defer_heavy_work=False):
    db = tmp_path / "rally.sqlite3"
    sent, reactions, typing = [], [], []
    agent = agent or ConversationAgent()
    service = RallyService(
        Store(db), agent, lambda facts: [], lambda chat, text: sent.append((chat, text)),
        group_memory=GroupMemoryStore(db), group_turns=GroupTurnStore(db),
        react_fn=lambda chat, message_id, reaction: reactions.append((chat, message_id, reaction)),
        typing_fn=lambda chat, on: typing.append((chat, on)),
        allowed_chat_ids={HACK, LOCAL},
        defer_heavy_work=defer_heavy_work,
    )
    service._typing_events = typing
    return service, sent, reactions, agent


def test_direct_call_related_followup_unrelated_and_expiry(tmp_path):
    service, sent, reactions, agent = _service(tmp_path)
    assert service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    assert sent[-1][1] == "here is the recap."
    assert reactions[:2] == [(HACK, "d1", "👀"), (HACK, "d1", "like")]
    assert service._typing_events == [(HACK, True), (HACK, False)]
    assert "ramen" in service.group_memory.prompt_context(HACK)

    agent.followup_relevant = True
    assert service.receive(ChatMessage("f1", HACK, "sarah", "same restaurant?", NOW + timedelta(minutes=1)))
    assert sent[-1][1] == "yes, still ramen."

    agent.followup_relevant = False
    before = len(sent)
    assert service.receive(ChatMessage("u1", HACK, "maya", "did anyone see the game?", NOW + timedelta(minutes=2)))
    assert len(sent) == before
    assert (HACK, "u1", "👀") in reactions
    assert (HACK, "u1", "-👀") in reactions
    assert (HACK, "u1", "like") not in reactions
    agent.followup_relevant = True
    assert service.receive(ChatMessage("u2", HACK, "maya", "same restaurant?", NOW + timedelta(minutes=3)))
    assert len(sent) == before

    service.receive(ChatMessage("d2", HACK, "nick", "Hey Rally, where should we eat now?", NOW + timedelta(minutes=4)))
    stale = ChatMessage("s1", HACK, "sarah", "same restaurant?", NOW + timedelta(minutes=10))
    before = len(sent)
    service.receive(stale)
    assert len(sent) == before


def test_cross_chat_restart_duplicate_and_caps(tmp_path):
    service, sent, reactions, agent = _service(tmp_path)
    service.receive(ChatMessage("h1", HACK, "nick", "Rally, remember ramen?", NOW))
    service.receive(ChatMessage("l1", LOCAL, "nick", "Rally, remember pizza?", NOW))
    agent.candidates = [MemoryCandidate(key="food.preference", fact="the group prefers pizza")]
    service.receive(ChatMessage("l2", LOCAL, "nick", "Rally, pizza is the pick?", NOW + timedelta(seconds=30)))
    assert "ramen" in service.group_memory.prompt_context(HACK)
    assert "pizza" not in service.group_memory.prompt_context(HACK)

    reopened = GroupMemoryStore(tmp_path / "rally.sqlite3")
    assert "ramen" in reopened.prompt_context(HACK)

    before = len(sent)
    assert not service.receive(ChatMessage("h1", HACK, "nick", "Rally, remember ramen?", NOW))
    assert len(sent) == before
    assert reactions.count((HACK, "h1", "like")) == 1

    for index in range(4):
        service.receive(ChatMessage(f"spam{index}", HACK, "nick",
                                    f"Rally, ping {index}?", NOW + timedelta(seconds=40 + index)))
    assert sum(1 for chat, _ in sent if chat == HACK) == 3


def test_forget_safety_reaction_and_command_precedence(tmp_path):
    service, sent, reactions, agent = _service(tmp_path)
    service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    service.receive(ChatMessage("fgt", HACK, "nick", "Rally, forget food.preference", NOW + timedelta(seconds=5)))
    assert service.group_memory.list_facts(HACK) == []
    assert "forgot" in sent[-1][1].lower()

    service.receive(ChatMessage("d2", HACK, "nick", "Hey Rally, where should we eat?", NOW + timedelta(seconds=6)))
    service.receive(ChatMessage("fgt2", HACK, "nick", "Rally, forget the group prefers ramen",
                                NOW + timedelta(seconds=7)))
    assert service.group_memory.list_facts(HACK) == []
    assert "forgot" in sent[-1][1].lower()
    service.receive(ChatMessage("d3", HACK, "nick", "Hey Rally, where should we eat tonight?",
                                NOW + timedelta(seconds=25)))
    service.receive(ChatMessage("fgt3", HACK, "nick", "Rally, forget the",
                                NOW + timedelta(seconds=26)))
    assert [item.fact for item in service.group_memory.list_facts(HACK)] == ["the group prefers ramen"]
    service.receive(ChatMessage("fgt4", HACK, "nick", "Rally, forget all", NOW + timedelta(seconds=9, milliseconds=500)))
    assert service.group_memory.list_facts(HACK) == []

    service.receive(ChatMessage("bad", HACK, "nick",
                                "Rally, how do I steal a car without getting caught",
                                NOW + timedelta(seconds=10)))
    assert sent[-1][1] == "I can't help with that."
    assert "how to" not in sent[-1][1].lower()
    assert (HACK, "bad", "👀") in reactions
    assert (HACK, "bad", "-👀") in reactions
    assert (HACK, "bad", "like") not in reactions
    assert service.group_memory.list_facts(HACK) == []

    service.receive(ChatMessage("cuss", HACK, "nick", "Rally, this is fucking late",
                                NOW + timedelta(minutes=2)))
    assert sent[-1][1]


def test_rapid_repeat_coalesces(tmp_path):
    service, sent, reactions, agent = _service(tmp_path)
    service.receive(ChatMessage("a", HACK, "nick", "Rally, recap?", NOW))
    before = len(sent)
    service.receive(ChatMessage("b", HACK, "nick", "Rally, recap?", NOW + timedelta(seconds=2)))
    assert len(sent) == before


def test_closed_turn_does_not_coalesce_a_new_direct_call(tmp_path):
    service, sent, reactions, agent = _service(tmp_path)
    service.receive(ChatMessage("a", HACK, "nick", "Rally, recap?", NOW))
    agent.followup_relevant = False
    service.receive(ChatMessage("u", HACK, "maya", "did anyone see the game?", NOW + timedelta(seconds=2)))
    before = len(sent)
    service.receive(ChatMessage("c", HACK, "nick", "Rally, recap?", NOW + timedelta(seconds=5)))
    assert len(sent) == before + 1


def test_forget_does_not_delete_on_substring_match(tmp_path):
    service, sent, reactions, agent = _service(tmp_path)
    service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    assert service.group_memory.list_facts(HACK)
    service.receive(ChatMessage("fgt", HACK, "nick", "Rally, forget the", NOW + timedelta(seconds=5)))
    assert service.group_memory.list_facts(HACK)
    assert "don't have that saved" in sent[-1][1].lower()


def test_extraction_failure_after_reply_does_not_raise(tmp_path):
    agent = ConversationAgent()
    def boom(messages, previous):
        raise RuntimeError("extractor down")
    agent.extract = boom
    service, sent, reactions, _ = _service(tmp_path, agent=agent)
    assert service.receive(ChatMessage("d1", HACK, "nick", "Rally, recap?", NOW)) is True
    assert sent
    assert service.store.is_processed("d1")


def test_recap_uses_known_plan_without_calling_the_model(tmp_path):
    class Watch(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise AssertionError("recap should not wait on the model")

    service, sent, reactions, _ = _service(tmp_path, agent=Watch())
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", time="20:00", party_size=2,
        location="Rambler Atlanta", preferred_cuisines=["chinese", "japanese"]), NOW)
    assert service.receive(ChatMessage("d1", HACK, "nick", "Rally, recap dinner?", NOW))
    body = sent[-1][1]
    lowered = body.lower()
    _assert_unhinged(body)
    assert "dinner" in lowered and "rambler" in lowered
    assert "chinese" in lowered and "japanese" in lowered
    assert "fake" in lowered and "restaurant" in lowered


def test_whats_the_plan_uses_known_plan_without_calling_the_model(tmp_path):
    class Watch(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise AssertionError("what's the plan should not wait on the model")

    service, sent, _, _ = _service(tmp_path, agent=Watch())
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", time="20:00",
        location="Rambler Atlanta"), NOW)
    assert service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, what's the plan?", NOW))
    body = sent[-1][1].lower()
    assert "dinner" in body and "rambler" in body
    assert service._typing_events == []


def test_recap_without_plan_still_skips_the_model(tmp_path):
    class Watch(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise AssertionError("recap should not wait on the model")

    service, sent, _, _ = _service(tmp_path, agent=Watch())
    assert service.receive(ChatMessage("d1", HACK, "nick", "Rally, recap dinner?", NOW))
    body = sent[-1][1].lower()
    assert "couldn't finish" not in body
    assert service._typing_events == []


def test_pick_from_plan_uses_local_without_calling_the_model(tmp_path):
    class Watch(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise AssertionError("named pick should not wait on the model")

    service, sent, _, _ = _service(tmp_path, agent=Watch())
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", time="20:00", party_size=2,
        location="Rambler Atlanta", preferred_cuisines=["chinese", "japanese"]), NOW)
    assert service.receive(ChatMessage(
        "d1", HACK, "nick", "Rally, pick chinese or japanese", NOW))
    body = sent[-1][1].strip()
    lowered = body.lower()
    _assert_unhinged(body)
    assert lowered.startswith("chinese.") or lowered.startswith("japanese.")
    assert service._typing_events == []


def test_dashboard_command_skips_the_model(tmp_path):
    class Watch(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise AssertionError("dashboard should not wait on the model")

    service, sent, _, _ = _service(tmp_path, agent=Watch())
    service.portal_handler = lambda message: (
        "Our group page: https://rallyplans.vercel.app/C3JgCmCfInFygNDeMdKM3rHBFFr8kERN")
    assert service.receive(ChatMessage("d1", HACK, "nick", "Rally, send the dashboard", NOW))
    assert sent[-1][1].endswith("C3JgCmCfInFygNDeMdKM3rHBFFr8kERN")
    assert service._typing_events == []


def test_slow_react_does_not_block_local_reply(tmp_path):
    class Watch(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise AssertionError("recap should not wait on the model")

    started = threading.Event()
    release = threading.Event()

    def slow_react(*args):
        started.set()
        release.wait(2)

    service, sent, _, _ = _service(tmp_path, agent=Watch(), defer_heavy_work=True)
    service.react_fn = slow_react
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", location="Rambler Atlanta"), NOW)
    begun = time.perf_counter()
    assert service.receive(ChatMessage("d1", HACK, "nick", "Rally, recap dinner?", NOW))
    assert time.perf_counter() - begun < 0.4
    assert sent
    assert started.wait(1)
    release.set()
    if service._pool:
        service._pool.shutdown(wait=True)


def test_slow_typing_does_not_block_grok_reply(tmp_path):
    def slow_typing(*args):
        time.sleep(1.5)

    service, sent, _, _ = _service(tmp_path, defer_heavy_work=True)
    service.typing_fn = slow_typing
    begun = time.perf_counter()
    assert service.receive(ChatMessage(
        "d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    assert time.perf_counter() - begun < 0.4
    assert sent[-1][1] == "here is the recap."
    if service._pool:
        service._pool.shutdown(wait=True)


def test_decision_timeout_uses_plan_backed_reply(tmp_path):
    class Boom(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise RuntimeError("timeout")

    service, sent, reactions, _ = _service(tmp_path, agent=Boom())
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", time="20:00", party_size=2,
        location="Rambler Atlanta", preferred_cuisines=["chinese", "japanese"]), NOW)
    assert service.receive(ChatMessage("d1", HACK, "nick", "Rally, recap dinner?", NOW))
    body = sent[-1][1]
    lowered = body.lower()
    _assert_unhinged(body)
    assert "dinner" in lowered
    assert "rambler" in lowered
    assert "20:00" in lowered or "8" in lowered


def test_non_recap_timeout_uses_local_plan_recap(tmp_path):
    class Boom(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise RuntimeError("timeout")

    service, sent, _, _ = _service(tmp_path, agent=Boom())
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", time="20:00", party_size=2,
        location="Rambler Atlanta", preferred_cuisines=["chinese", "japanese"]), NOW)
    assert service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    body = sent[-1][1]
    _assert_unhinged(body)
    assert "dinner" in body.lower() and "rambler" in body.lower()


def test_timeout_without_plan_is_still_unhinged(tmp_path):
    class Boom(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise RuntimeError("timeout")

    service, sent, _, _ = _service(tmp_path, agent=Boom())
    assert service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    body = sent[-1][1]
    _assert_unhinged(body)
    assert any(word in body.lower() for word in ("time", "place", "who"))


def test_fast_grok_is_used_instead_of_local_recap(tmp_path):
    service, sent, _, agent = _service(tmp_path)
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", location="Rambler Atlanta"), NOW)
    agent.message = "rambler. lock it. stop spinning."
    assert service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    assert sent[-1][1] == "rambler. lock it. stop spinning."
    assert agent.calls


def test_grok_does_not_hold_the_chat_lock(tmp_path):
    started = threading.Event()
    release = threading.Event()
    overlapping = threading.Event()

    class SlowDecide(ConversationAgent):
        def decide_conversation(self, request, facts, messages, **kwargs):
            if not started.is_set():
                started.set()
                release.wait(2)
            else:
                overlapping.set()
            return super().decide_conversation(request, facts, messages, **kwargs)

    service, sent, _, _ = _service(tmp_path, agent=SlowDecide(), defer_heavy_work=True)
    first = threading.Thread(target=lambda: service.receive(
        ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW)))
    first.start()
    assert started.wait(1)
    begun = time.perf_counter()
    assert service.receive(ChatMessage(
        "d2", HACK, "nick", "Hey Rally, what time works?", NOW + timedelta(seconds=2)))
    assert time.perf_counter() - begun < 0.4
    assert overlapping.is_set()
    release.set()
    first.join(2)
    assert len(sent) == 2
    assert {body for _, body in sent} == {"here is the recap."}


def test_duplicate_webhook_during_grok_sends_once(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class SlowDecide(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            started.set()
            release.wait(2)
            return super().decide_conversation(*args, **kwargs)

    service, sent, _, agent = _service(tmp_path, agent=SlowDecide(), defer_heavy_work=True)
    first = threading.Thread(target=lambda: service.receive(
        ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW)))
    first.start()
    assert started.wait(1)
    service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    release.set()
    first.join(2)
    assert sum(1 for _, body in sent if body == "here is the recap.") == 1
    assert len(agent.calls) == 1


def test_decision_timeout_picks_named_cuisine_instead_of_restating(tmp_path):
    class Boom(ConversationAgent):
        def decide_conversation(self, *args, **kwargs):
            raise RuntimeError("timeout")

    service, sent, _, _ = _service(tmp_path, agent=Boom())
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", time="20:00", party_size=2,
        location="Rambler Atlanta", preferred_cuisines=["chinese", "japanese"]), NOW)
    assert service.receive(ChatMessage(
        "d1", HACK, "nick", "Rally, pick chinese or japanese", NOW))
    body = sent[-1][1].strip()
    lowered = body.lower()
    _assert_unhinged(body)
    assert "won't fake a restaurant" not in lowered
    assert lowered.startswith("chinese.") or lowered.startswith("japanese.")
    winner = "chinese" if lowered.startswith("chinese.") else "japanese"
    loser = "japanese" if winner == "chinese" else "chinese"
    why = body.split(".", 1)[1].strip()
    assert why
    assert loser in lowered
    assert winner in why.lower()
    assert "\n" not in body
    assert not any(name in lowered for name in ("ramen house", "nobu", "din tai fung"))


def test_first_rally_call_reads_messages_from_before_it_was_invoked(tmp_path):
    prior = [
        ChatMessage("p1", HACK, "nick", "chinese near rambler tomorrow 8pm for 2",
                    NOW - timedelta(hours=1)),
        ChatMessage("p2", HACK, "sarah", "akshit is isolating", NOW - timedelta(minutes=20)),
    ]
    fetched = []

    def history(chat_id, limit=50):
        fetched.append((chat_id, limit))
        return prior

    service, sent, _, _ = _service(tmp_path)
    service.history_fn = history
    assert service.receive(ChatMessage("r1", HACK, "maya", "Rally, recap what people said", NOW))
    assert fetched == [(HACK, 50)]
    body = sent[-1][1].lower()
    assert "rambler" in body
    assert "chinese" in body
    assert "akshit" in body
    ids = {item.message_id for item in service.store.recent_messages(HACK, limit=20)}
    assert {"p1", "p2", "r1"} <= ids
    assert service.store.is_processed("p1")
    assert service.store.is_processed("p2")
    fetched.clear()
    service.receive(ChatMessage("r2", HACK, "maya", "Rally, recap again", NOW + timedelta(seconds=30)))
    assert fetched == []


def test_second_direct_call_does_not_wait_on_extract(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class SlowExtract(ConversationAgent):
        def extract(self, messages, previous):
            started.set()
            release.wait(2)
            return PlanFacts(activity="dinner", goal="Friday dinner")

    agent = SlowExtract()
    service, sent, reactions, _ = _service(tmp_path, agent=agent, defer_heavy_work=True)
    assert service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    assert started.wait(1)
    begun = time.perf_counter()
    assert service.receive(ChatMessage("d2", HACK, "nick", "Hey Rally, what time works?",
                                       NOW + timedelta(seconds=30)))
    assert time.perf_counter() - begun < 0.4
    assert sent[-1][1] == "here is the recap."
    release.set()


def test_conversation_sees_prior_rally_reply_and_proposal(tmp_path):
    service, sent, reactions, agent = _service(tmp_path)
    service.receive(ChatMessage("d1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    plan = service.store.get_plan(HACK)
    proposal = Proposal("p1", plan.id, plan.version, "v1", "Ramen House", "1 Main",
                        "2026-09-27", "20:00", 2, "pending")
    service.store.save_proposal(proposal)
    service.receive(ChatMessage("d2", HACK, "nick", "Hey Rally, is ramen still the pick?",
                                NOW + timedelta(seconds=30)))
    later = agent.seen_messages[-1]
    assert any(item.is_from_rally and "here is the recap" in item.text for item in later)
    assert agent.seen_proposal[-1]["venue_name"] == "Ramen House"
    assert agent.seen_proposal[-1]["time"] == "20:00"


@pytest.mark.parametrize("kind", ["love", "laugh", "emphasize", "question", "dislike"])
def test_completion_uses_the_chosen_tapback(tmp_path, kind):
    agent = ConversationAgent()
    agent.reaction = kind
    service, sent, reactions, _ = _service(tmp_path, agent=agent)
    service.receive(ChatMessage("r1", HACK, "nick", "Hey Rally, where should we eat?", NOW))
    assert reactions == [(HACK, "r1", "👀"), (HACK, "r1", kind)]
