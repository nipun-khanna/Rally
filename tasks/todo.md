# Rally MVP implementation tasks

## Current teammate handoff — 2026-09-26

The full PRD is **not complete**. No open teammate PRs were present at the last GitHub check. Pick one area below and open a focused branch/PR; include the route and data contract in the PR description. See [team ownership](../docs/team-ownership.md) and [relationship MVP plan](../docs/superpowers/plans/2026-09-26-relationship-mvp.md) for detail. Keep personal relationship data out of the public group portal and Vercel snapshots.

| Priority | Owner | Task | Done when |
| --- | --- | --- | --- |
| 1 | Frontend teammate | **Private relationship dashboard:** attention cards, editable person profiles/categories/intentions, evidence and freshness, draft review, action states. Use local private routes; provide synthetic fixtures for preview. | Overdue person → suggested action → reviewed draft can be demonstrated with clear private authentication and unknown-data states. |
| 1 | Backend teammate | **Local follow-up detection:** extract commitments and unfinished plans from explicitly selected conversations, retain source evidence, and implement dismiss/snooze/done plus edit/delete/disable lifecycle. | Fixture conversation creates a candidate; changing or disabling its source invalidates it without leaking source text to cloud/group portal. |
| 1 | Backend teammate | **Calendar integration:** Google OAuth setup/verification, read-only free/busy, timezone-aware available slots, and version-bound approved event creation. Distinguish owner-only availability from mutual availability. | Connected or labeled fixture calendar produces a slot; edited details invalidate approval; duplicate approval creates at most one event. |
| 2 | Frontend/infra teammate | **Website deployment:** GitHub → Vercel previews and production for website code, using synthetic data in previews and preserving the existing local group-portal publisher. | A PR produces a preview URL and a main push updates the website without publishing Mac SQLite or private relationship data. |
| 2 | Root | **Shared integration:** review teammate contracts/PRs, connect dashboard → follow-up → planning → availability → reviewed draft → approved event, then run the PRD demo. | One connected test and browser demo pass, with live-provider gaps labeled honestly. |
| 2 | Root | **iMessage/planning reliability:** resolve extraction timeouts and the 56 unprocessed group-message backlog without re-sending historical replies; verify live group response and approval safety. | New group messages are processed reliably; backlog recovery does not duplicate sends or silently skip plan changes. |

Teammates should avoid editing `app/main.py`, `app/config.py`, and shared orchestration routes without coordinating interface changes. The dashboard, follow-up, calendar, and deployment areas remain assigned to humans. Root has already built the live BlueBubbles path, group planning foundation, web search, adaptive request registry, and inert code proposals; those are not new teammate tasks.

## Relationship maintenance service

### Two-profile feasibility test

- [x] User approved testing one Mac with personal and Rally macOS profiles.
- [x] Verify macOS 26.0.1, 16 GB RAM, existing BlueBubbles, and administrator membership; noninteractive sudo unavailable.
- [x] Create and verify standard Rally macOS user (`rally`, UID 503); user entered local password.
- [ ] Sign into Rally's separate Apple account in that user's Messages and confirm native send works.
- [ ] Run BlueBubbles in Rally profile on a separate local port with its own password.
- [ ] Switch back while leaving Rally logged in; verify one labeled sender-to-owner message arrives.
- [ ] Record stability and permissions results; decide whether to keep this topology or use a shared sender host.
- [ ] Later: measure and reduce monitoring CPU, memory, and idle work; user explicitly deferred this until after setup.

### Live relationship test on current Messages account

- [ ] Locate or create a self-only iMessage test thread and verify delivery.
- [ ] Exercise setup/status, call/visit/message confirmations, cadence changes, snooze, pause/resume, removal, deduplication, and a due reminder in isolated test state.
- [ ] Verify local learning on an explicitly selected source; keep all other history disabled and no source text transfer to Grok/Vercel.
- [ ] Record actual receipts, failures, cleanup, and remaining sender/provider gaps.

- [ ] Resolve deployment architecture: user's local monitor plus local notifications, or a separate Rally iMessage sender with minimal authenticated relay. Current code uses one BlueBubbles account; it does not yet implement the separate sender topology.

- [x] Inspect current scheduling, persistence, message handling, and archive-disable state.
- [x] Draft relationship-service design with confirmed contact, learning, reminder cycles, and private data isolation.
- [x] Review written design: private Rally conversation and explicitly selected learning conversations approved.
- [x] Write implementation plan covering private persistence, commands, learning, setup, and verification.
- [x] Review implementation plan and confirm native execution approach.
- [x] Implement relationship records and confirmed contact events with durable ownership isolation.
- [x] Implement setup, status, contact confirmation, cadence changes, snooze, pause, resume, and removal.
- [x] Implement reminder scheduling and deduplicated delivery through a configured private destination.
- [x] Implement local selected-conversation learning and evidence-based cadence suggestions requiring acceptance.
- [x] Independent code review; reproduce and fix source re-selection and queued group-delivery privacy races.
- [ ] Configure the user's exact private destination and explicitly selected sources; verify live personal reminder receipt.
- [ ] Verify code tests, restart behavior, and live reminder delivery; commit and push verified changes.

