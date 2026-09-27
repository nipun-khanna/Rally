from app.portal_view import render_knowledge, render_portal


def _data(**overrides):
    data = {"title": "Tester", "group_id": "YSOVrF57lVMS4Bj8Nk2xbkET82nB-aD4",
            "members": ["Akhil Meda", "Tarun Devi"],
            "people": [{"name": "Tarun Devi", "sections": [
                {"label": "Food", "facts": ["Tarun loves spicy tacos."]},
                {"label": "Dietary", "facts": ["Tarun is allergic to peanuts."]}]}],
            "group": [{"label": "Activities", "facts": ["The group does taco Tuesdays."]}],
            "links": [{"a": "Akhil Meda", "b": "Tarun Devi", "shared": "both love chocolate"}]}
    data.update(overrides)
    return data


def test_knowledge_page_shows_people_group_links_and_chat():
    page = render_knowledge(_data())
    for expected in ("Tarun loves spicy tacos.", "Tarun is allergic to peanuts.",
                     "The group does taco Tuesdays.", "both love chocolate",
                     'id="kb-form"', "/api/chat", "Only you can see this chat",
                     'aria-current="page">Knowledge'):
        assert expected in page
    assert "font-weight: 700" not in page


def test_knowledge_page_escapes_facts_and_group_id():
    page = render_knowledge(_data(people=[{"name": "<b>x</b>", "sections": [
        {"label": "Food", "facts": ["<script>alert(1)</script>"]}]}], group_id='a"</script>'))
    assert "<script>alert(1)</script>" not in page
    assert '"a\\"\\u003c/script>"' in page


def test_empty_kb_shows_friendly_state():
    page = render_knowledge(_data(people=[], group=[], links=[]))
    assert "still getting to know everyone" in page


def test_overview_links_to_knowledge_unless_hidden():
    shown = render_portal({"title": "T", "group_id": "abc"})
    assert 'href="/abc/knowledge"' in shown
    hidden = render_portal({"title": "T", "group_id": "abc", "settings": {"knowledge": False}})
    assert "/abc/knowledge" not in hidden
