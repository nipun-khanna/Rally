"""Local receive-path profiler. No live iMessage, no Grok HTTP, no .env prints."""

from __future__ import annotations

import cProfile
import io
import json
import pstats
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent import GroupConversationDecision, GrokClient, MemoryCandidate
from app.group_memory import GroupMemoryStore
from app.group_turns import GroupTurnStore
from app.models import ChatMessage, PlanFacts
from app.orchestrator import RallyService
from app.store import Store

NOW = datetime(2026, 9, 26, 21, tzinfo=timezone.utc)
HACK = "iMessage;+;hackgt13"
OTHER = "iMessage;+;other"


class StageClock:
    def __init__(self):
        self.marks: list[tuple[str, float]] = []

    def mark(self, name: str, seconds: float):
        self.marks.append((name, seconds))

    def summary(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for name, seconds in self.marks:
            totals[name] = totals.get(name, 0.0) + seconds
        return totals


class FakeAgent:
    def __init__(self, clock: StageClock, decide_s=0.0, extract_s=0.0, learn_s=0.0):
        self.clock = clock
        self.decide_s = decide_s
        self.extract_s = extract_s
        self.learn_s = learn_s
        self.decide_calls = 0
        self.extract_calls = 0
        self.learn_calls = 0

    def extract(self, messages, previous):
        self.extract_calls += 1
        time.sleep(self.extract_s)
        self.clock.mark("extract", self.extract_s)
        return PlanFacts(activity="dinner", goal="Friday dinner", date="2026-09-27",
                         location="Rambler Atlanta")

    def decide_conversation(self, request, facts, messages, *, memory_context="",
                            followup=False, proposal=None):
        self.decide_calls += 1
        time.sleep(self.decide_s)
        self.clock.mark("decide_conversation", self.decide_s)
        return GroupConversationDecision(
            relevant=True, safety="ok", message="ramen at rambler saturday.",
            reaction="like",
            memory_candidates=[MemoryCandidate(key="food.preference", fact="the group prefers ramen")],
        )

    def learn_memory(self, request, messages, *, memory_context=""):
        self.learn_calls += 1
        time.sleep(self.learn_s)
        self.clock.mark("learn_memory", self.learn_s)
        return [MemoryCandidate(key="food.preference", fact="the group prefers ramen")]


def _service(db: Path, agent, *, defer: bool, send_s=0.0, react_s=0.0, clock: StageClock):
    sent = []

    def send_fn(chat, text):
        time.sleep(send_s)
        clock.mark("bluebubbles_send", send_s)
        sent.append((chat, text))

    def react_fn(chat, message_id, reaction):
        time.sleep(react_s)
        clock.mark("react", react_s)

    def typing_fn(chat, on):
        clock.mark("typing", 0.0)

    service = RallyService(
        Store(db), agent, lambda facts: [], send_fn,
        group_memory=GroupMemoryStore(db), group_turns=GroupTurnStore(db),
        react_fn=react_fn, typing_fn=typing_fn,
        allowed_chat_ids={HACK, OTHER},
        defer_heavy_work=defer,
    )
    return service, sent


def _seed(service: RallyService, count: int = 12):
    for index in range(count):
        service.store.add_message(ChatMessage(
            f"seed-{index}", HACK, "nick" if index % 2 == 0 else "maya",
            f"seed chat line {index} about dinner",
            NOW - timedelta(minutes=30 - index), False))
    service.store.save_plan(HACK, PlanFacts(
        activity="dinner", date="2026-09-27", time="20:00", party_size=4,
        location="Rambler Atlanta", preferred_cuisines=["ramen"]), NOW)
    service.group_memory.upsert_fact(
        HACK, "food.preference", "the group prefers ramen", "seed-0", NOW)


def _receive(service, suffix: str, text="Hey Rally, where should we eat?"):
    started = time.perf_counter()
    accepted = service.receive(ChatMessage(
        f"probe-{suffix}", HACK, "nick", text, NOW + timedelta(seconds=len(suffix))))
    return accepted, (time.perf_counter() - started) * 1000


def profile_instant():
    clock = StageClock()
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "rally.sqlite3"
        agent = FakeAgent(clock)
        service, _ = _service(db, agent, defer=True, clock=clock)
        _seed(service)
        profiler = cProfile.Profile()
        profiler.enable()
        for index in range(8):
            _receive(service, f"instant-{index}", f"Hey Rally, ping {index}?")
        if service._pool:
            service._pool.shutdown(wait=True)
        profiler.disable()
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats("cumtime")
        stats.print_stats(25)
        return stream.getvalue(), (time.perf_counter(),)


def stage_run(*, defer: bool, decide_s: float, extract_s: float, learn_s: float,
              send_s: float, react_s: float, label: str):
    clock = StageClock()
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "rally.sqlite3"
        agent = FakeAgent(clock, decide_s=decide_s, extract_s=extract_s, learn_s=learn_s)
        service, sent = _service(db, agent, defer=defer, send_s=send_s,
                                 react_s=react_s, clock=clock)
        _seed(service)
        accepted, wall_ms = _receive(service, label)
        if service._pool:
            heavy_started = time.perf_counter()
            service._pool.shutdown(wait=True)
            heavy_ms = (time.perf_counter() - heavy_started) * 1000
        else:
            heavy_ms = 0.0
        return {
            "label": label,
            "defer": defer,
            "accepted": accepted,
            "receive_return_ms": round(wall_ms, 1),
            "background_wait_ms": round(heavy_ms, 1),
            "sent": len(sent),
            "decide_calls": agent.decide_calls,
            "extract_calls": agent.extract_calls,
            "learn_calls": agent.learn_calls,
            "stages_ms": {name: round(seconds * 1000, 1) for name, seconds in clock.summary().items()},
        }


def payload_size():
    captured = []

    def transport(payload):
        captured.append(payload)
        return {
            "relevant": True, "safety": "ok", "message": "ramen.",
            "reaction": "like", "memory_candidates": [],
        }

    client = GrokClient("unused", transport=transport)
    messages = [
        ChatMessage(f"m{i}", HACK, "nick", f"line {i} " + ("word " * 12), NOW, False)
        for i in range(20)
    ]
    client.decide_conversation(
        "Hey Rally, where should we eat?",
        PlanFacts(activity="dinner", date="2026-09-27", location="Atlanta"),
        messages,
        memory_context="- the group prefers ramen\n" * 12,
        followup=False,
        proposal={"venue_name": "Rambler", "date": "2026-09-27", "time": "20:00"},
    )
    payload = captured[0]
    encoded = json.dumps(payload, ensure_ascii=False)
    prompt = payload["messages"][0]["content"]
    user = payload["messages"][1]["content"]
    return {
        "payload_bytes": len(encoded.encode()),
        "system_prompt_chars": len(prompt),
        "user_json_chars": len(user),
        "thread_messages": len(json.loads(user)["messages"]),
        "timeout_non_extract": 10,
        "timeout_extract": 60,
    }


def recap_skips_model():
    clock = StageClock()
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "rally.sqlite3"
        agent = FakeAgent(clock, decide_s=2.0)
        service, sent = _service(db, agent, defer=True, clock=clock)
        _seed(service)
        _, wall_ms = _receive(service, "recap", "Rally, recap dinner?")
        if service._pool:
            service._pool.shutdown(wait=True)
        return {
            "receive_return_ms": round(wall_ms, 1),
            "decide_calls": agent.decide_calls,
            "sent": sent[-1][1] if sent else "",
            "stages_ms": {name: round(seconds * 1000, 1) for name, seconds in clock.summary().items()},
        }


def main():
    print("=== payload / timeouts ===")
    print(json.dumps(payload_size(), indent=2))

    print("\n=== recap local fallback (plan present) ===")
    print(json.dumps(recap_skips_model(), indent=2))

    print("\n=== stage timings ===")
    cases = [
        stage_run(defer=True, decide_s=0, extract_s=0, learn_s=0, send_s=0, react_s=0,
                  label="local-only-defer"),
        stage_run(defer=False, decide_s=0, extract_s=0.2, learn_s=0.1, send_s=0, react_s=0,
                  label="sync-extract-300ms"),
        stage_run(defer=True, decide_s=0, extract_s=0.2, learn_s=0.1, send_s=0, react_s=0,
                  label="defer-extract-300ms"),
        stage_run(defer=True, decide_s=0.8, extract_s=1.2, learn_s=0.4, send_s=0.35, react_s=0.05,
                  label="simulated-live-shape"),
    ]
    print(json.dumps(cases, indent=2))

    print("\n=== cProfile FakeAgent 8 receives (cumtime) ===")
    dump, _ = profile_instant()
    print(dump)


if __name__ == "__main__":
    main()