### Relationship verification — 2026-09-26

153 tests pass, including private routing, owner/channel isolation, contact rhythms,
source disable/remove and reconciliation, stale-import rejection, portal exclusion,
local time windows, delivery deduplication, crash recovery, and configuration changes.
Independent review findings were reproduced and fixed. Local `/health` returns
200 after restart. Personal configuration currently has zero destinations and zero
sources; no personal texts were read and no personal iMessage was sent. Live private
delivery remains unverified until the user identifies its destination and selects
learning conversations. Monitoring is local deterministic analysis, not a local LLM;
selected source texts are excluded from Grok and portal exports.

## Finish remaining functionality — current iMessage account

- [ ] Audit the PRD and existing adapters; preserve completed behavior and identify implementation gaps.
- [ ] Finish and publish the pending portal analytics change, with its tests and structured commit.
- [ ] Prepare provider setup and credential validation for live venue search and Google Calendar.
- [ ] Run the complete live planning loop in the authorized group when venue credentials are available; record timing and outcomes.
- [ ] Design adaptive requests: registered tools, persistent workflows, missing-capability tracking, explicit approval for commitments, and honest failure reporting.
- [ ] Generate proposed code for missing capabilities, persist it as a review artifact with intended behavior and validation results, and keep execution or installation pending review.
- [ ] Implement the reviewed adaptive-request design and verify same-chat routing, durable state, and tool approval boundaries.
- [ ] Commit and push verified changes; update the hosted portal as needed.

## Proposed group websites — full history requirement

- [x] Wire a portal for each allowlisted group into the existing FastAPI service at `/{group_id}`.
- [x] Expose a safe admin setup path and same-chat Rally link request; keep portal changes scoped to its group.
- [x] Design a private website for each group with member names, historical messages, plans and Rally actions, and group analytics.
- [x] Import the group's complete available iMessage history before Rally joined, in resumable pages with deduplication; keep syncing new messages afterward.
- [x] Show import coverage and completion status so partial history does not appear complete.
- [x] Show only Rally-tracked plans by default; let members request a search for older plans in imported messages and clearly label any inferred result as historical.
- [x] Serve the portal at `{app_url}/{group_id}` with a random, replaceable public group ID; anyone holding the link can open it. Vercel cache and past deployment retention limit complete revocation.
- [x] Import available historical photos, videos, and other attachments as part of full chat history; show missing media clearly.
- [x] Add group-level controls to hide or show the message archive, media, analytics, plans, activity, and member list.
- [x] Give the portal an iMessage-inspired visual design, especially for the message timeline, with responsive layout and readable plans and analytics.
- [x] Define how group members request and authorize portal configuration changes through explicit Rally commands in the allowlisted chat.
- [x] Verify the archive import, media delivery, history search, analytics, settings, and portal rendering using tests and a local running app.
- [x] Organize implementation into sequential commits and push to the configured private GitHub remote.
- [x] Use the Vercel CLI to create the user-selected `rallyplans` project and assign `rallyplans.vercel.app` with a data-free holding page; verify the production alias returns 200.
- [x] Publish the actual group portal to that domain after explicit approval to upload the group's archived messages and media to Vercel.

### Portal review — 2026-09-26

The selected group import completed with 72 source messages and six available attachments; two participant names resolved from local Contacts. The live FastAPI page, a media endpoint, and the local historical-plan lookup returned 200. A labeled `Hey Rally, send our page link` test sent one prompt and received one same-thread URL reply; the published Vercel page then reflected that exchange. Vercel's production alias returned 200 for the group page, history index, and media; active attachment formats are download-only with restrictive headers. Historical-plan lookup uses local text matching and does not send archived messages to xAI. An automatic approval review rejected that proposed xAI archive call because external transfer of private history had not been specifically authorized; the local search replaced it. Vercel publication of the archive was later explicitly approved. The site is a static snapshot refreshed by the running Mac service about every five minutes; immutable deployments and caches mean old published data cannot be guaranteed erased instantly.

Portal commits `f0a88d3`, `48946af`, and `5b3ad2a` were pushed to the verified private `nipun-khanna/Rally` remote. The final webhook-facing service is running on port 8770, with health returning 200 and access logs disabled. The current Vercel production alias serves the final portal; obsolete Vercel deployments created during setup were removed.

## Future idea — adaptable requests

- [ ] Explore the user's idea that Rally should figure out how to fulfill new requests. Define its allowed tools, approval boundaries, and whether this means planning with existing capabilities or adding new capabilities. Keep this outside the current direct-address implementation.

