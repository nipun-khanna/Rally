"""Server-rendered group portal: one page, the plans and the group's stats up front.

The caller supplies already-authorized group data. This module only formats it.
"""

from html import escape
from urllib.parse import urlsplit


def _e(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _safe_media_url(value: object) -> str | None:
    """Keep media links on this origin; never emit executable or remote URLs."""
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or "\\" in value or any(ord(c) < 32 for c in value):
        return None
    return _e(value)


def _section_enabled(settings: dict, name: str) -> bool:
    return settings.get(name, True) is not False


def _initials(name: str) -> str:
    words = [w for w in name.replace("(", " ").replace(")", " ").replace("-", " ").split() if w]
    letters = "".join(w[0] for w in words[:2] if w[0].isalpha())
    return letters.upper() if letters else "#"


_STATE_INK = {"Ready to book": "ink-live", "Booking": "ink-live", "Confirmed": "ink-done"}


def _plan_row(plan: dict) -> str:
    state = plan.get("state") or ""
    ink = _STATE_INK.get(state, "ink-open")
    title = _e(plan.get("title") or "Group plan")
    when_parts = [part for part in (_e(plan.get("date_label")), _e(plan.get("time_label"))) if part]
    meta = [p for p in when_parts]
    if plan.get("location"):
        meta.append(_e(plan["location"]))
    if plan.get("party_size"):
        meta.append(f'{_e(plan["party_size"])} people')
    meta_line = " · ".join(meta)
    detail = _e((plan.get("details") or [""])[-1]) if plan.get("details") else ""
    return f'''<li class="plan-row">
<div class="plan-head"><span class="plan-title">{title}</span>{f'<span class="plan-state {ink}">{_e(state)}</span>' if state else ""}</div>
{f'<p class="plan-meta">{meta_line}</p>' if meta_line else ""}
{f'<p class="plan-detail">{detail}</p>' if detail else ""}
</li>'''


def _stat_row(label: str, value: object) -> str:
    return f'<div class="stat-row"><dt>{_e(label)}</dt><dd>{_e(value)}</dd></div>'


def _member_bar(entry: dict, index: int) -> str:
    name = _e(entry.get("name") or "Someone")
    count = _e(entry.get("count") or 0)
    pct = max(6, int(entry.get("pct") or 0))
    shade = "bar-fill" if index == 0 else "bar-fill bar-fill-soft"
    return (f'<li class="bar-row"><span class="bar-name">{name}</span>'
           f'<span class="bar-track"><span class="{shade}" style="width:{pct}%"></span></span>'
           f'<span class="bar-count">{count}</span></li>')


def _member_chip(name: str) -> str:
    return (f'<li class="member-chip"><span class="avatar">{_e(_initials(name))}</span>'
           f'<span class="member-name">{_e(name)}</span></li>')


def render_portal(data: dict) -> str:
    """Return a standalone portal page from prefiltered group data.

    Accepted keys: title, members, plans, analytics, member_stats, settings.
    Settings flags are analytics and members; absent flags default to visible.
    """
    title = _e(data.get("title") or "Your group")
    settings = data.get("settings") or {}
    members = data.get("members") or []
    enabled = {name: _section_enabled(settings, name) for name in ("analytics", "members")}
    member_html = "".join(_member_chip(m) for m in members) if (enabled["members"] and members) else ""
    if not enabled["members"]:
        members_body = '<p class="empty">Members are hidden for this group.</p>'
    elif not members:
        members_body = '<p class="empty">Members will appear once the group is imported.</p>'
    else:
        members_body = f'<ul class="member-list">{member_html}</ul>'

    plans = data.get("plans") or []
    rows = "".join(_plan_row(plan) for plan in plans)
    list_class = "plan-list stack" if len(plans) > 1 else "plan-list"
    plans_body = (f'<ul class="{list_class}">{rows}</ul>' if rows
                  else '<p class="empty">No plan yet — ask Rally in the group chat.</p>')

    if enabled["analytics"]:
        metrics = data.get("analytics") or {}
        stat_rows = "".join(_stat_row(k, v) for k, v in metrics.items())
        stats_html = f'<dl class="stat-list">{stat_rows}</dl>' if stat_rows else '<p class="empty">Stats will appear as history is imported.</p>'
        member_stats = data.get("member_stats") or []
        bars = "".join(_member_bar(m, i) for i, m in enumerate(member_stats[:8]))
        bars_html = (f'<p class="section-label">Most active</p><ul class="bar-list">{bars}</ul>'
                    if bars else "")
        stats_body = stats_html + bars_html
    else:
        stats_body = '<p class="empty">Stats are hidden for this group.</p>'

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Ubuntu:wght@300;400&display=swap" rel="stylesheet">
<title>{title} · Rally</title><style>
:root {{
  color-scheme: light; --bg: #fff; --ink: #0b0b0d; --ink-soft: #6b6f76;
  --line: #e4e6ea; --fill: #f2f3f5; --fill-glass: rgba(0,0,0,.045); --blue: #0a84ff;
  --green: #248a3d; --orange: #b25400;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ color-scheme: dark; --bg: #000; --ink: #f5f6f7; --ink-soft: #9a9ea6;
    --line: #2c2e33; --fill: #1e1f23; --fill-glass: rgba(255,255,255,.07); --blue: #409cff; --green: #63d883; --orange: #ffb15c; }}
}}
* {{ box-sizing: border-box; }} html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; background: var(--bg); color: var(--ink); position: relative; overflow-x: hidden;
  font: 300 17px/1.5 Ubuntu, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
}}
body::before, body::after {{
  content: ""; position: fixed; z-index: -1; border-radius: 50%; filter: blur(80px); pointer-events: none;
}}
body::before {{ top: -160px; right: -140px; width: 420px; height: 420px; background: var(--blue); opacity: .14; }}
body::after {{ top: 480px; left: -180px; width: 360px; height: 360px; background: var(--ink-soft); opacity: .08; }}
a {{ color: var(--blue); text-decoration: none; }}
a:focus-visible, button:focus-visible {{ outline: 3px solid var(--blue); outline-offset: 2px; border-radius: 6px; }}
.skip-link {{ position: absolute; top: -5rem; left: 1rem; z-index: 20; background: var(--bg); padding: .6rem .9rem; border-radius: 10px; }}
.skip-link:focus {{ top: .6rem; }}

