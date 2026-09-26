# Rally MVP implementation tasks

> **For agentic workers:** Implement tasks in order. Read [SPEC.md](../SPEC.md) and [PRD.md](../PRD.md) first; use the checkboxes to track progress.

**Goal:** Ship the complete iMessage dinner demo in under two minutes, including one automatic intervention after a plan stalls.

**Architecture:** One FastAPI backend owns persistent plan state, Grok decisions, scheduling, approval checks, and tool execution. BlueBubbles and Geoapify are adapters. SQLite persists plans and action results across restarts.

**Tech stack:** Python, FastAPI, SQLite, Grok, BlueBubbles, Geoapify, and server-rendered HTML for the debug view. Exact dependency versions are selected during Task 1.

**Spec:** [SPEC.md](../SPEC.md).

## Global constraints

- Automatic intervention is required for the MVP. The default stall threshold is 30 minutes and must be configurable for the demo.
- Keep plan records across restarts; do not build personal profiles or automatic cross-chat memory.
- LLM usage may be paid. All other external APIs must have a usable free path; stop at provider limits rather than silently incurring charges.
- No reservation or other commitment without explicit approval of the current concrete proposal.
- Never claim that venue search proves reservation availability. Label mock bookings as demo reservations.
- Keep BlueBubbles integration thin, and return all replies to the originating chat.

## Proposed file map

This is the planned structure for a currently documentation-only repository; adjust names only when a concrete framework constraint requires it.

| Path | Responsibility |
|---|---|
| `app/main.py`, `app/config.py` | FastAPI entry point, configuration, lifecycle. |
| `app/models.py`, `app/store.py` | Shared schemas and SQLite persistence. |
| `app/bluebubbles.py` | Incoming event normalization and outgoing messages. |
| `app/extraction.py`, `app/agent.py` | Grok structured extraction and action decisions. |
| `app/policy.py`, `app/scheduler.py` | State transitions, safety checks, and inactivity evaluation. |
| `app/places.py`, `app/reservations.py` | Free-tier venue lookup and local mock reservation. |
| `app/orchestrator.py` | Connect messages, state, decisions, tools, and outbound reports. |
| `app/debug.py`, `app/templates/debug.html` | Read-only plan interpretation view. |
| `scripts/seed_demo.py`, `docs/demo.md` | Reproducible scenario and operator script. |
| `tests/` | Focused contract, policy, integration, and demo-path checks. |

## P0 implementation sequence

### 1. Bootstrap and provider preflight

- [ ] Create the FastAPI app, dependency lock, `.env.example`, and setup instructions in `README.md` for BlueBubbles, Grok, and Geoapify.
- [ ] Keep API keys and chat configuration in environment variables, outside fixtures and logs.
- [ ] Check the BlueBubbles server and webhook connection, Grok structured output call, and Geoapify free-tier account. Record unavailable credentials as setup prerequisites.
- [ ] Verify the server starts and reports health; confirm the non-LLM path has no paid provider dependency.

### 2. Define schemas and durable storage

**Depends on:** 1. **Delivers:** `ChatMessage`, `Plan`, `Proposal`, `Approval`, reservation result, and outbound-message records.

- [ ] Define the fields and enums from `SPEC.md`, including message IDs, chat and sender IDs, evidence IDs, plan state, plan version, and proposal terms.
- [ ] Create SQLite tables with unique constraints for incoming message ID and reservation proposal ID. Store intervention and delivery status.
- [ ] Add operations to record a message once, load recent chat context, update the active plan, and record a booking once.
- [ ] Verify duplicate messages are ignored, chats stay isolated, and plans and action results survive restart.

### 3. Receive and send group messages

**Depends on:** 2. **Delivers:** normalized incoming messages and same-thread outgoing replies.

- [ ] Implement the BlueBubbles webhook endpoint and normalize supported new group-message events into `ChatMessage`.
- [ ] Ignore Rally's own messages, empty or unsupported events, and duplicate message IDs. Persist accepted messages before processing.
- [ ] Implement `send_message(chat_id, text)` through BlueBubbles; persist attempted, sent, and failed delivery state.
- [ ] Verify a group message is recorded once and a response goes to its original thread; test a delivery failure without losing the queued response.

### 4. Extract conversation facts with Grok

**Depends on:** 2–3. **Delivers:** evidence-backed activity, interest, availability, preferences, objections, and unresolved decisions.

- [ ] Define a strict extraction schema and prompt over recent messages plus current plan. Link facts to source message IDs.
- [ ] Resolve relative dates against message timestamps and the configured chat time zone; represent unresolved city, party size, and date explicitly.
- [ ] Reject malformed or contradictory model output before it changes persisted state.
- [ ] Verify the PRD dinner example, “after 7” versus 7:00, “no sushi” as a restriction, and “Midtown preferred” as a preference.

### 5. Apply plan state and safety policy

**Depends on:** 4. **Delivers:** deterministic state transitions and eligibility checks for live messages and scheduler ticks.

- [ ] Implement eight states and five decisions in `SPEC.md`, with `WAIT` as the default.
- [ ] Derive state from chat evidence or tool results, and invalidate pending proposals when venue, date, time, party size, or constraints change.
- [ ] Verify unrelated chatter stays silent, conflict triggers a targeted question, cancellation stops intervention, and failed tools cannot produce `DONE`.

