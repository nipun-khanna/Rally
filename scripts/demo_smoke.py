"""Offline code-only smoke check of the full coordination loop.

Uses fixed extraction and venue fixtures; it does not contact Grok, Geoapify,
BlueBubbles, or make a real reservation.
"""

import argparse
import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent import AgentDecision
from app.debug_view import render_debug_view
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


def run_demo(output_dir: str | Path | None = None) -> dict:
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    days_to_friday = (4 - now.weekday()) % 7 or 7
    plan_date = (now + timedelta(days=days_to_friday)).date().isoformat()
    chat = "iMessage;+;rally-demo"
    transcript = [
        ("nick", f"Dinner Friday, {plan_date}?"),
        ("sarah", "I'm down. Anything except sushi."),
        ("alex", "Same, but I can't until after 7."),
        ("maya", "I'll join too. Midtown?"),
    ]
    facts = PlanFacts(goal="Friday dinner", activity="dinner",
                      participants=["nick", "sarah", "alex", "maya"],
                      date=plan_date, earliest_time="19:00",
                      location="Midtown, New York", excluded_cuisines=["sushi"],
                      blockers=["restaurant not selected"], confidence=0.93,
                      evidence={"date": ["seed-0"], "excluded_cuisines": ["seed-1"],
                                "earliest_time": ["seed-2"], "location": ["seed-3"]})
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
        sushi = Venue("demo-sushi", "Demo Sushi Bar", "456 Main St, Midtown, New York",
                      40.75, -73.98, ("sushi",), source="demo")
        service = RallyService(store, DemoAgent(facts), lambda _: [sushi, venue],
                               lambda target, message: sent.append((target, message)), 30)

        def snapshot(stage):
            if output_dir is None:
                return
            directory = Path(output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            plan = store.get_plan(chat)
            proposal = store.latest_proposal(plan.id)
            reservation = store.reservation(proposal.id) if proposal else None
            page = render_debug_view(plan, proposal, reservation,
                                     messages=store.recent_messages(chat))
            banner = ("<aside style='padding:1rem;background:#fff1cf;color:#172b46'>"
                      "<strong>Offline replay</strong> · Fixed extraction and venue fixtures; "
                      "real local orchestration, simulated booking, no network calls. "
                      "Sushi candidate rejected by the backend's cuisine filter. "
                      "<nav aria-label='Replay stages'><a href='blocked.html'>1. Blocked</a> · "
                      "<a href='ready.html'>2. Proposal</a> · <a href='done.html'>3. Confirmed</a>"
                      "</nav></aside>")
            (directory / f"{stage}.html").write_text(
                page.replace("<body>", "<body>" + banner), encoding="utf-8")

        snapshot("blocked")
        service.tick(now)
        snapshot("ready")
        proposal_id = store.get_plan(chat).pending_proposal_id
        service.receive(ChatMessage("approval", chat, "nick", "Book it.", now))
        snapshot("done")
        return {"state": store.get_plan(chat).state,
                "plan_date": plan_date,
                "proposal_venue_id": store.get_proposal(proposal_id).venue_id,
                "reservation_count": int(store.reservation(proposal_id) is not None),
                "sent_messages": len(sent),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "messages": [text for _, text in sent]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Export labeled blocked/ready/done browser replay snapshots")
    args = parser.parse_args()
    print(json.dumps(run_demo(args.output_dir)))
