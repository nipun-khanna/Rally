from datetime import datetime, timezone

from app.voice.personal import callee_report


WHEN = datetime(2026, 9, 27, 12, 54, tzinfo=timezone.utc)


def test_reports_callee_answer_not_assistant_invention():
    evidence = {"messages": [
        {"role": "assistant", "text": "Hi Tarun. I think you are free at 2:00 PM."},
        {"role": "user", "text": "Yeah, it's a great time."},
        {"role": "assistant", "text": "When are you free?"},
        {"role": "user", "text": "I'm free at 4:00 PM today."},
    ]}
    body = callee_report(
        evidence, name="Tarun", purpose="ask when he's free", when=WHEN)
    assert "Tarun" in body and "4:00 PM today" in body
    assert "2:00 PM" not in body and "great time" not in body


def test_any_callee_answer_is_reported_not_just_availability():
    evidence = {"messages": [
        {"role": "assistant", "text": "Do you have patio seating tonight?"},
        {"role": "user", "text": "Patio is closed. Dining room until 9."},
    ]}
    body = callee_report(
        evidence, name="The tavern", purpose="ask about patio seating")
    assert "Patio is closed" in body and "Dining room until 9" in body
    assert "couldn't verify" not in body.lower()


def test_multiple_callee_answers_are_preserved():
    evidence = {"messages": [
        {"role": "user", "text": "I can do 4 PM Tuesday."},
        {"role": "user", "text": "Wednesday at 6 PM works for me too."},
    ]}
    body = callee_report(evidence, name="Nipun", purpose="ask when he's free")
    assert "4 PM Tuesday" in body and "Wednesday at 6 PM" in body


def test_no_callee_evidence_never_invents_an_answer():
    for evidence in (None, {}, {"messages": [{"role": "assistant", "text": "Tarun is free at 4 PM"}]},
                     {"messages": [{"role": "user", "text": "Thanks, bye."}]}):
        body = callee_report(evidence, name="Tarun", purpose="ask when he's free")
        assert "couldn't verify" in body.lower()
        assert "4 PM" not in body


def test_conflicting_callee_statements_report_uncertainty():
    evidence = {"messages": [
        {"role": "user", "text": "I'm free at 4 PM."},
        {"role": "user", "text": "Actually, I am not free at 4 PM."},
    ]}
    body = callee_report(evidence, name="Tarun")
    assert "couldn't verify" in body.lower()


def test_drops_audio_glitches_and_keeps_the_actual_answer():
    evidence = {"messages": [
        {"role": "user", "text": "Yeah, now's a good time."},
        {"role": "user", "text": "Uh, can we schedule a pizza plans with Tarun?"},
        {"role": "user", "text": "Uh, let's do tomorrow at 1:00 PM."},
        {"role": "user", "text": "Why did it cut off? Wait. It's now. I'm going to your audio?"},
        {"role": "user", "text": "Oh. Huh. What the hell? What? It's gone— oh, yeah, I'm still here."},
        {"role": "user", "text": "Just say anything. Wait. It just— it kept cutting out."},
        {"role": "user", "text": "Yeah, let's continue. Um,"},
    ]}
    body = callee_report(evidence, name="Nipun")
    assert "The call with Nipun ended." in body
    assert "pizza" in body.lower() and "1:00 pm" in body.lower()
    assert "started a plan" in body.lower()
    assert "cutting out" not in body.lower()
    assert "what the hell" not in body.lower()
    assert "vapi" not in body.lower()


def test_restaurant_ask_starts_a_plan_instead_of_dumping_transcript():
    evidence = {"messages": [
        {"role": "user", "text": "Yes."},
        {"role": "user", "text": "Um, can you find a restaurant near Midtown. Atlanta?"},
        {"role": "user", "text": "we're looking for a low price range for, uh, probably preferably Mexican food."},
        {"role": "user", "text": "Going to the side"},
    ]}
    from app.voice.personal import callee_followup
    body, facts = callee_followup(evidence, name="Nipun")
    assert "They said:" not in body
    assert "mexican" in body.lower() and "midtown" in body.lower()
    assert "started a plan" in body.lower()
    assert "yes." not in body.lower()
    assert "going to the side" not in body.lower()
    assert facts is not None
    assert facts.location == "Midtown Atlanta"
    assert "Mexican" in facts.preferred_cuisines
