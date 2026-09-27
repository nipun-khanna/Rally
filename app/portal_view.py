"""Server-rendered group portal: one page, the plans and the group's stats up front.

The caller supplies already-authorized group data. This module only formats it.
"""

import json
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


_STATE_INK = {"Ready to book": "ink-live", "Booking": "ink-live", "Confirmed": "ink-done",
              "Canceled": "ink-canceled"}


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

    group_id = data.get("group_id")
    body = f'''  <section aria-labelledby="plans-title">
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
  </section>'''
    return _shell(title, body, group_id=group_id, active="overview",
                  knowledge=_section_enabled(settings, "knowledge"))


def _nav(group_id: str | None, active: str, knowledge: bool) -> str:
    if not group_id or not knowledge:
        return ""
    base = "/" + _e(group_id)
    items = [("overview", "Overview", base), ("knowledge", "Knowledge", base + "/knowledge")]
    current = ' class="current" aria-current="page"'
    links = "".join(f'<a href="{href}"{current if key == active else ""}>{label}</a>'
                    for key, label, href in items)
    return f'<nav class="page-nav" aria-label="Group page">{links}</nav>'


def _shell(title: str, body: str, *, group_id: str | None, active: str, knowledge: bool,
           main_class: str = "", script: str = "") -> str:
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Ubuntu:wght@300;400&display=swap" rel="stylesheet">
<title>{title} · Rally</title><style>{_CSS}</style></head><body>
<a class="skip-link" href="#main-content">Skip to content</a>
<header class="top{" wide" if main_class else ""}">
  <h1>{title}</h1>
  {_nav(group_id, active, knowledge)}
