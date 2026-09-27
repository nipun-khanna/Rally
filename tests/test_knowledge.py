from app.agent import GrokClient
import threading
import time

from app.knowledge import (GROUP_SUBJECT, DebouncedKnowledgeRunner, KnowledgeBuilder,
                           KnowledgeStore, eligible_kb_fact)
from app.portal_store import PortalStore

CHAT = "any;+;group"


def test_filter_allows_allergies_birthdays_and_rejects_negatives_and_secrets():
    assert eligible_kb_fact("Tarun is allergic to peanuts.")
    assert eligible_kb_fact("Akhil's birthday is March 3.")
    assert eligible_kb_fact("Sanjan is vegetarian.")
    assert not eligible_kb_fact("Nipun is really rude.")
    assert not eligible_kb_fact("Akhil is kind of annoying.")
    assert not eligible_kb_fact("Tarun's password is hunter2.")
    assert not eligible_kb_fact("Call Sanjan at 678-599-1244.")


def test_upsert_replaces_by_key_and_caps_per_person(tmp_path):
    store = KnowledgeStore(tmp_path / "r.sqlite3")
    assert store.upsert_fact(CHAT, "a", "food.mexican", "food", "A likes Mexican food.", "m1", .6)
    assert store.upsert_fact(CHAT, "a", "food.mexican", "food", "A loves spicy Mexican food.", "m2", .9)
    facts = store.facts(CHAT)
    assert len(facts) == 1 and facts[0]["fact"] == "A loves spicy Mexican food."
    for i in range(40):
        store.upsert_fact(CHAT, "a", f"likes.k{i}", "likes", f"A likes thing {i}.", "m", .5)
    assert len([f for f in store.facts(CHAT) if f["subject_id"] == "a"]) == 25
    assert not store.upsert_fact(CHAT, "a", "Bad Key!", "food", "A likes tea.", "m", .5)


def test_forget_matching_removes_facts(tmp_path):
    store = KnowledgeStore(tmp_path / "r.sqlite3")
    store.upsert_fact(CHAT, "a", "food.sushi", "food", "A loves sushi.", "m1", .8)
    assert store.forget_matching(CHAT, "sushi") == 1
    assert store.facts(CHAT) == []


def _portal(tmp_path):
    portal = PortalStore(tmp_path / "r.sqlite3")
    portal.ensure_group(CHAT)
    portal.set_member(CHAT, "+1555", "Tarun")
    portal.upsert_messages(CHAT, [
        {"message_id": "m1", "sender_id": "+1555", "text": "i could eat tacos every day",
         "sent_at": "2026-09-26T10:00:00+00:00"},
        {"message_id": "m2", "sender_id": "+1555", "text": "Rally: noted",
         "sent_at": "2026-09-26T10:01:00+00:00"},
    ])
    return portal


def _agent(response, seen):
    def transport(payload):
        seen.append(payload)
        return response
    return GrokClient("key", transport=transport)


def test_builder_saves_validated_facts_and_advances_cursor(tmp_path):
    portal = _portal(tmp_path)
    store = KnowledgeStore(tmp_path / "r.sqlite3")
    seen = []
    agent = _agent({"facts": [
        {"subject_id": "+1555", "category": "food", "key": "food.tacos",
         "fact": "Tarun loves tacos.", "confidence": .9, "source_message_id": "m1"},
        {"subject_id": "stranger", "category": "food", "key": "food.x",
         "fact": "Someone likes x.", "confidence": .9, "source_message_id": "m1"},
        {"subject_id": "+1555", "category": "food", "key": "food.y",
         "fact": "Tarun likes y.", "confidence": .9, "source_message_id": "invented"},
        {"subject_id": "+1555", "category": "personality", "key": "personality.rude",
         "fact": "Tarun is rude.", "confidence": .9, "source_message_id": "m1"},
    ], "removals": [], "links": []}, seen)
    builder = KnowledgeBuilder(store, portal, agent, owner_name="Akshit")
    assert builder.run(CHAT) == 1
    assert [f["fact"] for f in store.facts(CHAT)] == ["Tarun loves tacos."]
    sent = seen[0]["messages"][1]["content"]
    assert "tacos every day" in sent and "Rally: noted" not in sent
    assert store.cursor(CHAT)[1] == "m1"
    assert builder.run(CHAT) == 0
    assert len(seen) == 1


def test_builder_refresh_reads_only_messages_after_its_cursor(tmp_path):
    portal = _portal(tmp_path)
    store = KnowledgeStore(tmp_path / "r.sqlite3")
    seen = []
    agent = _agent({"facts": [], "removals": [], "links": []}, seen)
    builder = KnowledgeBuilder(store, portal, agent)

    assert builder.run(CHAT) == 0
    portal.upsert_messages(CHAT, [{"message_id": "m3", "sender_id": "+1555",
                                   "text": "i also love dumplings",
                                   "sent_at": "2026-09-26T10:02:00+00:00"}])
    assert builder.run(CHAT) == 0

    latest = seen[-1]["messages"][1]["content"]
    assert '"id": "m3"' in latest
    assert '"id": "m1"' not in latest


def test_builder_accepts_group_facts(tmp_path):
    portal = _portal(tmp_path)
    store = KnowledgeStore(tmp_path / "r.sqlite3")
    agent = _agent({"facts": [{"subject_id": GROUP_SUBJECT, "category": "activities",
                               "key": "activities.taco_tuesday", "fact": "The group does taco Tuesdays.",
                               "confidence": .7, "source_message_id": "m1"}],
                    "removals": [], "links": []}, [])
    assert KnowledgeBuilder(store, portal, agent).run(CHAT) == 1


def _portal_two_batches(tmp_path):
    portal = PortalStore(tmp_path / "r.sqlite3")
    portal.ensure_group(CHAT)
    portal.set_member(CHAT, "+1555", "Tarun")
    portal.upsert_messages(CHAT, [
        {"message_id": "m1", "sender_id": "+1555", "text": "i love tacos",
         "sent_at": "2026-09-26T10:00:00+00:00"},
        {"message_id": "m2", "sender_id": "+1555", "text": "i love sushi too",
         "sent_at": "2026-09-26T10:05:00+00:00"},
    ])
    return portal


def test_one_failed_batch_does_not_block_the_rest_of_the_backlog(tmp_path):
    portal = _portal_two_batches(tmp_path)
    store = KnowledgeStore(tmp_path / "r.sqlite3")
    calls = []

    def transport(payload):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("simulated timeout")
        return {"facts": [{"subject_id": "+1555", "category": "food", "key": "food.sushi",
                           "fact": "Tarun loves sushi.", "confidence": .9, "source_message_id": "m2"}],
                "removals": [], "links": []}

    agent = GrokClient("key", transport=transport)
    builder = KnowledgeBuilder(store, portal, agent, batch_size=1)
    builder.run(CHAT)
    assert [f["fact"] for f in store.facts(CHAT)] == ["Tarun loves sushi."]
    assert store.cursor(CHAT)[1] == "m2"
    assert len(calls) == 2


def test_debounced_runner_processes_messages_arriving_during_a_run():
    started = threading.Event()
    release = threading.Event()
    calls = []

    class Builder:
        def run(self, _chat_id):
            calls.append(1)
            if len(calls) == 1:
                started.set()
                release.wait(timeout=1)
            return 0

    runner = DebouncedKnowledgeRunner(Builder(), interval=0)
    runner(CHAT)
    assert started.wait(timeout=1)
    runner(CHAT)
    release.set()
    deadline = time.monotonic() + 1
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(.01)
    assert len(calls) == 2
