import unittest
from datetime import datetime, timezone

from app.debug_view import render_debug_view
from app.models import ChatMessage, Plan, PlanFacts, Proposal, Reservation


NOW = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)


class DebugViewTests(unittest.TestCase):
    def test_evidence_resolves_escaped_source_quotes_only_from_this_chat(self):
        messages = [
            ChatMessage("m1", "group-1", "nick", '<b>Dinner Friday?</b>', NOW),
            ChatMessage("m4", "other-group", "private", "SECRET", NOW),
        ]
        page = render_debug_view(self.plan(), None, None, messages=messages)
        self.assertIn("&lt;b&gt;Dinner Friday?&lt;/b&gt;", page)
        self.assertIn("nick", page)
        self.assertIn("Source message unavailable", page)
        self.assertNotIn("SECRET", page)
        self.assertNotIn("<b>Dinner Friday?</b>", page)

    def plan(self, **overrides):
        facts = PlanFacts(
            goal="Friday dinner", activity="dinner",
            participants=["nick", "sarah", "alex"], date="2026-10-02",
            earliest_time="19:00", location="Midtown, New York",
            excluded_cuisines=["sushi"], blockers=["venue missing"],
            evidence={"date": ["m1"], "location": ["m4"]}, confidence=0.93,
        )
        for key, value in overrides.items():
            setattr(facts, key, value)
        return Plan("plan-1", "group-1", 2, facts, "BLOCKED", NOW)

    def test_renders_plan_reasoning_and_state_path(self):
        page = render_debug_view(self.plan(), None, None)
        for expected in ("Friday dinner", "BLOCKED", "venue missing", "93%",
                         "3 people interested", "After 19:00", "sushi", "Midtown, New York",
                         "m1", "m4", "Propose a venue"):
            self.assertIn(expected, page)
        self.assertIn('name="viewport"', page)
        self.assertIn("@media (max-width: 760px)", page)
        self.assertNotIn("<script", page)

    def test_renders_proposal_and_tool_result(self):
        plan = self.plan()
        plan.state = "DONE"
        proposal = Proposal("prop-1", plan.id, plan.version, "v1", "An Italian Table",
                            "123 Main St", "2026-10-02", "20:00", 3,
                            status="approved", created_at=NOW.isoformat())
        reservation = Reservation(proposal.id, "RLY-123", "confirmed")
        page = render_debug_view(plan, proposal, reservation)
        for expected in ("An Italian Table", "123 Main St", "Wait for approval",
                         "RLY-123", "confirmed", "Party of 3", "DONE"):
            if expected == "Wait for approval":
                self.assertNotIn(expected, page)
            else:
                self.assertIn(expected, page)

    def test_known_party_size_takes_precedence_over_interest_estimate(self):
        plan = self.plan()
        plan.facts.party_size = 4
        page = render_debug_view(plan, None, None)
        self.assertIn("Party of 4", page)
        self.assertNotIn("3 people interested", page)

    def test_escapes_every_dynamic_field(self):
        plan = self.plan(goal='<script>alert("x")</script>',
                         participants=['<img src=x onerror=alert(1)>'],
                         blockers=['<b>bad</b>'],
                         evidence={"<svg/onload=1>": ["<i>m</i>"]})
        plan.chat_id = '<img src=x onerror=alert(2)>'
        plan.state = '<script>alert(3)</script>'
        proposal = Proposal("p", plan.id, 1, "v", "<img src=x>", "<b>street</b>",
                            "2026-10-02", "20:00", 1, status="<script>x</script>")
        reservation = Reservation("p", "<i>code</i>", "<svg/onload=1>")
        page = render_debug_view(plan, proposal, reservation)
        for unsafe in ("<script", "<img", "<svg", "<b>bad</b>", "<i>code</i>"):
            self.assertNotIn(unsafe, page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;img", page)
        self.assertIn("&lt;i&gt;code&lt;/i&gt;", page)

    def test_empty_sections_explain_what_is_missing(self):
        plan = Plan("p", "c", 1, PlanFacts(goal="Dinner", confidence=0.2), "SPARK", NOW)
        page = render_debug_view(plan, None, None)
        self.assertIn("No proposal yet", page)
        self.assertIn("No reservation result yet", page)
        self.assertIn("No specific blocker recorded", page)

    def test_refresh_has_keyboard_landmarks_and_reduced_motion_support(self):
        page = render_debug_view(self.plan(), None, None)
        for expected in (
            '<a class="skip-link" href="#main-content">Skip to plan details</a>',
            '<nav class="section-nav" aria-label="Plan sections">',
            'href="#conversation-signals"',
            'href="#message-evidence"',
            'href="#proposal"',
            '<main id="main-content">',
            ":focus-visible",
            "#0A84FF",
            "-apple-system",
            "prefers-reduced-motion: reduce",
            'aria-current="step"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, page)

    def test_plan_sections_keep_clear_scan_order_and_anchor_targets(self):
        page = render_debug_view(self.plan(), None, None)
        anchors = ("conversation-signals", "current-blocker", "message-evidence",
                   "proposal", "reservation-result")
        positions = [page.index(f'id="{anchor}"') for anchor in anchors]
        self.assertEqual(positions, sorted(positions))
        for heading in ("Conversation signals", "Current blocker", "Message evidence",
                        "Proposal", "Latest demo reservation result"):
            self.assertIn(f"<h2>{heading}</h2>", page)

    def test_narrow_mobile_section_header_can_stack_without_overflow(self):
        page = render_debug_view(self.plan(), None, None)
        self.assertIn(".section-head { flex-direction:column;", page)
        self.assertIn(".confidence { white-space:normal;", page)


if __name__ == "__main__":
    unittest.main()