### 6. Search for a viable venue

**Depends on:** 4–5. **Delivers:** normalized venue candidates with source IDs and location details.

- [ ] Implement Geoapify Places search with bounded result counts, provider attribution, free-tier limits, and clear error results.
- [ ] Filter against known restrictions, rank preferences, and keep incomplete provider facts marked unknown.
- [ ] Add a fixed, clearly labeled venue fixture used only in demo mode.
- [ ] Verify missing location or empty search leads to clarification or truthful failure; do not claim table availability from place search.

### 7. Generate decisions and concrete proposals

**Depends on:** 4–6. **Delivers:** a structured Grok decision and one persisted proposal when warranted.

- [ ] Give Grok recent messages, structured state, available tools, and previous results; validate the returned action and confidence.
- [ ] Let the backend approve `search_places`, select a viable venue, and create a proposal with exact venue, date, time, party size, and version.
- [ ] Send a concise recommendation and ask whether to book the demo reservation.
- [ ] Verify vague input yields `WAIT` or `ASK`, a viable venue yields a concrete proposal, and the same plan version does not generate duplicates.

### 8. Schedule automatic intervention

**Depends on:** 5–7. **Delivers:** one useful intervention for an eligible quiet plan.

- [ ] Add a periodic job over persisted active plans and last human activity, with a configurable 30-minute threshold.
- [ ] Require two interested people, a blocker, enough context, and no prior unsolicited intervention for that plan version.
- [ ] Route scheduler and manual demo trigger through the same orchestration function and safety checks.
- [ ] Verify one intervention after the threshold, none before it, and none repeated after restart or another scheduler tick.

### 9. Validate approval

**Depends on:** 3, 5, 7. **Delivers:** an `Approval` tied to the current proposal.

- [ ] Accept clear affirmative instructions from a human in the originating chat only while exactly one current proposal is pending.
- [ ] Record approving message and proposal ID before any reservation attempt; reject vague interest, other-chat messages, and stale terms.
- [ ] Verify “I’m down” does not book, “Book it” approves the current proposal, and replayed approval creates no extra action.

### 10. Execute the mock reservation and report

**Depends on:** 9. **Delivers:** one stable demo confirmation and a truthful final iMessage message.

- [ ] Make `create_reservation(proposal_id)` idempotent in local storage and return a stable confirmation ID with exact approved terms.
- [ ] Move through `EXECUTING` to `DONE` only after a successful mock result and a sent final report.
- [ ] Send a message labeled demo reservation with venue, date, time, party size, and confirmation ID.
- [ ] Verify failed or uncertain results stay unresolved; retrying message delivery cannot rebook; duplicate approvals preserve one confirmation.

### 11. Show the debug interpretation

**Depends on:** 2, 5, 7–10. **Delivers:** a lightweight read-only demo view.

- [ ] Render goal, interested people, signals, plan state, blocker, next action, confidence, proposal, and latest tool result from persisted state.
- [ ] Keep secrets and unrelated chats out of the demo view.
- [ ] Verify the view shows the same state that drove the iMessage proposal and updates after approval and tool completion.

### 12. Prepare and prove the end-to-end demo

**Depends on:** 1–11. **Delivers:** a repeatable under-two-minute walkthrough.

- [ ] Seed the PRD dinner conversation with explicit sender identities, date context, time zone, and four interested people.
- [ ] Document BlueBubbles setup, venue fixture mode, scheduler threshold, demo steps, and reset procedure in `docs/demo.md`.
- [ ] Run: quiet chat → automatic intervention → proposal → “Book it” → one mock reservation → completed message in the same iMessage thread.
- [ ] Record elapsed time and check the debug view. Check no approval, changed terms, duplicate webhook, conflicting preference, venue-search failure, and reservation failure.

## P1 after the MVP works

- [ ] Calendar: create a real event only when approval covers that action; report calendar and reservation outcomes separately and use a free API path within quotas.
- [ ] Meta/Muse: evaluate social-context extraction only if it improves fact accuracy; keep Grok responsible for agent decisions.
- [ ] Dashboard polish: improve presentation after the lightweight view is correct.
- [ ] Real reservation provider: assess when a genuine free integration and actual booking workflow are available; preserve the same approval contract.

## Review focus

- A repeated webhook must leave a single message record, proposal, intervention, and booking where applicable.
- A changed date, time, venue, or party size must invalidate old approval.
- Missing location, provider outage, or conflicting preference must not become an invented recommendation.
- A failed or uncertain reservation result must not be reported as completed.
- A quiet plan must produce one useful intervention and stay quiet on later scheduler ticks until material new input arrives.

## Documentation review

- [x] Compared P0 and P1 items with the PRD and the user's later scope choices.
- [x] Traced every MVP acceptance criterion in `SPEC.md` to a task above.
- [x] Kept paid LLM access separate from the free non-LLM API requirement.
- [x] Defined automatic intervention, persistent plan records, proposal-bound approval, and truthful mock booking behavior.

Implementation has not started. Implementation checkboxes remain open.
