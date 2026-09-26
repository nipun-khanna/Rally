"""Read-only, server-rendered view of a persisted Rally plan."""

from html import escape

from app.models import ChatMessage, Plan, Proposal, Reservation


STAGES = ("SPARK", "INTEREST", "ALIGNMENT", "BLOCKED", "READY", "EXECUTING", "DONE")
NEXT_ACTION = {
    "SPARK": "Wait for more interest",
    "INTEREST": "Wait for a time or place",
    "ALIGNMENT": "Watch for a decision to make",
    "BLOCKED": "Find the smallest next step",
    "READY": "Wait for approval",
    "EXECUTING": "Report the reservation",
    "DONE": "No further action",
    "ABANDONED": "Stop intervening",
}


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _item(label: str, value: object) -> str:
    return f"<li><span class='signal-mark' aria-hidden='true'>✓</span><span><strong>{_text(label)}</strong>{_text(value)}</span></li>"


def render_debug_view(plan: Plan, proposal: Proposal | None,
                      reservation: Reservation | None, *,
                      messages: list[ChatMessage] | None = None) -> str:
    """Render only the supplied plan's stored facts and latest outcomes."""
    facts = plan.facts
    title = facts.goal or facts.activity or "Plan in progress"
    state = plan.state
    next_action = NEXT_ACTION.get(state, "Wait")
    if state == "BLOCKED":
        if not facts.location:
            next_action = "Ask for the city or area"
        elif not facts.date:
            next_action = "Ask for the date"
        elif any("venue" in blocker.lower() or "restaurant" in blocker.lower()
                 for blocker in facts.blockers):
            next_action = "Propose a venue"
    stage_index = STAGES.index(state) if state in STAGES else -1
    stages = "".join(
        f"<li class='{'current' if item == state else 'passed' if stage_index > i else ''}'"
        f"{' aria-current=\"step\"' if item == state else ''}>{item.title()}</li>"
        for i, item in enumerate(STAGES)
    )
    if state == "ABANDONED":
        stages += "<li class='current' aria-current='step'>Abandoned</li>"

    signals: list[str] = []
    party_size = getattr(facts, "party_size", None)
    if isinstance(party_size, int) and not isinstance(party_size, bool) and party_size > 0:
        signals.append(_item("People", f"Party of {party_size}"))
    elif facts.participants:
        signals.append(_item("People", f"{len(set(facts.participants))} people interested"))
    if facts.date:
        signals.append(_item("Date", facts.date))
    if facts.time:
        signals.append(_item("Time", facts.time))
    elif facts.earliest_time:
        signals.append(_item("Time", f"After {facts.earliest_time}"))
    if facts.location:
        signals.append(_item("Place", facts.location))
    for cuisine in facts.excluded_cuisines:
        signals.append(_item("Avoid", cuisine))
    for cuisine in facts.preferred_cuisines:
        signals.append(_item("Prefer", cuisine))
    for objection in facts.objections:
        signals.append(_item("Objection", objection))
    if not signals:
        signals.append("<li class='empty'>No planning signals recorded yet.</li>")

    sources = {m.message_id: m for m in messages or []
               if m.chat_id == plan.chat_id and not m.is_from_rally}
    evidence_items = []
    for signal, ids in sorted(facts.evidence.items()):
        quotes = []
        for message_id in ids:
            source = sources.get(message_id)
            quote = (f"<strong>{_text(source.sender_id)}</strong>: {_text(source.text)}"
                     if source else "Source message unavailable")
            quotes.append(f"<blockquote>{quote}<br><code>{_text(message_id)}</code></blockquote>")
        evidence_items.append(f"<li><span>{_text(signal.replace('_', ' '))}</span>"
                              f"<div>{''.join(quotes)}</div></li>")
    evidence = "".join(evidence_items) or "<li class='empty'>No message references recorded yet.</li>"

    if proposal:
        proposal_view = (
            "<div class='venue'>"
            f"<strong>{_text(proposal.venue_name)}</strong>"
            f"<span>{_text(proposal.venue_address)}</span>"
            "</div><dl class='details'>"
            f"<div><dt>When</dt><dd>{_text(proposal.date)} at {_text(proposal.time)}</dd></div>"
            f"<div><dt>Party</dt><dd>Party of {_text(proposal.party_size)}</dd></div>"
            f"<div><dt>Status</dt><dd>{_text(proposal.status)}</dd></div>"
            "</dl>"
        )
    else:
        proposal_view = "<p class='empty'>No proposal yet.</p>"

    if reservation:
        result_view = (
            "<dl class='details'>"
            f"<div><dt>Result</dt><dd>{_text(reservation.status)}</dd></div>"
            f"<div><dt>Confirmation</dt><dd>{_text(reservation.confirmation_id)}</dd></div>"
            "</dl>"
        )
    else:
        result_view = "<p class='empty'>No reservation result yet.</p>"

    confidence = max(0, min(1, facts.confidence))
    blockers = "".join(f"<li>{_text(blocker)}</li>" for blocker in facts.blockers)
    if not blockers:
        blockers = "<li class='empty'>No specific blocker recorded.</li>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rally · {_text(title)}</title>
