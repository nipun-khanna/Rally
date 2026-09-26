## 1. THE REALITY CHECK

Rally currently demonstrates a Mac-hosted iMessage group coordinator: evidence-validated facts become a durable plan, stalled plans get venue proposals, and explicit approval produces a labeled simulated reservation (`app/agent.py`, `app/orchestrator.py`, `app/store.py`). Its strongest technical artifact is the versioned, approval-gated state machine with persistent outbox, stale-proposal invalidation, and idempotent actions. The offline smoke scenario works with fixed agents and venues, but bypasses real extraction; documentation records live addressed replies and portal publishing, not a verified live venue-to-reservation loop. Calendar, alternate Muse extraction, archive analytics, and private relationship reminders split the story; the separate sender topology and adaptive tool generation remain unfinished.

## 2. THE SCALPEL — CUT 50%

KEEP: group constraints → stalled decision → compatible venue → explicit approval → same-thread simulated confirmation. Keep SQLite, evidence validation, cuisine filtering, stale approvals, and delivery deduplication because these support a credible demonstration. Use the authenticated plan desk as the single companion screen.

CUT from this sprint and presentation, without deleting working modules:
- Relationship reminders and dual macOS account setup (`app/relationships/`): different use case; native permissions and sender identity debugging buy no group-planning payoff.
- Full historical import, media, reactions, analytics, link rotation, and portal settings: a separate archive product; pagination, attachments, deployment, and privacy troubleshooting dilute the three-minute story.
- Google Calendar OAuth (`app/calendar.py`): another credential chain for an outcome already visible in the chat.
- Muse switching (`app/muse.py`): a second extractor adds validation and latency uncertainty, while decisions still depend on Grok. Reconsider only for a supplied track requirement.
- Adaptive capability/code generation (`tasks/todo.md`): planned, not implemented; tool registration and installation safety are a new system.
- Automatic Vercel refresh during the demo: five-minute static snapshots cannot show immediate state transitions.

FAKE / HARD-CODE: use RALLY_DEMO_MODE=1 plus RALLY_DEMO_VENUES=1 for the already labeled Midtown venue fixture. Keep reservation simulation explicitly labeled. Preload a consented or synthetic four-person transcript and fixed upcoming date. Prepare a separately labeled offline browser replay with fixed facts, a rejected sushi candidate, and real orchestration; never call replay output live AI or real delivery. Keep one pre-opened group and plan desk; disable history publishing and Calendar in an isolated rehearsal configuration.

## 3. THE HOOK — ONE SENTENCE

Friends discuss dinner in iMessage → Rally turns their messages into constraints and resolves the stalled venue choice → one approval produces a concrete group plan and a simulated reservation confirmation.

## 4. THE GAP — WHAT JUDGES WILL ATTACK

Primary vulnerability: “Is this more than a chat model suggesting a restaurant?” The hard engineering is largely invisible: source evidence is currently shown as IDs, and the smoke script seeds facts rather than demonstrating extraction. Cheapest patch: resolve cited message IDs to escaped sender/text quotes in `app/debug_view.py`, pass same-chat messages from `/debug` in `app/main.py`, and show the proposal beside the after-7 and no-sushi constraints. Add a sushi candidate to the offline scenario so the existing deterministic filter demonstrably rejects it. This exposes persisted, source-backed state and backend enforcement without inventing a new agent architecture. It does not prove model accuracy; rehearse the exact live extraction separately.

## 5. THE WINNING DEMO

1. 0:00–0:20: show a pre-opened four-person iMessage conversation: specific upcoming dinner date, no sushi, after 7, Midtown. The local plan desk is already open beside it.
2. 0:20–0:50: add the final planning message; display extracted people, date, restrictions, blocker, and quoted source messages. Keep live Grok extraction if rehearsed; explicitly switch to the offline replay if unavailable.
3. 0:50–1:25: after a staged idle interval, the existing scheduler or authenticated demo evaluation proposes the Italian venue at 8 PM. Use a one-minute stall and five-second tick for live staging; the manual trigger does not bypass eligibility.
4. 1:25–2:05: point to “after 7” becoming 8 PM and the excluded sushi restriction; show proposal state READY, with no reservation yet. Magic moment: unstructured group messages visibly become one compatible, actionable proposal with traceable constraints.
5. 2:05–2:40: reply “Book it.” Show one same-thread DEMO reservation confirmation and DONE on the refreshed plan desk. Explain simulated booking in one sentence. End before three minutes; no portal navigation, OAuth, or account setup.

## 6. THE 3-STEP SPRINT

Hours, team size, tracks, and demo length were placeholders. Allocate the available time 50% / 30% / 20%; do not claim a track match until criteria are supplied.