## Direct Rally address and Grok setup — 2026-09-26

- [x] Add a narrow, case-insensitive plain-text address check for new human group messages; ignore incidental mentions and Rally's own replies.
- [x] Generate a short context-aware reply through Grok when directly addressed; preserve the PRD's explicit approval boundary for actions.
- [x] Persist and deduplicate direct replies through the existing outbox, and verify same-chat routing and failure behavior.
- [x] Update setup/docs and run focused and full tests.
- [x] Configure the user-supplied xAI API key, verify a model call, and run a live addressed-message test.

### Review

The user supplied an xAI API key, which is stored only in ignored, owner-only `.env`; the xAI Console browser was unavailable, so no account or key was created by the agent. A minimal structured Grok request succeeded. The direct-address path detects explicit calls, answers from group context before extraction, stores its response in the outbox, and does not treat an addressed `book it` request as approval. Current-account human messages are accepted; generated `Rally:` echoes are ignored. Ninety-seven tests and the offline demo passed. In the live Akshit–Nipun group, a labeled `Hey Rally` prompt reached Rally and Grok, one reply was sent in the same thread, and the echo was ignored. The user intends to rotate the pasted key. Geoapify remains unconfigured, so the full venue-search PRD loop is still pending.

## Messages crash and live test — 2026-09-26

- [x] Inspect recent Messages crash reports, BlueBubbles status, and relevant logs; identify a reproducible cause before changing settings.
- [x] Apply the smallest safe fix and verify Messages opens directly without a new crash.
- [x] Confirm the exact Akshit–Nipun group GUID and BlueBubbles local API configuration.
- [x] Connect Rally webhook and allowlist, then verify inbound and outbound iMessage in that group.
- [x] Record live test evidence and remaining provider limits.

### Review

Ten Messages crash reports show `CODESIGNING`, `SIGKILL (Code Signature Invalid)`, and `Launch Constraint Violation` with BlueBubbles as the parent. BlueBubbles had Messages Private API enabled despite its `SIP Disabled: Fail` requirement. Disabling Private API stopped helper launch attempts; Messages opened directly and no newer crash report appeared. BlueBubbles and Rally then authenticated successfully after Rally adopted the existing BlueBubbles password. Contact metadata identified the Akshit–Nipun two-contact group, and its recent message matched the visible PRD message. The exact group was allowlisted, a local `new-message` webhook was registered, and Rally `/health` returns 200.

A single labeled API send returned an uncertain result. The marker was absent from the group's recent messages. BlueBubbles' AppleScript send timed out with AppleEvent `-1712`, then its automatic retry stalled; that retry process was stopped and no AppleScript send remains. A read-only AppleScript query to Messages also timed out. macOS reports the console session is locked, which also makes the app windows unavailable to Computer Use. Repeat one live send only after the user unlocks the Mac and inspect the group before retrying. No live delivery has been verified. xAI and Geoapify credentials remain empty. Ninety unit tests pass.

After the user unlocked the Mac, a read-only Messages AppleEvent succeeded. A new labeled test message was delivered to the exact allowlisted group and confirmed by BlueBubbles as `isFromMe=true`. The HTTP adapter's 15-second timeout fired before BlueBubbles completed at 17.3 seconds, so its timeout was raised to 45 seconds; the new test failed before the change and all 90 tests passed after it. No extra message was sent to retest the timeout. Two distinct real inbound group messages are stored in Rally; one arrived through the live webhook and one was manually replayed from BlueBubbles history for diagnosis. Both remain unprocessed because the Grok API key is empty, causing webhook processing to return 503. The live backend was restarted with the updated timeout. This verifies live iMessage transport in both directions, but the PRD decision and venue loop still needs xAI and Geoapify credentials.

## Live iMessage completion plan — 2026-09-25

- [x] Audit this Mac for Messages, BlueBubbles, and live provider configuration; verify current BlueBubbles setup and sender identity behavior against official documentation.
- [x] Restrict production ingestion, scheduled actions, and outbound delivery to configured group chat GUIDs so connecting a personal iMessage account cannot activate Rally in unrelated groups.
- [x] Verify the restriction and existing backend flow with tests, and document the exact live setup sequence.
- [ ] Configure BlueBubbles, xAI, Geoapify, and a test group; send and receive an actual iMessage and complete the PRD loop when the account and credentials are available.

### Live iMessage review

BlueBubbles Server 1.9.9 for Apple Silicon was downloaded from the official release, its DMG verified, and the app copied to `/Applications`. An ignored `.env` now contains a random webhook token and empty provider credentials and chat allowlist. The production-mode Rally backend was started on local port 8770; health returned 200 and a synthetic message from an unlisted chat was rejected. No live iMessage has been sent. Live xAI, Geoapify, identity, and group setup remain outstanding.

