"""Small server-rendered, dependency-free HTML view for the private dashboard."""

from html import escape


def _e(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _initials(label: object) -> str:
    parts = str(label or "?").split()
    return _e("".join(part[0] for part in parts[:2]).upper())


def render_dashboard(data: dict, csrf: str) -> str:
    cards = []
    for card in data.get("cards", ()):
        evidence = card.get("evidence") or {}
        state = str(card.get("state", "unknown")).lower()
        category = _e(card.get("category", "other"))
        label = _e(card.get("label", "Relationship"))
        intention = _e(card.get("intention") or "Add an intention to make this relationship personal.")
        summary = _e(evidence.get("summary", "No recent activity has been confirmed."))
        mode = _e(card.get("mode", "contact"))
        cadence = _e(card.get("cadence_days", "?"))
        state_label = {"overdue": "Ready for a check-in", "due": "A good time to reach out",
                       "unknown": "Activity not confirmed"}.get(state, state.replace("_", " ").title())
        cards.append(f'''<article class="attention-card state-{_e(state)}">
          <div class="person-mark" aria-hidden="true">{_initials(card.get("label"))}</div>
          <div class="person-copy">
            <div class="person-heading"><div><h3>{label}</h3><p class="relationship-type">{category}</p></div>
              <span class="state-pill">{_e(state_label)}</span></div>
            <p class="intention">{intention}</p>
            <div class="evidence"><span class="evidence-label">What Rally knows</span><p>{summary}</p></div>
            <p class="rhythm">{mode} · every {cadence} days</p>
          </div>
        </article>''')

    plans = []
    for plan in data.get("plans", ()):
        plans.append(f'''<li class="plan-row"><span class="plan-marker" aria-hidden="true"></span>
          <div><strong>{_e(plan.get("title", "Plan"))}</strong>
          <span class="plan-status">{_e(plan.get("status", "open"))}</span></div></li>''')

    card_content = "".join(cards) or '''<div class="empty-state"><span class="empty-mark" aria-hidden="true">✓</span>
      <div><strong>You’re caught up.</strong><p>No relationships need attention right now.</p></div></div>'''
    plan_content = "".join(plans) or '<li class="empty-plan">No tracked plans yet.</li>'

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f4f5f8"><title>Relationships · Rally</title>
<style>
:root {{
  color-scheme: light dark;
  --blue: #0a84ff;
  --blue-deep: #0068d6;
  --ink: #1c1c1e;
  --muted: #68686e;
  --line: #d9dbe1;
  --canvas: #f2f3f7;
  --surface: #ffffff;
  --soft-blue: #eaf3ff;
  --green: #248a55;
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
  background: var(--canvas);
  color: var(--ink);
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-width: 320px; background: var(--canvas); color: var(--ink); }}
a {{ color: var(--blue-deep); }}
:focus-visible {{ outline: 3px solid var(--blue); outline-offset: 3px; border-radius: 4px; }}
.topbar {{ background: var(--surface); border-bottom: 1px solid var(--line); }}
.topbar-inner {{ width: min(1100px, calc(100% - 40px)); margin: auto; min-height: 62px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
.brand {{ display: inline-flex; align-items: center; gap: 9px; color: var(--ink); text-decoration: none; font-size: 1.03rem; font-weight: 700; letter-spacing: -.035em; }}
.brand-mark {{ width: 27px; height: 22px; position: relative; background: var(--blue); border-radius: 8px; box-shadow: 0 2px 4px #007aff35; }}
.brand-mark::after {{ content: ""; position: absolute; bottom: -3px; left: 6px; width: 7px; height: 7px; background: var(--blue); transform: skewY(-34deg); border-radius: 1px; }}
.private-label {{ display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: .8rem; }}
.privacy-dot {{ width: 7px; height: 7px; background: var(--green); border-radius: 50%; }}
main {{ width: min(1100px, calc(100% - 40px)); margin: 0 auto; padding: 54px 0 72px; }}
.page-intro {{ max-width: 690px; margin-bottom: 32px; }}
.page-intro h1 {{ margin: 0; font-size: clamp(2rem, 4.5vw, 3.1rem); letter-spacing: -.055em; line-height: 1.08; font-weight: 720; }}
.page-intro p {{ max-width: 58ch; margin: 13px 0 0; color: var(--muted); font-size: 1.02rem; line-height: 1.6; }}
.dashboard-grid {{ display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(250px, .75fr); align-items: start; gap: 26px; }}
.section-head {{ display: flex; align-items: end; justify-content: space-between; gap: 12px; margin: 0 0 13px; }}
.section-head h2 {{ margin: 0; font-size: 1.1rem; letter-spacing: -.025em; }}
.section-note {{ margin: 4px 0 0; color: var(--muted); font-size: .84rem; }}
.attention-list {{ display: grid; gap: 11px; }}
.attention-card {{ display: grid; grid-template-columns: 46px minmax(0, 1fr); gap: 15px; padding: 19px; background: var(--surface); border: 1px solid var(--line); border-radius: 17px; box-shadow: 0 2px 7px #1c1c1e0a; }}
.person-mark {{ width: 46px; height: 46px; display: grid; place-items: center; border-radius: 15px; background: var(--soft-blue); color: var(--blue-deep); font-size: .92rem; font-weight: 700; letter-spacing: -.03em; }}
.person-copy {{ min-width: 0; }}
.person-heading {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }}
.person-heading h3 {{ margin: 0; font-size: 1.1rem; letter-spacing: -.025em; }}
.relationship-type {{ margin: 1px 0 0; color: var(--muted); font-size: .78rem; text-transform: capitalize; }}
.state-pill {{ flex: 0 0 auto; border-radius: 999px; padding: 4px 9px; background: var(--soft-blue); color: var(--blue-deep); font-size: .72rem; font-weight: 650; line-height: 1.4; }}
.state-unknown .state-pill {{ background: #f0f0f3; color: var(--muted); }}
.intention {{ margin: 11px 0; font-size: .94rem; }}
.evidence {{ border-left: 2px solid #b7d8ff; padding: 1px 0 1px 11px; }}
.evidence-label {{ display: block; color: var(--muted); font-size: .72rem; font-weight: 600; }}
.evidence p {{ margin: 3px 0 0; color: #45454a; font-size: .84rem; line-height: 1.45; }}
.rhythm {{ margin: 10px 0 0; color: var(--muted); font-size: .76rem; text-transform: capitalize; }}
.plans-panel {{ padding: 20px; background: var(--surface); border: 1px solid var(--line); border-radius: 17px; box-shadow: 0 2px 7px #1c1c1e0a; }}
.plans-panel h2 {{ margin: 0; font-size: 1.05rem; letter-spacing: -.025em; }}
.plans-panel > p {{ margin: 5px 0 14px; color: var(--muted); font-size: .82rem; }}
.plan-list {{ list-style: none; margin: 0; padding: 0; }}
.plan-row {{ display: grid; grid-template-columns: 10px minmax(0, 1fr); align-items: baseline; gap: 9px; padding: 11px 0; border-top: 1px solid var(--line); }}
.plan-marker {{ width: 7px; height: 7px; background: var(--blue); border-radius: 50%; }}
.plan-row strong {{ display: block; font-size: .88rem; font-weight: 620; }}
.plan-status {{ display: block; margin-top: 2px; color: var(--muted); font-size: .75rem; text-transform: capitalize; }}
.empty-state {{ display: flex; align-items: center; gap: 13px; padding: 20px; background: var(--surface); border: 1px solid var(--line); border-radius: 17px; color: var(--muted); }}
.empty-mark {{ display: grid; place-items: center; flex: 0 0 38px; width: 38px; height: 38px; border-radius: 50%; background: #e6f5ed; color: var(--green); font-size: 1.1rem; font-weight: 700; }}
.empty-state strong {{ color: var(--ink); }} .empty-state p {{ margin: 2px 0 0; font-size: .88rem; }}
.empty-plan {{ padding: 12px 0; color: var(--muted); font-size: .83rem; }}
@media (max-width: 780px) {{
  main {{ padding-top: 39px; }}
  .dashboard-grid {{ grid-template-columns: 1fr; gap: 27px; }}
}}
@media (max-width: 520px) {{
  .topbar-inner, main {{ width: min(100% - 28px, 1100px); }}
  .topbar-inner {{ min-height: 56px; }}
  main {{ padding-top: 31px; }}
  .private-label {{ font-size: .72rem; }}
  .attention-card {{ grid-template-columns: 38px minmax(0, 1fr); gap: 11px; padding: 15px; border-radius: 14px; }}
  .person-mark {{ width: 38px; height: 38px; border-radius: 12px; }}
  .person-heading {{ flex-direction: column; gap: 6px; }}
  .state-pill {{ align-self: flex-start; }}
  .plans-panel {{ padding: 17px; border-radius: 14px; }}
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --ink:#f5f5f7; --muted:#a1a1a8; --line:#38383d; --canvas:#111114; --surface:#1c1c1f; --soft-blue:#183b60; --blue-deep:#69b4ff; --green:#55c788; }}
  .evidence p {{ color:#d1d1d6; }}
  .state-unknown .state-pill {{ background:#303035; color:#c2c2c7; }}
  .empty-mark {{ background:#173525; color:#62d394; }}
}}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ scroll-behavior:auto !important; animation-duration:.01ms !important; animation-iteration-count:1 !important; transition-duration:.01ms !important; }} }}
</style></head><body>
<header class="topbar"><div class="topbar-inner"><a class="brand" href="#main" aria-label="Rally relationships home"><span class="brand-mark" aria-hidden="true"></span><span>Rally</span></a>
  <span class="private-label"><span class="privacy-dot" aria-hidden="true"></span>Private to you</span></div></header>
<main id="main"><div class="page-intro"><h1>Keep up with your people.</h1>
  <p>Small reminders can help you stay close to the relationships you care about. Rally shows what it knows and where the picture is still incomplete.</p></div>
  <div class="dashboard-grid"><section aria-label="Relationships needing attention">
    <div class="section-head"><div><h2>People to reconnect with</h2><p class="section-note">A gentle nudge, based on your intentions and confirmed activity.</p></div></div>
    <div class="attention-list">{card_content}</div></section>
    <section class="plans-panel" aria-label="Tracked plans"><h2>Plans in motion</h2><p>Follow-ups Rally is keeping track of.</p><ul class="plan-list">{plan_content}</ul></section>
  </div>
</main><form hidden><input name="csrf" value="{_e(csrf)}"></form></body></html>'''
