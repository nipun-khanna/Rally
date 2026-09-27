import unittest

from app.portal_view import render_portal


class PortalViewTests(unittest.TestCase):
    def test_page_has_keyboard_navigation_and_respects_reduced_motion(self):
        page = render_portal({"title": "Friends"})
        self.assertIn('class="skip-link" href="#main-content"', page)
        self.assertIn('id="main-content"', page)
        self.assertIn(':focus-visible', page)
        self.assertIn('@media (prefers-reduced-motion: reduce)', page)
        self.assertIn('@media (max-width: 480px)', page)
        self.assertIn('--blue: #0a84ff', page)
        self.assertIn('Ubuntu', page)
        self.assertNotIn(">Rally<", page)

    def test_full_portal_renders_plans_stats_and_members(self):
        page = render_portal({
            "title": "Friday Crew",
            "members": ["Akshit", "Nipun"],
            "plans": [{"title": "Dinner", "state": "Ready to book", "date_label": "Tomorrow",
                      "time_label": "8:00 PM", "location": "Taj", "details": []}],
            "analytics": {"Total messages": 42, "Funniest": "Nipun"},
            "member_stats": [{"name": "Nipun", "count": 30, "pct": 100},
                             {"name": "Akshit", "count": 12, "pct": 40}],
            "settings": {"analytics": True, "members": True},
        })
        for expected in ("Friday Crew", "Akshit", "Nipun", "Dinner", "Total messages",
                         "Funniest", "name=\"viewport\"", "Most active", "Ready to book", "Plans"):
            self.assertIn(expected, page)
        self.assertNotIn("ALIGNMENT", page)
        self.assertNotIn("Rally activity", page)
        self.assertNotIn("direct_reply", page)
        self.assertNotIn("Still needs", page)
        self.assertNotIn("Page visibility", page)
        self.assertNotIn("font-weight: 700", page)
        self.assertNotIn("font-weight: 600", page)

    def test_hidden_sections_and_escaped_content(self):
        page = render_portal({
            "title": '<script>alert(1)</script>', "members": ['<b>name</b>'],
            "plans": [{"title": "private plan"}], "analytics": {"count": "secret count"},
            "settings": {"analytics": False, "members": True},
        })
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<b>name", page)
        self.assertNotIn("secret count", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Stats are hidden", page)

    def test_no_plans_shows_empty_state_not_raw_log(self):
        page = render_portal({"title": "Empty Crew", "plans": []})
        self.assertIn("No plan yet", page)
        self.assertNotIn("Rally activity", page)

    def test_member_without_a_name_gets_a_hash_avatar_not_a_raw_number(self):
        page = render_portal({"members": ["(678) 599-1244"]})
        self.assertIn('<span class="avatar">#</span>', page)

    def test_early_stage_plan_shows_no_state_tag(self):
        page = render_portal({"plans": [{"title": "Brunch", "state": ""}]})
        self.assertIn("Brunch", page)
        self.assertNotIn('span class="plan-state', page)

    def test_multiple_plans_get_the_horizontal_stack_class(self):
        page = render_portal({"plans": [{"title": "Brunch"}, {"title": "Dinner"}]})
        self.assertIn('class="plan-list stack"', page)

    def test_single_plan_does_not_get_the_stack_class(self):
        page = render_portal({"plans": [{"title": "Brunch"}]})
        self.assertIn('<ul class="plan-list">', page)


if __name__ == "__main__":
    unittest.main()