2026-09-26 update: The user authorized first launch. BlueBubbles opened and its wizard reported Full Disk Access missing. The wizard was inspected through its connection step; no Full Disk Access, Firebase account connection, server password, or proxy configuration was granted or saved. BlueBubbles would read the Messages database of the selected macOS user, so setup is waiting for the user's choice of current versus dedicated iMessage identity. The user identified an existing chat with Akshit and Nipun as the intended test group; no message has been sent to it.

The user chose the current iMessage account for immediate testing. BlueBubbles's Full Disk Access toggle was selected with the user's explicit approval, but macOS is waiting for the user's account password in System Settings before applying it. The password must be entered by the user directly on the Mac. A dedicated Rally account would require a separate verified Apple Account and macOS user; no account was created. No iMessage has been sent.

2026-09-26 follow-up: The user entered their Mac password; BlueBubbles now reports Full Disk Access **Pass**. The connection wizard is set to **LAN URL** rather than its Cloudflare tunnel. The generated server password is stored only in ignored, owner-only `.env`, and has not yet been saved in BlueBubbles. A fresh approval to save it was requested under the computer-use skill. The Rally local backend is currently stopped. Ninety unit tests pass. No live iMessage has been sent.

Final local check for this pass: 90 `unittest` cases passed with `ResourceWarning` treated as an error; the offline coordination flow reached `DONE` with one demo reservation and two outbound messages in 0.024 seconds; `compileall` and `git diff --check` passed. The installed app bundle and the port 8770 backend were present and responding.

## Continuation plan — 2026-09-25

- [x] Reconcile the PRD, spec, implementation, and tests; identify already completed work and genuine gaps.
- [x] Wire the existing Calendar adapter through opt-in settings, credentials, a persisted request cap, and documentation.
- [x] Preserve and use positive venue preferences from conversation extraction while keeping evidence-backed restrictions and safe selection.
- [x] Complete focused tests for the added behavior, rerun the full suite and offline demo, and update stale checklist entries.
- [x] Check available live credentials and provider services; record any external verification that remains unavailable.

### Continuation review

The Calendar adapter is reachable through normal service configuration only when explicitly enabled with full credentials. The service persists its calendar result separately from the demo reservation and caps attempts before calling Google. Extraction requires message citations for material plan terms, and relative dates are checked against the cited message's local date. The venue fixture is limited to Midtown, New York; preferred cuisines affect candidate order. The debug view now names the venue proposal when that is the blocker.

Final local verification: 88 `unittest` cases passed with `ResourceWarning` treated as an error; `compileall` and `git diff --check` passed. The offline demo reached `DONE` with one mock reservation and two same-chat outbound messages in 0.026 seconds. Live BlueBubbles, Grok, Geoapify, and Google Calendar checks remain unavailable because `.env` and the corresponding credentials and Mac server are absent. A real restaurant booking provider remains unavailable under the project's verified free non-LLM API constraint, so the PRD-authorized mock remains the booking path.

## Local HTTP verification — 2026-09-25

- [x] Start the actual FastAPI app with isolated offline fixtures on `127.0.0.1:8765`.
- [x] Verify `/health`, the local test page, and `/debug` return HTTP 200.
- [x] Exercise proposal and explicit approval over HTTP; observe `READY` then `DONE`, one demo reservation, and the final report.
- [x] Restart the server with a fresh `BLOCKED` plan for browser testing.
- [ ] Repeat the PRD flow using live BlueBubbles, Grok, and Geoapify once credentials and the Mac server are available.

The local test page uses simulated Grok, place search, and message delivery. It verifies the backend flow and debug view, but cannot establish that the live iMessage integration or external providers fulfill the PRD acceptance criteria.

> **For agentic workers:** Implement tasks in order. Read [SPEC.md](../SPEC.md) and [PRD.md](../PRD.md) first; use the checkboxes to track progress.

**Goal:** Ship the complete iMessage dinner demo in under two minutes, including one automatic intervention after a plan stalls.

**Architecture:** One FastAPI backend owns persistent plan state, Grok decisions, scheduling, approval checks, and tool execution. BlueBubbles and Geoapify are adapters. SQLite persists plans and action results across restarts.

**Tech stack:** Python, FastAPI, SQLite, Grok, BlueBubbles, Geoapify, and server-rendered HTML for the debug view. Runtime dependencies are pinned in `requirements.txt`.

**Spec:** [SPEC.md](../SPEC.md).

## Global constraints

- Automatic intervention is required for the MVP. The default stall threshold is 30 minutes and must be configurable for the demo.
- Keep plan records across restarts; do not build personal profiles or automatic cross-chat memory.
- LLM usage may be paid. All other external APIs must have a usable free path; stop at provider limits rather than silently incurring charges.
- No reservation or other commitment without explicit approval of the current concrete proposal.
- Never claim that venue search proves reservation availability. Label mock bookings as demo reservations.
- Keep BlueBubbles integration thin, and return all replies to the originating chat.