</header>
<main id="main-content" class="{main_class}">
{body}
</main>{script}
</body></html>'''



def _fact_sections(sections: list[dict]) -> str:
    return "".join(
        f'<div class="kb-cat"><p class="kb-cat-label">{_e(sec["label"])}</p>'
        f'<ul class="kb-facts">{"".join(f"<li>{_e(f)}</li>" for f in sec["facts"])}</ul></div>'
        for sec in sections)


def render_knowledge(data: dict) -> str:
    """People-first knowledge page with a private, per-device chat beside it."""
    title = _e(data.get("title") or "Your group")
    group_id = data.get("group_id")
    people = data.get("people") or []
    person_html = "".join(
        f'<section class="kb-person"><div class="kb-person-head">'
        f'<span class="avatar">{_e(_initials(p["name"]))}</span>'
        f'<h2>{_e(p["name"])}</h2></div>{_fact_sections(p["sections"])}</section>'
        for p in people)
    group_sections = data.get("group") or []
    group_html = (f'<section class="kb-person"><div class="kb-person-head"><h2>The group</h2></div>'
                  f'{_fact_sections(group_sections)}</section>' if group_sections else "")
    links = data.get("links") or []
    links_html = ("<section><p class=\"section-label\">In common</p><ul class=\"kb-facts\">" +
                  "".join(f'<li>{_e(l["a"])} and {_e(l["b"])}: {_e(l["shared"])}</li>' for l in links) +
                  "</ul></section>" if links else "")
    if not (people or group_sections):
        kb_html = ('<p class="empty">Rally is still getting to know everyone. '
                   'Things people mention in the chat will show up here.</p>')
    else:
        kb_html = group_html + person_html + links_html
    names = [n for n in (data.get("members") or []) if n][:3]
    suggestions = [f"Gift ideas for {names[0]}?" if names else "Gift ideas for someone?",
                   f"Where should I take {names[1] if len(names) > 1 else names[0]}?" if names
                   else "Where should we go this weekend?",
                   "What food does everyone agree on?"]
    chips = "".join(f'<button type="button" class="kb-suggest">{_e(q)}</button>' for q in suggestions)
    body = f"""  <div class="kb-layout">
    <div class="kb-main">
      <p class="section-label">What Rally knows</p>
      {kb_html}
    </div>
    <aside class="kb-chat" aria-label="Ask about the group">
      <p class="section-label">Ask</p>
      <div class="kb-log" id="kb-log" aria-live="polite"></div>
      <div class="kb-suggestions" id="kb-suggestions">{chips}</div>
      <form class="kb-form" id="kb-form">
        <label class="visually-hidden" for="kb-input">Ask about someone in the group</label>
        <input id="kb-input" maxlength="300" autocomplete="off" placeholder="Ask about someone">
        <button type="submit">Send</button>
      </form>
      <p class="kb-note">Only you can see this chat. <button type="button" class="kb-clear" id="kb-clear">Clear</button></p>
    </aside>
  </div>"""
    script = "<script>" + _CHAT_JS.replace("__GROUP__", json.dumps(group_id or "").replace("<", "\\u003c")) + "</script>"
    return _shell(title, body, group_id=group_id, active="knowledge", knowledge=True,
                  main_class="wide", script=script)


_CHAT_JS = """
(() => {
  const group = __GROUP__;
  const key = "rally-chat:" + group;
  const log = document.getElementById("kb-log");
  const form = document.getElementById("kb-form");
  const input = document.getElementById("kb-input");
  const suggest = document.getElementById("kb-suggestions");
  let state;
  try { state = JSON.parse(localStorage.getItem(key)) || {}; } catch (_) { state = {}; }
  if (!state.deviceId) state.deviceId = (crypto.randomUUID && crypto.randomUUID()) || String(Math.random()).slice(2);
  state.messages = Array.isArray(state.messages) ? state.messages.slice(-30) : [];
  const save = () => { try { localStorage.setItem(key, JSON.stringify(state)); } catch (_) {} };
  const bubble = (role, text) => {
    const el = document.createElement("div");
    el.className = "kb-msg " + role;
    el.textContent = text;
    log.append(el);
    log.scrollTop = log.scrollHeight;
    return el;
  };
  const render = () => {
    log.replaceChildren();
    state.messages.forEach(m => bubble(m.role, m.content));
    suggest.hidden = state.messages.length > 0;
  };
  render(); save();
  let busy = false;
  async function ask(question) {
    question = question.trim().slice(0, 300);
    if (!question || busy) return;
    busy = true; input.value = ""; suggest.hidden = true;
    bubble("user", question);
    const history = state.messages.slice(-10);
    state.messages.push({ role: "user", content: question }); save();
    const out = bubble("assistant pending", "…");
    let text = "";
    try {
      const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group_id: group, device_id: state.deviceId, question, history }) });
      if (!res.ok || !res.body) throw new Error(String(res.status));
      const reader = res.body.getReader(); const dec = new TextDecoder();
      out.classList.remove("pending");
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        text += dec.decode(value, { stream: true });
        out.textContent = text;
        log.scrollTop = log.scrollHeight;
      }
    } catch (err) {
      text = err.message === "429" ? "Slow down a sec, then try again." : "Couldn't reach Rally right now. Try again in a moment.";
      out.classList.remove("pending"); out.textContent = text;
    }
    state.messages.push({ role: "assistant", content: text }); save();
    busy = false; input.focus();
  }
  form.addEventListener("submit", e => { e.preventDefault(); ask(input.value); });
  suggest.addEventListener("click", e => { if (e.target.matches(".kb-suggest")) ask(e.target.textContent); });
  document.getElementById("kb-clear").addEventListener("click", () => { state.messages = []; save(); render(); });
})();
"""

_CSS = """
:root {
  color-scheme: light; --bg: #fff; --ink: #0b0b0d; --ink-soft: #6b6f76;
  --line: #e4e6ea; --fill: #f2f3f5; --fill-glass: rgba(0,0,0,.045); --blue: #0a84ff;
  --green: #248a3d; --orange: #b25400;
}
@media (prefers-color-scheme: dark) {
  :root { color-scheme: dark; --bg: #000; --ink: #f5f6f7; --ink-soft: #9a9ea6;
    --line: #2c2e33; --fill: #1e1f23; --fill-glass: rgba(255,255,255,.07); --blue: #409cff; --green: #63d883; --orange: #ffb15c; }
}
* { box-sizing: border-box; } html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--ink); position: relative; overflow-x: hidden;
  font: 300 17px/1.5 Ubuntu, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
}
body::before, body::after {
  content: ""; position: fixed; z-index: -1; border-radius: 50%; filter: blur(80px); pointer-events: none;
}
body::before { top: -160px; right: -140px; width: 420px; height: 420px; background: var(--blue); opacity: .14; }
body::after { top: 480px; left: -180px; width: 360px; height: 360px; background: var(--ink-soft); opacity: .08; }
a { color: var(--blue); text-decoration: none; }
a:focus-visible, button:focus-visible { outline: 3px solid var(--blue); outline-offset: 2px; border-radius: 6px; }
.skip-link { position: absolute; top: -5rem; left: 1rem; z-index: 20; background: var(--bg); padding: .6rem .9rem; border-radius: 10px; }
.skip-link:focus { top: .6rem; }

header.top { padding: 3rem 1.3rem 1.4rem; max-width: 760px; margin: 0 auto; }
header.top.wide { max-width: 1080px; }
.page-nav { display: flex; gap: 1.4rem; margin-top: 1rem; font-size: 1rem; }
.page-nav a { color: var(--ink-soft); }
.page-nav a.current { color: var(--ink); }
.page-nav a:hover { color: var(--ink); }
h1 { margin: 0; font-size: 3rem; font-weight: 300; letter-spacing: -.02em; line-height: 1.05; }

main { width: min(760px, 100%); margin: 0 auto; padding: 0 1.3rem 3.5rem; }
section { margin-bottom: 2.6rem; }
.section-label { font-size: .9rem; font-weight: 400; color: var(--ink-soft); margin: 0 0 .9rem; }
.empty { color: var(--ink-soft); font-weight: 300; }

.stat-list { list-style: none; margin: 0; padding: 0; }
.plan-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.plan-row { padding: 1.1rem 0; border-bottom: 1px solid var(--line); }
.plan-row:first-child { padding-top: 0; }
.plan-list.stack {
  flex-direction: row; align-items: stretch; gap: 1rem; overflow-x: auto; padding-bottom: .6rem;
  scrollbar-width: thin; -webkit-overflow-scrolling: touch;
}
.plan-list.stack .plan-row {
  flex: 0 0 210px; border-bottom: none; background: var(--fill-glass);
  -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px); border-radius: 16px;
  padding: 1.1rem 1.2rem; display: flex; flex-direction: column;
}
.plan-head { display: flex; align-items: baseline; justify-content: space-between; gap: .8rem; }
.stack .plan-head { flex-direction: column; align-items: flex-start; gap: .4rem; }
.plan-title { font-size: 1.7rem; font-weight: 300; letter-spacing: -.01em; }
.stack .plan-title { font-size: 1.25rem; line-height: 1.2; }
.plan-state { font-size: .84rem; font-weight: 400; color: var(--ink-soft); white-space: nowrap; }
.ink-live { color: var(--orange); } .ink-done { color: var(--green); } .ink-open { color: var(--blue); } .ink-canceled { color: var(--ink-soft); }
.plan-meta { margin: .3rem 0 0; color: var(--ink-soft); font-size: 1rem; font-weight: 300; }
.stack .plan-meta { font-size: .88rem; }
.plan-detail { margin: .5rem 0 0; color: var(--ink-soft); font-size: .88rem; font-weight: 300; }
.stack .plan-detail { font-size: .8rem; }

.stat-row { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; padding: .85rem 0; border-bottom: 1px solid var(--line); }
.stat-row:last-child { border-bottom: none; }
.stat-row dt { font-size: 1.05rem; font-weight: 300; color: var(--ink-soft); }
.stat-row dd { margin: 0; font-size: 1.4rem; font-weight: 400; letter-spacing: -.01em; }

.bar-list { list-style: none; margin: .9rem 0 0; padding: 0; display: flex; flex-direction: column; gap: .6rem; }
.bar-row { display: grid; grid-template-columns: 100px 1fr 34px; align-items: center; gap: .7rem; font-size: .92rem; }
.bar-name { color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 300; }
.bar-track { height: 6px; border-radius: 980px; background: var(--fill); overflow: hidden; }
.bar-fill { display: block; height: 100%; border-radius: 980px; background: var(--blue); }
.bar-fill-soft { background: var(--blue); opacity: .4; }
.bar-count { color: var(--ink-soft); text-align: right; font-weight: 300; }

.member-list { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 1rem 1.3rem; }
.member-chip { display: flex; align-items: center; gap: .55rem; }
.avatar { width: 36px; height: 36px; border-radius: 50%; background: var(--fill); color: var(--ink-soft);
  display: flex; align-items: center; justify-content: center; font-weight: 400; font-size: .82rem; flex-shrink: 0; }
.member-name { font-size: .95rem; font-weight: 300; }

@media (max-width: 480px) {
  header.top { padding: 2rem 1rem 1.1rem; } main { padding: 0 1rem 2.6rem; }
  h1 { font-size: 2.1rem; } .plan-title { font-size: 1.35rem; }
  .bar-row { grid-template-columns: 76px 1fr 30px; }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }

main.wide { width: min(1080px, 100%); }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.kb-layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 2.4rem; align-items: start; }
.kb-person { margin-bottom: 2.2rem; }
.kb-person-head { display: flex; align-items: center; gap: .7rem; margin-bottom: .6rem; }
.kb-person h2 { margin: 0; font-size: 1.6rem; font-weight: 300; letter-spacing: -.01em; }
.kb-cat { display: grid; grid-template-columns: 110px 1fr; gap: .8rem; padding: .55rem 0; border-bottom: 1px solid var(--line); }
.kb-cat:last-child { border-bottom: none; }
.kb-cat-label { margin: 0; color: var(--ink-soft); font-size: .88rem; padding-top: .1rem; }
.kb-facts { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .25rem; font-size: 1rem; }
.kb-chat { position: sticky; top: 1.2rem; background: var(--fill-glass); -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px); border-radius: 18px; padding: 1.1rem; display: flex; flex-direction: column; max-height: calc(100vh - 2.4rem); }
.kb-log { flex: 1; min-height: 160px; max-height: 52vh; overflow-y: auto; display: flex; flex-direction: column; gap: .5rem; padding-bottom: .5rem; }
.kb-msg { max-width: 88%; padding: .55rem .85rem; border-radius: 18px; font-size: .95rem; line-height: 1.4; white-space: pre-wrap; overflow-wrap: anywhere; }
.kb-msg.user { align-self: flex-end; background: var(--blue); color: #fff; border-bottom-right-radius: 6px; }
.kb-msg.assistant { align-self: flex-start; background: var(--bg); color: var(--ink); border-bottom-left-radius: 6px; }
.kb-msg.pending { color: var(--ink-soft); }
.kb-suggestions { display: flex; flex-direction: column; align-items: flex-start; gap: .35rem; margin-bottom: .7rem; }
.kb-suggest, .kb-clear { appearance: none; background: none; border: 0; padding: 0; font: inherit; color: var(--blue); cursor: pointer; text-align: left; font-size: .92rem; }
.kb-form { display: flex; gap: .5rem; }
.kb-form input { flex: 1; min-width: 0; border: 0; border-radius: 980px; padding: .6rem .95rem; font: inherit; font-size: .95rem; background: var(--bg); color: var(--ink); }
.kb-form button { appearance: none; border: 0; border-radius: 980px; padding: .6rem 1rem; font: inherit; font-size: .92rem; background: var(--blue); color: #fff; cursor: pointer; }
.kb-note { margin: .6rem 0 0; font-size: .8rem; color: var(--ink-soft); }
@media (max-width: 860px) {
  .kb-layout { grid-template-columns: 1fr; }
  .kb-chat { position: static; max-height: none; }
  .kb-cat { grid-template-columns: 1fr; gap: .2rem; }
}
"""
