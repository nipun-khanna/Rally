from datetime import datetime, timezone

from app.models import PlanFacts
from app.store import Store


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def test_a_new_topic_creates_a_separate_plan_instead_of_overwriting(tmp_path):
    store = Store(tmp_path / "rally.sqlite3")
    chat = "iMessage;+;group"
    store.save_plan(chat, PlanFacts(activity="dinner", goal="Dinner plan"), NOW)
    store.save_plan(chat, PlanFacts(activity="movie", goal="Movie night"), NOW)
    plans = store.plans_for_chat(chat)
    assert len(plans) == 2
    assert {p.facts.activity for p in plans} == {"dinner", "movie"}


def test_same_activity_still_updates_in_place(tmp_path):
    store = Store(tmp_path / "rally.sqlite3")
    chat = "iMessage;+;group"
    store.save_plan(chat, PlanFacts(activity="dinner", goal="Dinner plan"), NOW)
    store.save_plan(chat, PlanFacts(activity="dinner", goal="Dinner plan", location="Taj"), NOW)
    plans = store.plans_for_chat(chat)
    assert len(plans) == 1
    assert plans[0].facts.location == "Taj"