## Proposed file map

Implemented file map; closely related responsibilities share modules to keep the service small.

| Path | Responsibility |
|---|---|
| `app/main.py`, `app/config.py` | FastAPI entry point, configuration, lifecycle. |
| `app/models.py`, `app/store.py` | Shared schemas and SQLite persistence. |
| `app/bluebubbles.py` | Incoming event normalization and outgoing messages. |
| `app/agent.py` | Grok structured extraction and action decisions. |
| `app/policy.py`, `app/main.py` | State checks and periodic inactivity evaluation. |
| `app/places.py`, `app/reservations.py` | Free-tier venue lookup and local mock reservation. |
| `app/orchestrator.py` | Connect messages, state, decisions, tools, and outbound reports. |
| `app/main.py` | Read-only plan interpretation view. |
| `scripts/demo_smoke.py`, `docs/demo.md` | Reproducible scenario and operator script. |
| `tests/` | Focused contract, policy, integration, and demo-path checks. |

## P0 implementation sequence

### 1. Bootstrap and provider preflight

- [x] Create the FastAPI app, dependency lock, `.env.example`, and setup instructions in `README.md` for BlueBubbles, Grok, and Geoapify.
- [x] Keep API keys and chat configuration in environment variables, outside fixtures and logs.
- [ ] Check the BlueBubbles server and webhook connection, Grok structured output call, and Geoapify free-tier account. Record unavailable credentials as setup prerequisites.
- [x] Verify the server starts and reports health; confirm the non-LLM path has no paid provider dependency.

### 2. Define schemas and durable storage

**Depends on:** 1. **Delivers:** `ChatMessage`, `Plan`, `Proposal`, `Approval`, reservation result, and outbound-message records.

- [x] Define the fields and enums from `SPEC.md`, including message IDs, chat and sender IDs, evidence IDs, plan state, plan version, and proposal terms.
- [x] Create SQLite tables with unique constraints for incoming message ID and reservation proposal ID. Store intervention and delivery status.
- [x] Add operations to record a message once, load recent chat context, update the active plan, and record a booking once.
- [x] Verify duplicate messages are ignored, chats stay isolated, and plans and action results survive restart.

### 3. Receive and send group messages

**Depends on:** 2. **Delivers:** normalized incoming messages and same-thread outgoing replies.

- [x] Implement the BlueBubbles webhook endpoint and normalize supported new group-message events into `ChatMessage`.
- [x] Ignore Rally's own messages, empty or unsupported events, and duplicate message IDs. Persist accepted messages before processing.
- [x] Implement `send_message(chat_id, text)` through BlueBubbles; persist attempted, sent, and failed delivery state.
- [x] Verify a group message is recorded once and a response goes to its original thread; test a delivery failure without losing the queued response.

### 4. Extract conversation facts with Grok

**Depends on:** 2–3. **Delivers:** evidence-backed activity, interest, availability, preferences, objections, and unresolved decisions.

- [x] Define a strict extraction schema and prompt over recent messages plus current plan. Link facts to source message IDs.
- [x] Resolve relative dates against message timestamps and the configured chat time zone; represent unresolved city, party size, and date explicitly.
- [x] Reject malformed or contradictory model output before it changes persisted state.
- [x] Verify the PRD dinner example, “after 7” versus 7:00, “no sushi” as a restriction, and “Midtown preferred” as a preference.

### 5. Apply plan state and safety policy

**Depends on:** 4. **Delivers:** deterministic state transitions and eligibility checks for live messages and scheduler ticks.

- [x] Implement eight states and five decisions in `SPEC.md`, with `WAIT` as the default.
- [x] Derive state from chat evidence or tool results, and invalidate pending proposals when venue, date, time, party size, or constraints change.
- [x] Verify unrelated chatter stays silent, conflict triggers a targeted question, cancellation stops intervention, and failed tools cannot produce `DONE`.

### 6. Search for a viable venue

**Depends on:** 4–5. **Delivers:** normalized venue candidates with source IDs and location details.

- [x] Implement Geoapify Places search with bounded result counts, provider attribution, free-tier limits, and clear error results.
- [x] Filter against known restrictions, rank preferences, and keep incomplete provider facts marked unknown.
- [x] Add a fixed, clearly labeled venue fixture used only in demo mode.
- [x] Verify missing location or empty search leads to clarification or truthful failure; do not claim table availability from place search.

### 7. Generate decisions and concrete proposals

**Depends on:** 4–6. **Delivers:** a structured Grok decision and one persisted proposal when warranted.

- [x] Give Grok recent messages, structured state, available tools, and previous results; validate the returned action and confidence.
- [x] Let the backend approve `search_places`, select a viable venue, and create a proposal with exact venue, date, time, party size, and version.
- [x] Send a concise recommendation and ask whether to book the demo reservation.
- [x] Verify vague input yields `WAIT` or `ASK`, a viable venue yields a concrete proposal, and the same plan version does not generate duplicates.

