"""Read-only, server-rendered relationship dashboard: category, cadence, and real
contact-frequency stats for one owner. No estimates are invented; a missing stat
renders as an explicit dash.
"""

from html import escape

from app.relationships.store import CATEGORIES

_CATEGORY_ORDER = list(CATEGORIES) + ['uncategorized']
_CATEGORY_LABELS = {
    'family': 'Family', 'parent': 'Parents', 'grandparent': 'Grandparents',
    'sibling': 'Siblings', 'cousin': 'Cousins', 'close_friend': 'Close friends',
    'friend': 'Friends', 'other': 'Other', 'uncategorized': 'Uncategorized',
}


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _fmt_date(value: str | None) -> str:
    return _text(value[:10]) if value else '—'


def build_dashboard_data(relationship_store, owner: str) -> dict:
    grouped: dict[str, list[dict]] = {key: [] for key in _CATEGORY_ORDER}
    for person in relationship_store.list_relationships(owner):
        stats = relationship_store.contact_stats(owner, person['label'])
        category = person.get('category') or 'uncategorized'
        grouped.setdefault(category, []).append({
            'label': person['label'], 'mode': person['mode'], 'days': person['days'],
            'paused': bool(person['paused']),
            'last_confirmed_at': person.get('last_confirmed_at'),
            'text_count': stats['text_count'], 'texts_per_day_avg': stats['texts_per_day_avg'],
            'last_text_at': stats['last_text_at'],
        })
    return grouped


def render_dashboard(grouped: dict[str, list[dict]]) -> str:
    sections = []
    total_people = sum(len(v) for v in grouped.values())
    for category in _CATEGORY_ORDER:
        people = grouped.get(category) or []
        if not people:
            continue
        rows = []
        for p in sorted(people, key=lambda p: p['label'].casefold()):
            status = 'paused' if p['paused'] else 'active'
            rows.append(
                "<tr>"
                f"<td>{_text(p['label'])}</td>"
                f"<td>{_text(p['mode'])} / {_text(p['days'])}d</td>"
                f"<td>{status}</td>"
                f"<td>{_fmt_date(p['last_confirmed_at'])}</td>"
                f"<td>{_fmt_date(p['last_text_at'])}</td>"
                f"<td>{_text(p['text_count'])}</td>"
                f"<td>{_text(p['texts_per_day_avg']) if p['texts_per_day_avg'] is not None else '—'}</td>"
                "</tr>"
            )
        sections.append(
            f"<section><h2>{_text(_CATEGORY_LABELS.get(category, category))} "
            f"<span class='count'>({len(people)})</span></h2>"
            "<table><thead><tr><th>Name</th><th>Intention</th><th>Status</th>"
            "<th>Last confirmed</th><th>Last text</th><th>Text count</th>"
            "<th>Texts/day</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></section>"
        )
    body = "".join(sections) if sections else (
        "<p class='empty'>No relationships configured yet. Use "
        "\"Hey Rally, remind me to call Mom every week\" or the voice check-in "
        "to add one.</p>")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Rally Relationships</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{ color-scheme: dark; }}
body {{ margin:0; padding:24px; background:#0a0a10; color:#f4f4f8;
       font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif; }}
h1 {{ font-size:20px; font-weight:600; margin:0 0 4px; }}
.sub {{ color:#8a8a9a; font-size:13px; margin:0 0 24px; }}
section {{ margin-bottom:28px; }}
h2 {{ font-size:14px; font-weight:600; color:#f4f4f8; margin:0 0 8px;
     border-bottom:1px solid #1e1e29; padding-bottom:6px; }}
.count {{ color:#6b6b7a; font-weight:400; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ text-align:left; color:#6b6b7a; font-weight:500; padding:4px 10px 4px 0; }}
td {{ padding:6px 10px 6px 0; border-top:1px solid #14141d; }}
.empty {{ color:#8a8a9a; }}
</style></head>
<body>
<h1>Relationships</h1>
<p class="sub">{total_people} tracked · grouped by category</p>
{body}
</body></html>"""
