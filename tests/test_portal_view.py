import unittest

from app.portal_view import render_portal


class PortalViewTests(unittest.TestCase):
    def test_archive_has_keyboard_navigation_and_respects_reduced_motion(self):
        page = render_portal({"title": "Friends", "messages": [
            {"sender": "Nipun", "timestamp": "2026-09-26 10:30", "text": "Hello"},
        ]})
        self.assertIn('class="skip-link" href="#main-content"', page)
        self.assertIn('id="main-content"', page)
        self.assertIn('aria-label="Portal sections"', page)
        self.assertIn('aria-label="Conversation messages"', page)
        self.assertIn('aria-label="Message from Nipun', page)
        self.assertIn(':focus-visible', page)
        self.assertIn('@media (prefers-reduced-motion: reduce)', page)
        self.assertIn('@media (max-width: 480px)', page)
        self.assertIn('--blue:#0A84FF', page)

    def test_full_portal_renders_history_media_plans_and_controls(self):
        page = render_portal({
            "title": "Friday Crew", "import_status": {"state": "complete", "imported": 42},
            "members": ["Akshit", "Nipun"],
            "messages": [{"id": "m1", "timestamp": "2026-09-26 10:30", "sender": "Akshit",
                          "text": "See you there", "attachments": [{"name": "photo.jpg", "url": "/media/a", "mime_type": "image/jpeg"}]}],
            "plans": [{"title": "Dinner", "state": "READY", "date": "Friday"}],
            "analytics": {"Top texter": "Nipun"},
            "settings": {"history": True, "media": True, "plans": True, "analytics": True},
        })
        for expected in ("Friday Crew", "Akshit", "Nipun", "See you there", "photo.jpg", "Dinner", "Top texter", "42 messages", "Search older plans", "name=\"viewport\""):
            self.assertIn(expected, page)
        self.assertIn('href="/media/a"', page)
        self.assertIn('action="?"', page)
        self.assertIn('name="old_plan_query"', page)
        self.assertIn('@media (max-width: 700px)', page)

    def test_hidden_sections_and_escaped_content(self):
        page = render_portal({
            "title": '<script>alert(1)</script>', "members": ['<b>name</b>'],
            "messages": [{"sender": "A", "text": "secret"}],
            "plans": [{"title": "private plan"}], "analytics": {"count": "secret count"},
            "settings": {"history": False, "plans": False, "analytics": False},
        })
        self.assertNotIn("<script", page)
        self.assertNotIn("<b>name", page)
        self.assertNotIn("secret", page)
        self.assertNotIn("private plan", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("History is hidden", page)

    def test_missing_media_and_partial_import(self):
        page = render_portal({
            "import_status": {"state": "running", "imported": 12},
            "messages": [{"sender": "A", "text": "", "attachments": [{"name": "old.mov", "available": False}]}],
        })
        self.assertIn("Importing history", page)
        self.assertIn("12 messages", page)
        self.assertIn("old.mov", page)
        self.assertIn("Media unavailable", page)

    def test_midnight_theme_uses_light_links_for_dark_surfaces(self):
        page = render_portal({"theme": "midnight"})
        self.assertIn("--link:#8fc8ff", page)
        self.assertIn("a { color:var(--link);", page)


if __name__ == "__main__":
    unittest.main()
