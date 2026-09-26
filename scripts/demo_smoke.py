"""Offline code-only smoke check of the full coordination loop.

Uses fixed extraction and venue fixtures; it does not contact Grok, Geoapify,
BlueBubbles, or make a real reservation.
"""

import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent import AgentDecision
from app.models import ChatMessage, PlanFacts
from app.orchestrator import RallyService
from app.places import Venue
from app.store import Store


class DemoAgent:
    def __init__(self, facts):
        self.facts = facts

    def extract(self, messages, previous):
        return self.facts

    def decide(self, facts, messages, previous_results=None):
        venue_id = previous_results[0]["venues"][0]["id"] if previous_results else None
        return AgentDecision(action="PROPOSE", reason="restaurant not selected",
                             tool="search_places", confidence=0.93, venue_id=venue_id)


def run_demo() -> dict:
    started = time.monotonic()
    now = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
    chat = "iMessage;+;rally-demo"
    transcript = [
        ("nick", "Dinner Friday?"),
        ("sarah", "I'm down. Anything except sushi."),
        ("alex", "Same, but I can't until after 7."),
        ("maya", "I'll join too. Midtown?"),
    ]
    facts = PlanFacts(goal="Friday dinner", activity="dinner",
                      participants=["nick", "sarah", "alex", "maya"],
                      date="2026-09-25", earliest_time="19:00",
                      location="Midtown, New York", excluded_cuisines=["sushi"],
                      blockers=["restaurant not selected"], confidence=0.93)
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "rally.sqlite3")
        for index, (sender, text) in enumerate(transcript):
            store.add_message(ChatMessage(f"seed-{index}", chat, sender, text,
                                          now - timedelta(minutes=34 - index)))
            store.mark_processed(f"seed-{index}")
        store.save_plan(chat, facts, now - timedelta(minutes=31))
        sent = []
        venue = Venue("demo-italian", "An Italian Table", "123 Main St, Midtown, New York",
                      40.75, -73.98, ("italian",), source="demo")
        service = RallyService(store, DemoAgent(facts), lambda _: [venue],
                               lambda target, message: sent.append((target, message)), 30)
        service.tick(now)
        proposal_id = store.get_plan(chat).pending_proposal_id
        service.receive(ChatMessage("approval", chat, "nick", "Book it.", now))
        return {"state": store.get_plan(chat).state,
                "reservation_count": int(store.reservation(proposal_id) is not None),
                "sent_messages": len(sent),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "messages": [text for _, text in sent]}


if __name__ == "__main__":
    print(json.dumps(run_demo()))
