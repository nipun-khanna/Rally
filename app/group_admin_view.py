"""Local-only HTML for the per-group admin desk. Never embed secret values."""

from html import escape
from urllib.parse import quote


def _t(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _rows(pairs: list[tuple[str, object]]) -> str:
    items = []
    for label, value in pairs:
        if value in (None, "", [], {}):
            continue
        items.append(f"<div><dt>{_t(label)}</dt><dd>{_t(value)}</dd></div>")
    return "".join(items) or "<p class='empty'>Nothing recorded yet.</p>"


def _css() -> str:
    return """
  :root { color-scheme:light; --ink:#1A2330; --mute:#5C6775; --rule:#C5CCD6;
          --paper:#E8ECF1; --card:#FBFCFF; --teal:#1F6B5A; --amber:#C45C12;
          --amber-wash:#F4E3D2; }
  * { box-sizing:border-box; }
  html { scroll-behavior:smooth; }
  body { margin:0; background:var(--paper); color:var(--ink);
         font:16px/1.45 "Avenir Next","Gill Sans",Calibri,sans-serif; }
  .skip-link { position:absolute; left:.6rem; top:.6rem; transform:translateY(-160%);
               background:#fff; color:var(--teal); padding:.5rem .8rem; font-weight:700; }
  .skip-link:focus { transform:none; }
  :focus-visible { outline:3px solid var(--teal); outline-offset:3px; }
  header { padding:1rem max(1rem, calc((100vw - 1080px)/2));
           border-bottom:1px solid var(--rule); background:var(--card); }
  .mark { display:flex; align-items:baseline; gap:.75rem; }
  .mark strong { font-family:"Iowan Old Style","Palatino Linotype",Palatino,serif;
                 font-size:1.45rem; letter-spacing:-.03em; }
  .mark span { color:var(--mute); font-size:.88rem; }
  main { width:min(1080px, calc(100% - 2rem)); margin:1.6rem auto 3rem; }
  h1 { font-family:"Iowan Old Style","Palatino Linotype",Palatino,serif;
       font-size:clamp(1.7rem, 3vw, 2.4rem); letter-spacing:-.03em; margin:0 0 .25rem; }
  h2 { font-size:1.05rem; margin:0 0 .7rem; }
  .guid { font:12px/1.4 "SF Mono",Menlo,Consolas,monospace; color:var(--mute);
          overflow-wrap:anywhere; }
  .lede { color:var(--mute); max-width:62ch; }
  .alert { background:var(--amber-wash); border-left:4px solid var(--amber);
           padding:.8rem 1rem; margin:1rem 0; }
  .alert strong { color:var(--amber); }
  nav.jump { display:flex; flex-wrap:wrap; gap:.35rem; margin:1.1rem 0 1.4rem; }
  nav.jump a { color:var(--teal); text-decoration:none; padding:.28rem .55rem;
               border:1px solid var(--rule); background:var(--card); }
  nav.jump a:hover { text-decoration:underline; }
  .back { display:inline-block; margin-bottom:1rem; color:var(--teal); }
  .stack { display:grid; gap:.85rem; }
  section { background:var(--card); border:1px solid var(--rule); padding:1rem 1.1rem;
            border-left:4px solid var(--teal); scroll-margin-top:.8rem; }
  section.issue { border-left-color:var(--amber); }
  table { width:100%; border-collapse:collapse; font-size:.92rem; }
  th, td { text-align:left; vertical-align:top; padding:.4rem .3rem;
           border-bottom:1px solid #dfe3e8; overflow-wrap:anywhere; }
  th { color:var(--mute); font-weight:600; }
  .who { font-family:"SF Mono",Menlo,Consolas,monospace; font-size:.78rem; }
  .rally td { background:#eef6f3; }
  dl { margin:0; }
  dl div { display:flex; justify-content:space-between; gap:1rem;
           border-bottom:1px solid #dfe3e8; padding:.38rem 0; }
  dt { color:var(--mute); }
  dd { margin:0; text-align:right; overflow-wrap:anywhere; }
  .empty { color:var(--mute); }
  .groups { list-style:none; padding:0; margin:1rem 0 0; }
  .groups li { border-bottom:1px solid var(--rule); }
  .groups a { display:grid; grid-template-columns:minmax(0,1.6fr) auto auto; gap:1rem;
              padding:.85rem 0; color:inherit; text-decoration:none; }
  .groups a:hover { color:var(--teal); }
  .groups strong { font-family:"Iowan Old Style","Palatino Linotype",Palatino,serif;
                   font-size:1.2rem; }
  .wait { color:var(--amber); font-weight:650; }
  @media (max-width: 640px) {
    main { width:calc(100% - 1rem); }
    .groups a { grid-template-columns:1fr; gap:.2rem; }
    dl div { flex-direction:column; }
    dd { text-align:left; }
  }
  @media (prefers-reduced-motion: reduce) {
    *,*::before,*::after { scroll-behavior:auto !important;
      animation-duration:.01ms !important; transition-duration:.01ms !important; }
  }
"""


def render_group_picker(groups: list[dict], token: str = "") -> str:
    del token  # never write the admin token into HTML
    if groups:
        items = []
        for group in groups:
            pending = int(group.get("pending") or 0)
            wait = f"<span class='wait'>{pending} waiting</span>" if pending else "<span>caught up</span>"
            state = _t(group.get("plan_state") or "no plan")
            href = group.get("href") or "/admin/groups/" + quote(str(group.get("chat_id") or ""), safe="")
            items.append(
                f"<li><a href='{_t(href)}'>"
                f"<span><strong>{_t(group.get('title'))}</strong>"
                f"<div class='guid'>{_t(group.get('chat_id'))}</div></span>"
                f"<span>{state}</span>{wait}</a></li>"
            )
        body = f"<ul class='groups'>{''.join(items)}</ul>"
    else:
        body = ("<p class='empty'>No allowlisted group chats. Add a group GUID to "
                "RALLY_ALLOWED_CHAT_GUIDS, then reopen this page.</p>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rally · Group desk</title>
<style>{_css()}</style></head>
<body>
<a class="skip-link" href="#main-content">Skip to groups</a>
<header><div class="mark"><strong>Rally</strong><span>Group desk · local admin · not published</span></div></header>
<main id="main-content">
  <h1>Allowlisted groups</h1>
  <p class="lede">Each row is a group Rally is allowed to see. Open one to inspect messages, plan state, memory, and failures. This page is not part of the public archive.</p>
  {body}
</main></body></html>"""


def render_group_admin(data: dict) -> str:
    token = data.get("token")
    del token  # never write the admin token into HTML
    title = data.get("title") or data.get("chat_id") or "Group"
    processing = data.get("processing") or {}
    pending = int(processing.get("pending") or 0)
    alert = (f"<div class='alert'><strong>{pending} unprocessed</strong> human messages "
             f"are still waiting on Rally.</div>" if pending else "")
    failures = processing.get("failures") or []
    fail_rows = "".join(
        f"<tr><td>{_t(item.get('stage'))}</td><td>{_t(item.get('kind'))}</td>"
        f"<td>{_t(item.get('status') if item.get('status') is not None else '—')}</td>"
        f"<td>{_t(item.get('count'))}</td></tr>"
        for item in failures
    ) or "<tr><td colspan='4' class='empty'>No recorded processing failures.</td></tr>"

    messages = data.get("messages") or []
    if messages:
        msg_rows = []
        for item in messages:
            cls = " class='rally'" if item.get("is_from_rally") else ""
            who = "Rally" if item.get("is_from_rally") else item.get("sender_id")
            msg_rows.append(
                f"<tr{cls}><td class='who'>{_t(who)}</td><td>{_t(item.get('text'))}</td>"
                f"<td>{_t(item.get('sent_at'))}</td><td>{_t(item.get('reaction') or '—')}</td></tr>"
            )
        message_block = ("<table><thead><tr><th>From</th><th>Text</th><th>When</th>"
                         "<th>Tapback</th></tr></thead><tbody>"
                         + "".join(msg_rows) + "</tbody></table>")
    else:
        message_block = "<p class='empty'>No messages stored for this group yet.</p>"

    plan = data.get("plan")
    plan_block = ("<dl>" + _rows([
        ("State", plan.get("state")),
        ("Version", plan.get("version")),
        ("Goal", plan.get("goal")),
        ("Activity", plan.get("activity")),
        ("When", " ".join(part for part in (plan.get("date") or "", plan.get("time") or "") if part) or None),
        ("Place", plan.get("location")),
        ("People", ", ".join(plan.get("participants") or []) or None),
        ("Blockers", "; ".join(plan.get("blockers") or []) or None),
        ("Confidence", f"{plan['confidence']:.0%}"),
    ]) + "</dl>") if plan else "<p class='empty'>Rally has not tracked a plan in this group.</p>"

    proposal = data.get("proposal")
    approval = data.get("approval")
    reservation = data.get("reservation")
    proposal_parts = []
    if proposal:
        proposal_parts.append("<dl>" + _rows([
            ("Venue", proposal.get("venue_name")),
            ("Address", proposal.get("venue_address")),
            ("Status", proposal.get("status")),
            ("When", f"{proposal.get('date')} {proposal.get('time')}"),
            ("Party", proposal.get("party_size")),
        ]) + "</dl>")
    else:
        proposal_parts.append("<p class='empty'>No proposal yet.</p>")
    if approval:
        proposal_parts.append("<p>Approved by " + _t(approval.get("sender_id"))
                              + (" · calendar included" if approval.get("includes_calendar") else "")
                              + "</p>")
    if reservation:
        proposal_parts.append("<p>Reservation " + _t(reservation.get("status"))
                              + " · " + _t(reservation.get("confirmation_id")) + "</p>")

    memory = data.get("memory") or []
    if memory:
        mem_rows = "".join(
            f"<tr><td class='who'>{_t(item.get('key'))}</td><td>{_t(item.get('fact'))}</td>"
            f"<td>{_t(item.get('source_message_id'))}</td></tr>"
            for item in memory
        )
        memory_block = ("<table><thead><tr><th>Key</th><th>Fact</th><th>Source</th>"
                        "</tr></thead><tbody>" + mem_rows + "</tbody></table>")
    else:
        memory_block = "<p class='empty'>No group memory facts stored.</p>"

    turn = data.get("turn") or {}
    if turn.get("available"):
        turn_block = "<dl>" + _rows([
            ("Active", "yes" if turn.get("active") else "no"),
            ("Opened by", turn.get("opened_by_message_id")),
            ("Last relevant", turn.get("last_relevant_at")),
            ("Closed", "yes" if turn.get("closed") else "no"),
            ("Replies this minute", turn.get("replies_in_window")),
        ]) + "</dl>"
    else:
        turn_block = "<p class='empty'>Turn tracking is not attached to this service.</p>"

    outbound = data.get("outbound") or []
    if outbound:
        out_rows = "".join(
            f"<tr><td>{_t(item.get('kind'))}</td><td>{_t(item.get('status'))}</td>"
            f"<td>{_t(item.get('text'))}</td></tr>"
            for item in outbound
        )
        outbound_block = ("<table><thead><tr><th>Kind</th><th>Status</th><th>Text</th>"
                          "</tr></thead><tbody>" + out_rows + "</tbody></table>")
    else:
        outbound_block = "<p class='empty'>No outbound Rally replies queued or sent.</p>"

    identity = data.get("identity") or {}
    identity_pairs = [
        ("Allowlisted", "yes" if identity.get("allowlisted") else "no"),
        ("Chat", identity.get("chat_id") or data.get("chat_id")),
        ("Portal title", identity.get("portal_title")),
        ("Portal id", identity.get("portal_public_id")),
        ("Portal theme", identity.get("portal_theme")),
        ("Webhook token", identity.get("webhook_token")),
        ("Admin token", identity.get("admin_token")),
        ("BlueBubbles password", identity.get("bluebubbles_password")),
        ("Reaction transport", (data.get("reactions") or {}).get("transport")),
    ]
    import_state = identity.get("history_import") or {}
    if import_state:
        identity_pairs.append(("History import", import_state.get("status")))
        identity_pairs.append(("Imported messages", import_state.get("imported_count")))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rally · {_t(title)}</title>
<style>{_css()}</style></head>
<body>
<a class="skip-link" href="#main-content">Skip to group operations</a>
<header><div class="mark"><strong>Rally</strong><span>Group desk · local admin · not published</span></div></header>
<main id="main-content">
  <a class="back" href="/admin/groups">All allowlisted groups</a>
  <h1>{_t(title)}</h1>
  <p class="guid">{_t(data.get('chat_id'))}</p>
  <p class="lede">Operational truth for this group. Member archive stays on the public portal.</p>
  {alert}
  <nav class="jump" aria-label="Group operations">
    <a href="#messages">Messages</a><a href="#plan">Plan</a><a href="#proposal">Proposal</a>
    <a href="#memory">Memory</a><a href="#turn">Turn</a><a href="#replies">Replies</a>
    <a href="#processing">Processing</a><a href="#identity">Identity</a>
  </nav>
  <div class="stack">
    <section id="messages"><h2>Messages Rally sees</h2>{message_block}</section>
    <section id="plan"><h2>Plan</h2>{plan_block}</section>
    <section id="proposal"><h2>Proposal</h2>{''.join(proposal_parts)}</section>
    <section id="memory"><h2>Group memory</h2>{memory_block}</section>
    <section id="turn"><h2>Turn</h2>{turn_block}</section>
    <section id="replies"><h2>Replies</h2>{outbound_block}</section>
    <section id="processing" class="{'issue' if pending else ''}">
      <h2>Processing</h2>
      <p>{pending} unprocessed human messages.</p>
      <table><thead><tr><th>Stage</th><th>Kind</th><th>Status</th><th>Count</th></tr></thead>
      <tbody>{fail_rows}</tbody></table>
    </section>
    <section id="identity"><h2>Identity</h2><dl>{_rows(identity_pairs)}</dl></section>
  </div>
</main></body></html>"""
