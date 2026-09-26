"""Server-rendered, iMessage-inspired group portal.

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


def _attachments(items: list[dict], media_enabled: bool) -> str:
    if not media_enabled:
        return ""
    rendered = []
    for item in items:
        name = _e(item.get("name") or "Attachment")
        url = _safe_media_url(item.get("url")) if item.get("available", True) else None
        if url:
            mime = str(item.get("mime") or "")
            if mime.startswith("image/"):
                rendered.append(f'<li><a href="{url}"><img src="{url}" alt="{name}" loading="lazy"></a></li>')
            elif mime.startswith("video/"):
                rendered.append(f'<li><video controls preload="metadata" src="{url}" aria-label="{name}"></video></li>')
            elif mime.startswith("audio/"):
                rendered.append(f'<li><audio controls preload="none" src="{url}" aria-label="{name}"></audio></li>')
            else:
                rendered.append(f'<li><a href="{url}" download>{name}</a></li>')
        else:
            rendered.append(f'<li><span>{name}</span> <small>Media unavailable</small></li>')
    return f'<ul class="attachments">{"".join(rendered)}</ul>' if rendered else ""


def render_portal(data: dict) -> str:
    """Return a standalone portal page from prefiltered group data.

    Accepted keys: title, import_status, members, messages, plans, analytics,
    settings. Settings flags are history, media, plans, and analytics; absent
    flags default to visible. Message and media access control belongs to the
    HTTP layer, not this renderer.
    """
    title = _e(data.get("title") or "Your group")
    theme = data.get("theme") if data.get("theme") in {"imessage", "midnight", "sage"} else "imessage"
    settings = data.get("settings") or {}
    members = data.get("members") or []
    status = data.get("import_status") or {}
    imported = status.get("imported", 0)
    state = status.get("state") or "pending"
    status_label = "History imported" if state == "complete" else "Importing history" if state == "running" else "History import pending" if state == "pending" else "History import needs attention"
    member_html = "".join(f"<li>{_e(member)}</li>" for member in members) or "<li>Members not available yet</li>"
    enabled = {name: _section_enabled(settings, name) for name in ("history", "media", "plans", "analytics", "members", "activity")}
    if not enabled["members"]:
        member_html = "<li>Member list hidden</li>"

    if enabled["history"]:
        bubbles = []
        for msg in data.get("messages") or []:
            sender = _e(msg.get("sender") or "Unknown")
            when = _e(msg.get("timestamp") or "")
            body = _e(msg.get("text") or "")
            media = _attachments(msg.get("attachments") or [], enabled["media"])
            reactions = "".join(f'<span>{_e(r.get("sender"))}: {_e(r.get("type"))}</span>' for r in msg.get("reactions") or [])
            if not body and not media:
                continue
            bubbles.append(f'<li class="message"><div class="message-meta"><strong>{sender}</strong> <time>{when}</time></div><div class="bubble">{body}{media}</div><div class="reactions">{reactions}</div></li>')
        history = f'<ol class="messages">{"".join(bubbles) if bubbles else "<li class=empty>No messages imported yet.</li>"}</ol>'
        older_url = _safe_media_url(data.get("older_url"))
        if older_url:
            history += f'<p class="older"><a href="{older_url}">Older messages</a></p>'
    else:
        history = '<p class="empty">History is hidden for this group.</p>'

    if enabled["plans"]:
        plan_items = []
        for plan in data.get("plans") or []:
            details = "".join(f'<li>{_e(detail)}</li>' for detail in plan.get("details") or [])
            plan_items.append(f'<li class="plan"><strong>{_e(plan.get("title") or "Plan")}</strong><span>{_e(plan.get("state") or "In progress")}</span><small>{_e(plan.get("date") or "")}</small>{f"<ul>{details}</ul>" if details else ""}</li>')
        plans = f'<ul class="plans">{"".join(plan_items) if plan_items else "<li class=empty>Rally has not tracked a plan here yet.</li>"}</ul>'
        if enabled["history"]:
            plans += '<form action="?" method="get" class="old-plan-search"><label for="old-plan-query">Search older plans</label><div><input id="old-plan-query" name="old_plan_query" type="search" placeholder="What plan are you looking for?"><button type="submit">Search</button></div><small>Results from older messages are inferred and should include message evidence.</small></form><div id="historical-results"></div>'
        else:
            plans += '<p class="status">Show conversation history to search older plans.</p>'
        if data.get("historical_query"):
            findings = []
            for finding in data.get("historical_results") or []:
                evidence = "".join(f'<li>{_e(item.get("sent_at"))}: {_e(item.get("text"))}</li>' for item in finding.get("evidence") or [])
                findings.append(f'<li><strong>{_e(finding.get("title"))}</strong><p>{_e(finding.get("summary"))}</p><details><summary>Supporting messages</summary><ul>{evidence}</ul></details></li>')
            result = _e(data.get("historical_error") or "No matching older plans found.")
            plans += f'<div class="historical"><h3>Possible older plans</h3><ul>{"".join(findings)}</ul>{"" if findings else f"<p>{result}</p>"}</div>'
    else:
        plans = '<p class="empty">Plans are hidden for this group.</p>'

    if enabled["analytics"]:
        metrics = data.get("analytics") or {}
        rows = "".join(f'<div><dt>{_e(key)}</dt><dd>{_e(value)}</dd></div>' for key, value in metrics.items())
        analytics = f'<dl class="metrics">{rows}</dl>' if rows else '<p class="empty">Analytics will appear as history is imported.</p>'
    else:
        analytics = '<p class="empty">Analytics are hidden for this group.</p>'

    if enabled["activity"]:
        action_items = "".join(f'<li><strong>{_e(item.get("kind"))}</strong><span>{_e(item.get("status"))}</span><p>{_e(item.get("text"))}</p></li>' for item in data.get("actions") or [])
        activity = f'<ul class="activity-list">{action_items or "<li class=empty>No Rally actions yet.</li>"}</ul>'
    else:
        activity = '<p class="empty">Rally activity is hidden for this group.</p>'

    controls = "".join(f'<li>{name.title()}: {"Shown" if visible else "Hidden"}</li>' for name, visible in enabled.items())
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Rally</title><style>
:root {{ color-scheme:light; --blue:#007aff; --ink:#172334; --muted:#617084; --line:#dce2e9; --surface:#fff; --back:#f2f3f7; }}
body.midnight {{ color-scheme:dark; --blue:#61a4ff; --ink:#eef3fb; --muted:#b0bfd1; --line:#3a4758; --surface:#202a38; --back:#121a25; }}
body.sage {{ --blue:#447c63; --ink:#20312a; --muted:#61756a; --line:#d1dfd4; --surface:#fff; --back:#edf4ed; }}
* {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }}
body {{ margin:0; background:var(--back); color:var(--ink); font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
a {{ color:#0659b9; }} a:focus-visible,button:focus-visible,input:focus-visible {{ outline:3px solid #ffbd44; outline-offset:3px; }}
header {{ background:var(--surface); border-bottom:1px solid var(--line); padding:1rem max(1rem,calc((100vw - 1080px)/2)); }}
.brand {{ color:var(--blue); font-size:.8rem; font-weight:800; letter-spacing:.07em; text-transform:uppercase; }}
h1 {{ margin:.1rem 0; font-size:clamp(1.7rem,4vw,2.7rem); line-height:1.2; }} h2 {{ margin:0 0 1rem; font-size:1.18rem; }}
.members {{ display:flex; flex-wrap:wrap; gap:.35rem .7rem; list-style:none; padding:0; margin:.4rem 0 0; color:var(--muted); font-size:.9rem; }}
.members li+li:before {{ content:"· "; }}
main {{ width:min(1080px,calc(100% - 2rem)); margin:1.5rem auto 4rem; display:grid; grid-template-columns:minmax(0,1.8fr) minmax(260px,1fr); gap:1rem; align-items:start; }}
.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:18px; padding:1.2rem; min-width:0; margin-bottom:1rem; }}
.history {{ grid-row:span 3; }} .status {{ margin:0 0 1rem; color:var(--muted); font-size:.85rem; }}
.messages {{ list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:1.15rem; max-height:68vh; overflow:auto; }}
.message {{ max-width:min(90%,560px); }} .message-meta {{ color:var(--muted); font-size:.75rem; display:flex; flex-wrap:wrap; gap:.45rem; padding:0 .7rem .2rem; }}
.bubble {{ background:#e9e9eb; border-radius:18px 18px 18px 5px; padding:.7rem 1rem; white-space:pre-wrap; overflow-wrap:anywhere; }}
.midnight .bubble {{ background:#34455a; color:#fff; }} .midnight .reactions span {{ background:#202a38; }}
.attachments {{ list-style:none; padding:.35rem 0 0; margin:0; }} .attachments li {{ padding:.3rem 0; border-top:1px solid #cbd3dc; }} .attachments small {{ display:block; color:var(--muted); }}
.attachments img,.attachments video {{ display:block; width:min(100%,360px); max-height:320px; object-fit:contain; border-radius:10px; }} .attachments audio {{ max-width:100%; }}
.reactions {{ display:flex; gap:.35rem; flex-wrap:wrap; padding:.2rem .6rem; color:var(--muted); font-size:.72rem; }} .reactions span {{ border:1px solid var(--line); background:#fff; border-radius:20px; padding:.1rem .4rem; }}
.plans {{ list-style:none; padding:0; margin:0; }} .plan {{ display:grid; grid-template-columns:1fr auto; gap:0 .6rem; padding:.65rem 0; border-bottom:1px solid var(--line); }}
.plan span {{ color:var(--blue); font-size:.8rem; font-weight:700; }} .plan small {{ color:var(--muted); }}
.plan ul {{ grid-column:1 / -1; margin:.4rem 0; padding-left:1.2rem; font-size:.85rem; color:var(--muted); }}
.activity-list {{ list-style:none; padding:0; margin:0; max-height:20rem; overflow:auto; }} .activity-list li {{ border-bottom:1px solid var(--line); padding:.5rem 0; }} .activity-list span {{ float:right; color:var(--blue); font-size:.8rem; }} .activity-list p {{ margin:.25rem 0; font-size:.85rem; white-space:pre-wrap; }}
.old-plan-search {{ margin-top:1.3rem; }} label {{ display:block; font-weight:700; margin-bottom:.4rem; }} .old-plan-search div {{ display:flex; gap:.4rem; }}
input {{ min-width:0; flex:1; border:1px solid #a9b7c8; border-radius:10px; padding:.6rem; font:inherit; }} button {{ border:0; border-radius:10px; background:var(--blue); color:#fff; padding:.6rem .9rem; font:inherit; font-weight:700; cursor:pointer; }}
.old-plan-search small,.empty {{ color:var(--muted); }} .metrics {{ margin:0; }} .metrics div {{ display:flex; justify-content:space-between; gap:1rem; border-bottom:1px solid var(--line); padding:.5rem 0; }} .metrics dd {{ margin:0; font-weight:700; text-align:right; }}
.historical {{ margin-top:1.2rem; border-top:1px solid var(--line); padding-top:.8rem; }} .historical h3 {{ margin:.2rem 0; font-size:1rem; }} .historical ul {{ padding-left:1.2rem; }} .historical li {{ margin:.7rem 0; }} .historical p {{ margin:.2rem 0; }} .older {{ text-align:center; }}
.controls {{ padding-left:1.2rem; margin:.3rem 0 0; color:var(--muted); font-size:.88rem; }}
@media (max-width: 700px) {{ main {{ display:block; }} .messages {{ max-height:none; }} .panel {{ padding:1rem; }} }}
</style></head><body class="{theme}">
<header><div class="brand">Rally · Group space</div><h1>{title}</h1><ul class="members" aria-label="Group members">{member_html}</ul></header>
<main><section class="panel history" aria-labelledby="history-title"><h2 id="history-title">Conversation history</h2><p class="status" role="status">{status_label} · {_e(imported)} messages</p>{history}</section>
<section class="panel" aria-labelledby="plans-title"><h2 id="plans-title">Rally plans</h2>{plans}</section>
<section class="panel" aria-labelledby="analytics-title"><h2 id="analytics-title">Group analytics</h2>{analytics}</section>
<section class="panel" aria-labelledby="activity-title"><h2 id="activity-title">Rally activity</h2>{activity}</section>
<section class="panel" aria-labelledby="settings-title"><h2 id="settings-title">Portal settings</h2><ul class="controls">{controls}</ul><p class="status">In the group chat, ask “Hey Rally, hide media on our page” or “Hey Rally, show media.”</p></section></main>
</body></html>'''