### 8. Schedule automatic intervention

**Depends on:** 5–7. **Delivers:** one useful intervention for an eligible quiet plan.

- [x] Add a periodic job over persisted active plans and last human activity, with a configurable 30-minute threshold.
- [x] Require two interested people, a blocker, enough context, and no prior unsolicited intervention for that plan version.
- [x] Route scheduler and manual demo trigger through the same orchestration function and safety checks.
- [x] Verify one intervention after the threshold, none before it, and none repeated after restart or another scheduler tick.

### 9. Validate approval

**Depends on:** 3, 5, 7. **Delivers:** an `Approval` tied to the current proposal.

- [x] Accept clear affirmative instructions from a human in the originating chat only while exactly one current proposal is pending.
- [x] Record approving message and proposal ID before any reservation attempt; reject vague interest, other-chat messages, and stale terms.
- [x] Verify “I’m down” does not book, “Book it” approves the current proposal, and replayed approval creates no extra action.

### 10. Execute the mock reservation and report

**Depends on:** 9. **Delivers:** one stable demo confirmation and a truthful final iMessage message.

- [x] Make `create_reservation(proposal_id)` idempotent in local storage and return a stable confirmation ID with exact approved terms.
- [x] Move through `EXECUTING` to `DONE` only after a successful mock result and a sent final report.
- [x] Send a message labeled demo reservation with venue, date, time, party size, and confirmation ID.
- [x] Verify failed or uncertain results stay unresolved; retrying message delivery cannot rebook; duplicate approvals preserve one confirmation.

### 11. Show the debug interpretation

**Depends on:** 2, 5, 7–10. **Delivers:** a lightweight read-only demo view.

- [x] Render goal, interested people, signals, plan state, blocker, next action, confidence, proposal, and latest tool result from persisted state.
- [x] Keep secrets and unrelated chats out of the demo view.
- [x] Verify the view shows the same state that drove the iMessage proposal and updates after approval and tool completion.

### 12. Prepare and prove the end-to-end demo

**Depends on:** 1–11. **Delivers:** a repeatable under-two-minute walkthrough.

- [x] Seed the PRD dinner conversation with explicit sender identities, date context, time zone, and four interested people.
- [x] Document BlueBubbles setup, venue fixture mode, scheduler threshold, demo steps, and reset procedure in `docs/demo.md`.
- [x] Run the offline flow: quiet chat → automatic intervention → proposal → “Book it” → one mock reservation → completed message addressed to the originating chat ID.
- [ ] Run the same flow through a live BlueBubbles group chat, Grok, and Geoapify once credentials and the Mac server are available.
- [ ] Record elapsed time and check the debug view. Check no approval, changed terms, duplicate webhook, conflicting preference, venue-search failure, and reservation failure.

## P1 after the MVP works

- [x] Calendar: create a real event only when approval covers that action; report calendar and reservation outcomes separately and use a free API path within quotas. Live provider verification still requires OAuth credentials.
- [x] Meta/Muse: evaluate social-context extraction only if it improves fact accuracy; keep Grok responsible for agent decisions. Optional adapter added; a live accuracy comparison still needs credentials.
- [x] Dashboard polish: improve presentation after the lightweight view is correct.
- [x] Real reservation provider: assess when a genuine free integration and actual booking workflow are available; preserve the same approval contract. No qualifying provider is currently verified; keep the demo mock.

### Calendar integration plan

- [x] Implement and code-test a Google Calendar adapter using its no-charge standard API path and a stable event ID.
- [x] Add calendar-specific proposal wording and approval parsing, persist the approving message and calendar scope before action.
- [x] Persist calendar result separately from the mock reservation; reconcile restart and uncertain outcomes without duplicate creation.
- [x] Enforce a small application request cap and report reservation and calendar outcomes separately.
- [x] Verify configured and unconfigured flows with code tests, then document OAuth setup and the remaining live check.

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

## Implementation review — 2026-09-25

- Initial local verification recorded 50 `unittest` cases. The continuation review below records the current test count. The FastAPI health route is covered with a code client.
- Approval is bound to the sent current proposal, expires after 24 hours, and is blocked when an earlier message failed extraction. SQLite keeps completed plan history and recovers an approval saved before a crash.
- The remaining open P0 boxes cover live provider preflight and a live same-thread iMessage run. Credentials and a BlueBubbles Mac server are required for those checks.
- Outbound transport can have an ambiguous result if BlueBubbles accepts a message but the connection fails before Rally receives its response. Such sends are now held as `uncertain` rather than automatically retried; inspect the chat before any manual retry. The mock reservation itself remains idempotent.


## Hackathon demo audit — 2026-09-26