1. Reliability (50%). Objective: reproducible proposal→approval→DONE. Restore pinned runtime and pytest; rehearse one allowlisted group, check upcoming date and eligible state; retain uncertain-delivery quarantine; prepare fresh isolated replay state. Files: `scripts/demo_smoke.py`, `docs/demo.md`, `app/config.py`, service tests. Do not work on sender topology, deployment, or Calendar. Done: repeated fresh runs yield two messages and exactly one reservation; real transport is separately rehearsed or replay is chosen explicitly.
2. Differentiator (30%). Objective: visible source-backed coordination. Resolve quotes in `/debug`, show constraints beside proposal, include a rejected cuisine candidate in replay, and verify escaped text and group isolation. Files: `app/debug_view.py`, `app/main.py`, `tests/test_debug_view.py`, `tests/test_http.py`. Do not build new autonomous tools or switch models. Done: a judge can connect source text to constraints and understand why execution waits for approval.
3. Polish (20%). Objective: finish within three minutes with no setup clicks. State the exact accepted approval phrase; export labeled blocked/ready/done snapshots; document the fallback and manually refresh the local desk. Files: `app/orchestrator.py`, `scripts/demo_smoke.py`, `docs/demo.md`. Do not redesign the portal or add analytics. Done: two timed rehearsals finish under three minutes with legible screens and honest labels.

## 7. ENGINEERING TRIAGE

- MUST FIX — missing runtime dependencies. The documented .venv command initially failed imports. Install requirements plus pytest; use pytest because unittest discovery misses pytest function tests.
- HARD-CODE — Geoapify key, quota, geocoding, and venue nondeterminism. Use the existing explicitly labeled Midtown fixture; keep geography consistent.
- MUST FIX — model and transport rehearsal. Extraction takes one model request per human message; intervention takes two more. Calls run under a global RLock, so slow requests block other groups. Use one group, pre-stage, bound the demo waiting time, and switch explicitly to offline replay; avoid a concurrency rewrite.
- HARD-CODE — LLM output during offline fallback. Use evidence-tagged synthetic facts; do not synthesize unknown live facts after an API failure.
- MUST FIX — exact approval discoverability. Backend accepts “Book it,” but default proposal only asks whether it should reserve. Print the literal command.
- MUST FIX — Mac/BlueBubbles permissions, wake state, authentication, allowlist, and sender identity. Health only checks that the app responds; it does not test providers. Rehearse on the actual Mac without sending unsolicited messages during auditing.
- MUST FIX — database/version/idle prerequisites. Old DONE or READY state and unchanged material facts affect intervention. Use separate rehearsal storage; never delete real state. Stall age tracks material planning changes, intentionally not every chat message (`tests/test_core.py`).
- HARD-CODE — static hosting delay. Present local /debug and labeled exported replay; hosted portal refreshes about every five minutes.
- IGNORE — Calendar, relationship learning, archive/media syncing, alternate extractor, future tool generation, production scaling. Existing modules can remain; keep them off the stage.
- MUST FIX operationally — uncertain sends and transient failures. Preserve quarantine; inspect the thread before any retry. Venue failures or WAIT mark the current version intervened; use the replay instead of repeatedly pressing evaluate expecting recovery.
- IGNORE — broad refactors and speculative edge cases. No inspected TODO stub is required for the selected loop; missing adaptive-request scope is documented as future work.

## 8. NEXT CODE CHANGES

Changes 1–4 below were implemented after this review. Verification: 155 pytest tests
and 12 subtests passed; offline replay reached DONE with two outgoing messages and
one simulated reservation. Source escaping/group isolation, explicit approval, and
exported stages have regression coverage. Independent code review found no
substantive regressions. Local HTTP and stage links were checked; no browser was
connected for visual QA. Live providers were not exercised.

1. `app/debug_view.py` + `app/main.py`: resolve evidence IDs to escaped same-chat source quotes, with an explicit unavailable label. Makes reasoning inspectable. P0.
2. `app/orchestrator.py`: default proposal says “Reply 'Book it' for the demo reservation.” Prevents an on-stage approval dead end. P0.
3. `scripts/demo_smoke.py`: export labeled blocked/ready/done HTML from the existing renderer, evidence-tagged fixture facts, upcoming date, and competing sushi venue. Gives a deterministic browser fallback while exercising actual filtering and approval. P0.
4. `docs/demo.md` + `README.md`: document replay output and use pytest for the full mixed test suite. Prevents misleading test coverage and operator confusion. P1.
5. `app/main.py` periodic scheduler: isolate individual plan/provider failures so one broken plan cannot starve another; add a two-plan regression test before changing it. Useful reliability improvement after rehearsal, beyond the immediate one-group patch. P1.
