"""Read-only, server-rendered view of a persisted Rally plan."""

from html import escape

from app.models import Plan, Proposal, Reservation


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
                      reservation: Reservation | None) -> str:
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

    evidence = "".join(
        f"<li><span>{_text(signal)}</span><code>{_text(', '.join(map(str, ids)))}</code></li>"
        for signal, ids in sorted(facts.evidence.items())
    ) or "<li class='empty'>No message references recorded yet.</li>"

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
  :root {{ color-scheme: light; --ink:#172b46; --muted:#597089; --line:#cad5df; --paper:#f7fafc; --white:#fff; --blue:#2258cf; --pale:#e7efff; --orange:#b3541f; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 "Avenir Next", "Segoe UI", sans-serif; }}
  header {{ background:#123365; color:#fff; padding:1.3rem max(1.3rem, calc((100vw - 1120px)/2)); display:flex; align-items:center; gap:1.2rem; }}
  .brand {{ font-size:1.55rem; font-weight:800; letter-spacing:-.06em; line-height:1; }}
  .head-note {{ border-left:1px solid #7192ba; padding-left:1.2rem; color:#d8e8ff; font-size:.9rem; }}
  main {{ width:min(1120px, calc(100% - 2.6rem)); margin:3rem auto 5rem; }}
  h1 {{ font-size:clamp(2.2rem, 5vw, 4.7rem); letter-spacing:-.065em; line-height:1.05; margin:0 0 1rem; max-width:13ch; overflow-wrap:anywhere; }}
  h2 {{ font-size:1.12rem; letter-spacing:-.02em; margin:0 0 1rem; }}
  p {{ margin:.3rem 0; }}
  .lede {{ max-width:64ch; color:var(--muted); font-size:1.07rem; }}
  .status {{ display:inline-block; background:var(--pale); color:#194ca8; border-left:4px solid var(--blue); padding:.42rem .8rem; font-weight:800; font-size:.85rem; letter-spacing:.02em; overflow-wrap:anywhere; }}
  .topline {{ display:flex; align-items:flex-start; justify-content:space-between; gap:1.5rem; margin-bottom:3.2rem; }}
  .meta {{ color:var(--muted); font-size:.83rem; overflow-wrap:anywhere; margin-top:1rem; }}
  .grid {{ display:grid; grid-template-columns:minmax(240px, .8fr) minmax(0, 1.7fr); gap:3.5rem; }}
  .stage-wrap {{ border-top:3px solid var(--ink); padding-top:1.15rem; }}
  .stages {{ list-style:none; padding:0; margin:1.4rem 0 2rem; border-left:2px solid var(--line); }}
  .stages li {{ position:relative; padding:.45rem 0 .45rem 1.4rem; color:#73869a; font-weight:600; }}
  .stages li::before {{ content:""; position:absolute; left:-6px; top:1.04rem; height:10px; width:10px; border-radius:50%; background:var(--line); }}
  .stages .passed {{ color:var(--ink); }}
  .stages .passed::before {{ background:var(--blue); }}
  .stages .current {{ color:var(--blue); font-weight:800; font-size:1.08rem; }}
  .stages .current::before {{ left:-8px; width:14px; height:14px; top:.93rem; background:var(--blue); box-shadow:0 0 0 4px var(--pale); }}
  .next {{ background:var(--white); border:1px solid var(--line); padding:1.1rem 1.2rem; }}
  .next span {{ display:block; color:var(--muted); font-size:.84rem; }}
  .next strong {{ display:block; margin-top:.2rem; font-size:1.1rem; }}
  .section {{ border-top:1px solid var(--line); padding:1.35rem 0 1.6rem; }}
  .section:first-child {{ border-top:3px solid var(--ink); }}
  .section-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:1rem; }}
  .confidence {{ color:var(--muted); white-space:nowrap; font-size:.88rem; }}
  .confidence strong {{ color:var(--ink); font-size:1.1rem; }}
  .signals {{ list-style:none; padding:0; margin:.3rem 0 0; display:grid; grid-template-columns:1fr 1fr; column-gap:1.5rem; }}
  .signals li {{ display:flex; gap:.6rem; padding:.55rem 0; border-bottom:1px solid #e0e7ed; overflow-wrap:anywhere; }}
  .signals strong {{ color:var(--muted); display:block; font-size:.77rem; font-weight:600; }}
  .signal-mark {{ color:var(--blue); font-weight:800; }}
  .blockers {{ padding-left:1.2rem; margin:.3rem 0; }}
  .blockers li {{ margin:.4rem 0; }}
  .evidence {{ list-style:none; padding:0; margin:.3rem 0 0; }}
  .evidence li {{ display:flex; justify-content:space-between; gap:1rem; border-bottom:1px solid #e0e7ed; padding:.4rem 0; overflow-wrap:anywhere; }}
  code {{ color:var(--muted); font-size:.82rem; overflow-wrap:anywhere; }}
  .venue {{ display:flex; flex-direction:column; gap:.1rem; margin:.3rem 0 1rem; }}
  .venue strong {{ font-size:1.27rem; }}
  .venue span, .empty {{ color:var(--muted); }}
  .details {{ margin:0; }}
  .details div {{ display:flex; justify-content:space-between; gap:1rem; border-bottom:1px solid #e0e7ed; padding:.4rem 0; }}
  .details dt {{ color:var(--muted); }}
  .details dd {{ margin:0; text-align:right; overflow-wrap:anywhere; }}
  @media (max-width: 760px) {{ main {{ margin-top:2rem; }} .grid {{ grid-template-columns:1fr; gap:2rem; }} .topline {{ flex-direction:column-reverse; gap:.8rem; }} .stages {{ display:grid; grid-template-columns:1fr 1fr; column-gap:1.4rem; }} }}
  @media (max-width: 480px) {{ .signals {{ grid-template-columns:1fr; }} .head-note {{ font-size:.78rem; }} .evidence li {{ flex-direction:column; gap:0; }} }}
</style></head><body>
<header><span class="brand">Rally</span><span class="head-note">Group plan desk</span></header>
<main>
  <div class="topline"><div><h1>{_text(title)}</h1><p class="lede">What the conversation says, where the plan stands, and what Rally will do next.</p>
  <p class="meta">Chat {_text(plan.chat_id)} · Plan version {_text(plan.version)} · Last group activity {_text(plan.last_human_at.isoformat())}</p></div><span class="status">{_text(state)}</span></div>
  <div class="grid"><aside class="stage-wrap" aria-label="Plan progress"><h2>Plan progress</h2><ol class="stages">{stages}</ol>
    <div class="next"><span>Next action</span><strong>{_text(next_action)}</strong></div></aside>
  <div class="content">
    <section class="section"><div class="section-head"><h2>Conversation signals</h2><span class="confidence">Confidence <strong>{confidence:.0%}</strong></span></div><ul class="signals">{''.join(signals)}</ul></section>
    <section class="section"><h2>Current blocker</h2><ul class="blockers">{blockers}</ul></section>
    <section class="section"><h2>Message evidence</h2><ul class="evidence">{evidence}</ul></section>
    <section class="section"><h2>Proposal</h2>{proposal_view}</section>
    <section class="section"><h2>Latest reservation result</h2>{result_view}</section>
  </div></div>
</main></body></html>"""