<style>
  :root {{ color-scheme:light; --ink:#1c1c1e; --muted:#63666b; --line:#d9dce1; --canvas:#f2f4f7; --surface:#fff; --blue:#0A84FF; --blue-dark:#0068cf; --blue-wash:#e8f3ff; }}
  * {{ box-sizing:border-box; }}
  html {{ scroll-behavior:smooth; }}
  body {{ margin:0; background:var(--canvas); color:var(--ink); font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  header {{ min-height:64px; background:var(--blue); color:#fff; padding:.9rem max(1rem, calc((100vw - 1120px)/2)); display:flex; align-items:center; gap:1rem; }}
  .brand {{ font-size:1.35rem; font-weight:750; letter-spacing:-.045em; line-height:1; }}
  .head-note {{ border-left:1px solid #83beff; padding-left:1rem; color:#f2f8ff; font-size:.9rem; }}
  .skip-link {{ position:absolute; top:.5rem; left:.5rem; z-index:5; transform:translateY(-180%); padding:.65rem 1rem; border-radius:.6rem; background:#fff; color:var(--blue-dark); font-weight:700; box-shadow:0 2px 12px #003b771f; }}
  .skip-link:focus {{ transform:translateY(0); }}
  :focus-visible {{ outline:3px solid #003f8c; outline-offset:3px; }}
  main {{ width:min(1120px, calc(100% - 2rem)); margin:2.4rem auto 4rem; }}
  h1 {{ font-size:clamp(1.8rem, 4vw, 3rem); letter-spacing:-.045em; line-height:1.12; margin:0 0 .55rem; max-width:24ch; overflow-wrap:anywhere; }}
  h2 {{ font-size:1.08rem; letter-spacing:-.015em; margin:0 0 .9rem; }}
  p {{ margin:.3rem 0; }}
  .lede {{ max-width:64ch; color:var(--muted); font-size:1rem; }}
  .status {{ display:inline-flex; align-items:center; background:#fff; color:#075eb4; border:1px solid #b4d9ff; border-radius:999px; padding:.38rem .75rem; font-weight:700; font-size:.84rem; overflow-wrap:anywhere; }}
  .topline {{ display:flex; align-items:flex-start; justify-content:space-between; gap:1.25rem; margin-bottom:1.2rem; }}
  .meta {{ color:var(--muted); font-size:.82rem; overflow-wrap:anywhere; margin-top:.8rem; }}
  .section-nav {{ display:flex; flex-wrap:wrap; gap:.4rem; padding:.65rem; margin:0 0 1.5rem; background:var(--surface); border:1px solid var(--line); border-radius:.9rem; }}
  .section-nav a {{ color:#075eb4; border-radius:999px; padding:.35rem .7rem; font-size:.87rem; font-weight:600; text-decoration:none; }}
  .section-nav a:hover {{ background:var(--blue-wash); text-decoration:underline; }}
  .grid {{ display:grid; grid-template-columns:minmax(225px, .72fr) minmax(0, 1.8fr); gap:1.2rem; align-items:start; }}
  .stage-wrap {{ position:sticky; top:1rem; padding:1.1rem; background:var(--surface); border:1px solid var(--line); border-radius:1rem; }}
  .stages {{ list-style:none; padding:0; margin:1rem 0 1.25rem; border-left:2px solid var(--line); }}
  .stages li {{ position:relative; padding:.42rem 0 .42rem 1.2rem; color:#777a80; font-weight:550; }}
  .stages li::before {{ content:""; position:absolute; left:-6px; top:.95rem; height:10px; width:10px; border-radius:50%; background:var(--line); }}
  .stages .passed {{ color:var(--ink); }}
  .stages .passed::before {{ background:var(--blue); }}
  .stages .current {{ color:var(--blue-dark); font-weight:750; }}
  .stages .current::before {{ left:-8px; width:14px; height:14px; top:.78rem; background:var(--blue); box-shadow:0 0 0 4px var(--blue-wash); }}
  .next {{ background:var(--blue-wash); border:1px solid #b9dcff; border-radius:.8rem; padding:.85rem .95rem; }}
  .next span {{ display:block; color:#4f6275; font-size:.8rem; }}
  .next strong {{ display:block; margin-top:.2rem; color:#064d91; font-size:1rem; }}
  .content {{ display:grid; gap:.8rem; min-width:0; }}
  .section {{ scroll-margin-top:1rem; padding:1.15rem 1.2rem; background:var(--surface); border:1px solid var(--line); border-radius:.95rem; min-width:0; }}
  .section-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:1rem; }}
  .confidence {{ color:var(--muted); white-space:nowrap; font-size:.84rem; }}
  .confidence strong {{ color:var(--ink); font-size:1rem; }}
  .signals {{ list-style:none; padding:0; margin:.2rem 0 0; display:grid; grid-template-columns:1fr 1fr; column-gap:1.25rem; }}
  .signals li {{ display:flex; gap:.55rem; padding:.48rem 0; border-bottom:1px solid #edf0f3; overflow-wrap:anywhere; }}
  .signals strong {{ color:var(--muted); display:block; font-size:.76rem; font-weight:600; }}
  .signal-mark {{ color:var(--blue-dark); font-weight:800; }}
  .blockers {{ padding-left:1.2rem; margin:.2rem 0; }}
  .blockers li {{ margin:.35rem 0; }}
  .evidence {{ list-style:none; padding:0; margin:.2rem 0 0; }}
  .evidence li {{ display:grid; grid-template-columns:minmax(100px, .5fr) minmax(0, 2fr); gap:.8rem; border-bottom:1px solid #edf0f3; padding:.5rem 0; overflow-wrap:anywhere; }}
  blockquote {{ margin:.15rem 0; padding:.55rem .75rem; border-left:3px solid var(--blue); border-radius:0 .65rem .65rem 0; background:#f2f7fc; }}
  code {{ color:var(--muted); font-size:.8rem; overflow-wrap:anywhere; }}
  .venue {{ display:flex; flex-direction:column; gap:.1rem; margin:.2rem 0 .8rem; }}
  .venue strong {{ font-size:1.16rem; }}
  .venue span, .empty {{ color:var(--muted); }}
  .details {{ margin:0; }}
  .details div {{ display:flex; justify-content:space-between; gap:1rem; border-bottom:1px solid #edf0f3; padding:.45rem 0; }}
  .details dt {{ color:var(--muted); }}
  .details dd {{ margin:0; text-align:right; overflow-wrap:anywhere; }}
  @media (max-width: 760px) {{ main {{ margin-top:1.5rem; }} .grid {{ grid-template-columns:1fr; gap:.8rem; }} .stage-wrap {{ position:static; }} .stages {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); column-gap:1rem; }} .topline {{ gap:.8rem; }} }}
  @media (max-width: 480px) {{ main {{ width:calc(100% - 1rem); margin-top:1rem; }} .signals {{ grid-template-columns:1fr; }} header {{ min-height:56px; }} .head-note {{ font-size:.8rem; }} .topline {{ flex-direction:column-reverse; }} .section-nav {{ gap:.2rem; padding:.45rem; }} .section-nav a {{ font-size:.81rem; padding:.32rem .55rem; }} .section {{ padding:1rem; }} .section-head {{ flex-direction:column; align-items:flex-start; gap:.3rem; }} .section-head h2 {{ min-width:0; overflow-wrap:anywhere; }} .confidence {{ white-space:normal; }} .evidence li {{ grid-template-columns:1fr; gap:.2rem; }} .details div {{ align-items:flex-start; }} }}
  @media (prefers-reduced-motion: reduce) {{ *,*::before,*::after {{ scroll-behavior:auto !important; animation-duration:.01ms !important; animation-iteration-count:1 !important; transition-duration:.01ms !important; }} }}
</style></head><body>
<a class="skip-link" href="#main-content">Skip to plan details</a>
<header><span class="brand">Rally</span><span class="head-note">Group plan desk</span></header>
<main id="main-content">
  <div class="topline"><div><h1>{_text(title)}</h1><p class="lede">What the conversation says, where the plan stands, and what Rally will do next.</p>
  <p class="meta">Chat {_text(plan.chat_id)} · Plan version {_text(plan.version)} · Last group activity {_text(plan.last_human_at.isoformat())}</p></div><span class="status">{_text(state)}</span></div>
  <nav class="section-nav" aria-label="Plan sections">
    <a href="#conversation-signals">Signals</a><a href="#current-blocker">Blocker</a>
    <a href="#message-evidence">Evidence</a><a href="#proposal">Proposal</a><a href="#reservation-result">Result</a>
  </nav>
  <div class="grid"><aside class="stage-wrap" aria-label="Plan progress"><h2>Plan progress</h2><ol class="stages">{stages}</ol>
    <div class="next"><span>Next action</span><strong>{_text(next_action)}</strong></div></aside>
  <div class="content">
    <section class="section" id="conversation-signals"><div class="section-head"><h2>Conversation signals</h2><span class="confidence">Confidence <strong>{confidence:.0%}</strong></span></div><ul class="signals">{''.join(signals)}</ul></section>
    <section class="section" id="current-blocker"><h2>Current blocker</h2><ul class="blockers">{blockers}</ul></section>
    <section class="section" id="message-evidence"><h2>Message evidence</h2><ul class="evidence">{evidence}</ul></section>
    <section class="section" id="proposal"><h2>Proposal</h2>{proposal_view}</section>
    <section class="section" id="reservation-result"><h2>Latest demo reservation result</h2><p class="empty">Simulated booking; no table is reserved with a venue.</p>{result_view}</section>
  </div></div>
</main></body></html>"""