Scope: favor one source-backed group-planning flow; no live messages, deployment,
private history export, or changes to existing user configuration. Context fields
(hours, team, tracks) were placeholders; use relative sprint allocation.

- [x] Inspect repository, integrations, lessons, and primary planning flow.
- [x] Independently audit model/transport dependencies and demo failure paths.
- [x] Record the eight-section judge review in docs/hackathon-review.md.
- [x] Restore pinned dependencies and establish test baseline.
- [x] Show escaped source quotes in the authenticated debug view.
- [x] Make the proposal's explicit approval phrase discoverable.
- [x] Export labeled offline replay snapshots using the existing smoke scenario.
- [x] Verify each change and run full pytest plus primary demo smoke.
- [x] Record results and remaining live integration limitations.

### Push verification — 2026-09-26

- Full pytest: 155 passed, one existing dependency warning.
- Offline smoke: DONE, one simulated reservation, two captured messages.
- `git diff --check`: clean. Live iMessage self-test creation returned uncertain; no automatic retry. Vercel CI is not implemented.


### Hackathon audit review results

Baseline: 153 pytest tests passed after installing pinned requirements and pytest
into the existing .venv. New source-quote, HTTP-wiring, approval-prompt, and replay
checks first failed against the old behavior; focused checks then passed. Final
suite: 155 passed, 12 subtests passed, one upstream Starlette/AnyIO deprecation
warning. Offline replay reached DONE with two outbound fixture messages and one
simulated reservation; generated three source-backed, explicitly labeled HTML
snapshots in ignored data/demo_replay. Local HTTP response matched generated
blocked.html; all stage links were checked. Independent review found no substantive
correctness/security regressions. git diff --check passed.

Browser discovery returned no connected browser, so rendered desktop/mobile visual
QA remains unverified. Live model extraction, venue search, native iMessage delivery,
and actual table booking were not tested during this audit. No messages were sent,
private history exported, deployment changed, or live configuration modified.

### Explicit history-command reply fix

- [x] Trace original request: stored in allowlisted group, trigger rejected `rally turn on history for this group chat`, no reply queued.
- [x] Reproduce two failing regressions, support imperative triggers and portal visibility synonyms, explain globally disabled history without imports/model calls.
- [x] Full pytest: 157 passed; diff whitespace check clean.
- [x] Restart service and process original command once: HTTP 200 accepted, BlueBubbles acknowledgement recorded as sent. History remains disabled.
- Note: synthetic Grok requests succeeded; failures processing other ordinary messages remain a separate unverified issue. Real group-context replay to xAI was rejected by automatic approval review and was not performed.

### Live group latency checks

- User re-enabled group history; restored history/media/analytics sections and restarted service.
- Two authorized labeled tests sent in the allowlisted group. Page-link reply acknowledged sent at 1.83 seconds; Grok-backed help reply acknowledged sent at 9.78 seconds from send initiation. Input transport acknowledgements 0.83 and 0.74 seconds respectively.
- Measurements poll SQLite at one-second intervals and confirm provider acknowledgements, not recipient screen/read time. Both original requests were observed via live BlueBubbles webhooks.

## Updated relationship-manager PRD — parallel audit

- [x] Capture updated product intent and demo acceptance flow in docs/relationship-mvp-audit.md.
- [x] Dispatch independent memory/dashboard, follow-up, and calendar audits concurrently.
- [x] Consolidate existing functionality and missing demo requirements.
- [ ] Review the proposed subsystem design, then implementation plan, before coding new behavior.

### Universal direct Rally addressing

- [x] Replace command-word allowlist with start-of-message Rally/@Rally/optional greeting trigger; unrelated mid-message mentions remain ordinary chat.
- [x] Allow natural replies outside planning in direct-answer prompt, retaining approval and non-invention rules.
- [x] Regression red/green and full pytest: 159 passed.
- [x] Restart local service and process Nipun's unanswered request once: direct reply recorded sent. Subsequent extraction failed (HTTP error after 36.03 seconds total), so broader plan-processing failure remains open.
- [ ] Diagnose extraction failure. Automatic approval review rejected a standalone real-context xAI diagnostic replay even after history re-enable; no workaround attempted. Synthetic Grok requests succeeded earlier.

### Extraction diagnostics and updated PRD implementation plan