header.top {{ padding: 3rem 1.3rem 1.4rem; max-width: 760px; margin: 0 auto; }}
h1 {{ margin: 0; font-size: 3rem; font-weight: 300; letter-spacing: -.02em; line-height: 1.05; }}

main {{ width: min(760px, 100%); margin: 0 auto; padding: 0 1.3rem 3.5rem; }}
section {{ margin-bottom: 2.6rem; }}
.section-label {{ font-size: .9rem; font-weight: 400; color: var(--ink-soft); margin: 0 0 .9rem; }}
.empty {{ color: var(--ink-soft); font-weight: 300; }}

.stat-list {{ list-style: none; margin: 0; padding: 0; }}
.plan-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }}
.plan-row {{ padding: 1.1rem 0; border-bottom: 1px solid var(--line); }}
.plan-row:first-child {{ padding-top: 0; }}
.plan-list.stack {{
  flex-direction: row; align-items: stretch; gap: 1rem; overflow-x: auto; padding-bottom: .6rem;
  scrollbar-width: thin; -webkit-overflow-scrolling: touch;
}}
.plan-list.stack .plan-row {{
  flex: 0 0 210px; border-bottom: none; background: var(--fill-glass);
  -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px); border-radius: 16px;
  padding: 1.1rem 1.2rem; display: flex; flex-direction: column;
}}
.plan-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: .8rem; }}
.stack .plan-head {{ flex-direction: column; align-items: flex-start; gap: .4rem; }}
.plan-title {{ font-size: 1.7rem; font-weight: 300; letter-spacing: -.01em; }}
.stack .plan-title {{ font-size: 1.25rem; line-height: 1.2; }}
.plan-state {{ font-size: .84rem; font-weight: 400; color: var(--ink-soft); white-space: nowrap; }}
.ink-live {{ color: var(--orange); }} .ink-done {{ color: var(--green); }} .ink-open {{ color: var(--blue); }}
.plan-meta {{ margin: .3rem 0 0; color: var(--ink-soft); font-size: 1rem; font-weight: 300; }}
.stack .plan-meta {{ font-size: .88rem; }}
.plan-detail {{ margin: .5rem 0 0; color: var(--ink-soft); font-size: .88rem; font-weight: 300; }}
.stack .plan-detail {{ font-size: .8rem; }}

.stat-row {{ display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; padding: .85rem 0; border-bottom: 1px solid var(--line); }}
.stat-row:last-child {{ border-bottom: none; }}
.stat-row dt {{ font-size: 1.05rem; font-weight: 300; color: var(--ink-soft); }}
.stat-row dd {{ margin: 0; font-size: 1.4rem; font-weight: 400; letter-spacing: -.01em; }}

.bar-list {{ list-style: none; margin: .9rem 0 0; padding: 0; display: flex; flex-direction: column; gap: .6rem; }}
.bar-row {{ display: grid; grid-template-columns: 100px 1fr 34px; align-items: center; gap: .7rem; font-size: .92rem; }}
.bar-name {{ color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 300; }}
.bar-track {{ height: 6px; border-radius: 980px; background: var(--fill); overflow: hidden; }}
.bar-fill {{ display: block; height: 100%; border-radius: 980px; background: var(--blue); }}
.bar-fill-soft {{ background: var(--blue); opacity: .4; }}
.bar-count {{ color: var(--ink-soft); text-align: right; font-weight: 300; }}

.member-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 1rem 1.3rem; }}
.member-chip {{ display: flex; align-items: center; gap: .55rem; }}
.avatar {{ width: 36px; height: 36px; border-radius: 50%; background: var(--fill); color: var(--ink-soft);
  display: flex; align-items: center; justify-content: center; font-weight: 400; font-size: .82rem; flex-shrink: 0; }}
.member-name {{ font-size: .95rem; font-weight: 300; }}

@media (max-width: 480px) {{
  header.top {{ padding: 2rem 1rem 1.1rem; }} main {{ padding: 0 1rem 2.6rem; }}
  h1 {{ font-size: 2.1rem; }} .plan-title {{ font-size: 1.35rem; }}
  .bar-row {{ grid-template-columns: 76px 1fr 30px; }}
}}
@media (prefers-reduced-motion: reduce) {{ html {{ scroll-behavior: auto; }} }}
</style></head><body>
<a class="skip-link" href="#main-content">Skip to content</a>
<header class="top">
  <h1>{title}</h1>
</header>
<main id="main-content">
  <section aria-labelledby="plans-title">
    <p class="section-label" id="plans-title">Plans</p>
    {plans_body}
  </section>
  <section aria-labelledby="stats-title">
    <p class="section-label" id="stats-title">Group stats</p>
    {stats_body}
  </section>
  <section aria-labelledby="members-title">
    <p class="section-label" id="members-title">Members</p>
    {members_body}
  </section>
</main>
</body></html>'''