- [x] User explicitly authorized one real group-context xAI extraction diagnostic. Subagent consumed it once: provider ReadTimeout at the prior 25-second timeout, no further replay.
- [x] Add sanitized provider stage/kind/HTTP-status diagnostics and configurable extraction HTTP timeout (default 60 seconds, range 1–120). Direct replies/decisions retain 25 seconds. Evidence/participant/date validations preserved.
- [x] Regression tests demonstrated failure before fixes; root integrated env setting and safe webhook logging. Full suite: 166 passed, existing dependency warning.
- [x] Restart the local service with the verified change. Live extraction success remains unverified; larger timeout can increase shared-lock wait.
- [x] Replace PRD.md with the user's relationship-manager PRD, retaining previous planner PRD in docs/group-planning-prd.md.
- [x] Write reviewable design and implementation plan for private dashboard, local follow-ups, calendar availability/setup, reviewed actions and connected demo.
- [x] Written implementation plan approved. Later user instruction assigns dashboard, follow-ups, calendar and deployment to external teammates; internal agents restricted to existing-runtime reliability and integration review.


### External teammate coordination

- [x] Record dashboard/follow-up/calendar/deployment ownership in docs/team-ownership.md and narrow approved implementation plan accordingly.
- [x] Tell running agents not to implement external teammate subsystems.
- [ ] Obtain teammate branches/PRs and actual interface contracts.
- [ ] Integrate shared routes/configuration and connected end-to-end demo after teammate deliverables arrive.
- [x] Verify scheduler isolates one failing group plan from other plans and private-monitor exceptions from subsequent checks: regression tests, 169 passing tests, independent review clean.


### Ownership-constrained execution review

- External teammates have not started branches yet; assignments remain reserved. No dashboard/follow-up/calendar/deployment code added in this session.
- Root completed current runtime config/logging and scheduler isolation; subagents implemented extraction diagnostics and group-plan isolation and independently reviewed the combined diff.
- Final full suite: 169 passed, one existing dependency warning. `git diff --check` clean.
- Existing shared lock still spans provider calls; a longer extraction HTTP timeout can increase queue latency. HTTPX timeouts are per network phase rather than total wall-clock deadlines.
- One real extraction diagnostic timed out at prior 25-second setting. No second replay and no real messages sent during this reliability work; live extraction success is not claimed.

## Read-only web research and adaptive tone

- [x] Confirm xAI Responses API web_search, citations, store=false, bounded max_tool_calls and pricing in primary docs.
- [x] Add read-only web client with private-host citation filtering, sanitized errors, bounded tool/output counts, and tests.
- [x] Route directly addressed public/current information requests to web search with a separate SQLite daily quota; no raw surrounding history is sent to web search.
- [x] Infer casual/formal/neutral style locally and guide normal and web replies without imitating people.
- [x] Verify a synthetic public query through xAI web search (7.62 seconds, public source URL) and one labeled authorized group request (same-thread outbox `sent`, source URL, 7.93 seconds). No private history sent to the web client.
- [x] Review search/tone paths, test citation and provider-failure handling, run full suite (186 passed), restart local app, commit and push.


### Web search review

- xAI web search is read-only and limited to one Responses request with at most three server-side tool calls. The local daily quota defaults to unlimited (`0`); a positive configured cap consumes before a provider attempt. Provider tool and token charges still vary.
- [x] Remove the arbitrary daily default cap, retain an optional configured cap, and update the running local configuration.
- The classifier covers obvious public/current queries; it is not a general autonomous tool planner. A requested venue search does not prove a business is open or a table available. Calendar, contact, and code tools remain separate and require the previously planned integrations/approvals.
- The current direct message alone goes to xAI for web research. The local style label includes no surrounding message text. Group extraction remains separate and can still time out on other messages.

### Adaptive requests implementation (unassigned backend area)

- [x] Ground design in docs/remaining-functionality-design.md and write docs/adaptive-requests-implementation-plan.md with boundaries to external teammate work.
- [x] Implement durable request/workflow store and tests.
- [x] Implement registry and exact approval boundary with tests.
- [x] Implement structured planning and inert generated-code proposals with tests.
- [x] Integrate explicit adaptive requests into same-chat routing without stealing existing portal/planner/web behavior.
- [x] Verify and document actual capability coverage, commits and live behavior.

### Adaptive requests review

- Explicit `Rally, build/automate/do/use tools…` requests enter the adaptive planner in allowlisted chats. Portal commands and direct web lookups keep their existing priority. Registered read tools are plan status and the existing budgeted web search. No commitment tool is currently registered, so approval-bound side effects remain a framework, not a live capability.
- Missing capabilities are durable. An optional second model call drafts Python source as inert, private data for developer review; no generation result is installed or executed. The review endpoint requires a separate admin token in a request header and is outside the public portal.
- Synthetic xAI planner call selected `get_plan_status` successfully. Synthetic xAI code-draft call produced a syntax-valid `pending_review` artifact. Neither test sent an iMessage or used private group context. Full suite: 215 tests passed before final review.
- One labeled Akshit–Nipun group request entered through BlueBubbles, completed the adaptive `get_plan_status` step and sent a same-chat direct reply (`Rally: {"status": "none"}`). Inbound message was processed, adaptive request status `complete`, outbox `sent`. This verifies the read-only live adaptive route; generated code and commitment tools were not tested in the live chat.
