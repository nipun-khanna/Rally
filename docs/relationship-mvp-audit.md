# Relationship manager MVP — design

## Product brief

Source: user's updated HackGT 13 PRD. Working product name is TBD; Rally remains the existing implementation name. Product loop: Understand → Notice → Act. Help users maintain chosen relationships, with the existing group planner retained as the Planning Agent.

Relationships include categories (friends, family, parents, siblings, cousins, grandparents) and intentions such as twice-weekly contact, weekend calls, fortnightly meetings, staying close after moving, or becoming closer. Memory includes last meaningful interaction, commitments, plans, and follow-ups.

The private dashboard should show actionable attention cards: overdue contact (Text/Call), unfinished dinner discussion (Finish Plan), stalled group plan (Resolve). Conversation intelligence should remember promises and unfinished actions. Calendar awareness should turn intentions into concrete suggestions.

## Demo acceptance flow

1. Show a chosen important relationship needing attention with an honest interaction basis.
2. Identify a stalled plan from an iMessage conversation, retaining supporting evidence.
3. Check authorized calendar availability, propose a time, draft the human-facing message, and create the approved event.

## Constraints

- Reuse existing BlueBubbles integration, persistent planning state, relationship store, and approval/calendar adapters.
- Keep personal relationship records and selected source conversations private, separate from public group portals.
- A message does not prove a call/visit or a meaningful interaction. Unknown evidence must be labeled.
- Another person's availability requires authorized calendar access or their explicit confirmation.
- No automatic personal message, event, invitation, or booking based solely on inferred commitment.
- Current live group history was explicitly re-enabled; personal source consent remains separate.
- Existing booking adapter is simulated; Calendar event creation is coded but live credentials are missing.

## Parallel audits

- [x] Relationship memory, categories/intentions, private dashboard and actions.
- [x] Conversation commitments, pending follow-ups, stalled-plan reuse.
- [x] Calendar availability, draft/proposal/approval integration and OAuth gaps.
- [x] Consolidate minimal design and demo test plan for review before implementation.

User approved continuing with this design and subagent execution. New feature implementation awaits the written implementation-plan review. The independent extraction bugfix is separately authorized.

## Consolidated findings so far

### Relationship memory and dashboard

Already built: owner-scoped contact records, one mode and 1–90-day cadence, manual confirmations, selected-source message evidence, pause/snooze/remove, durable reminders and explicit cadence suggestions. Missing: categories and intention metadata, multi-intention/weekend/twice-weekly semantics, meaningful-interaction classification, private dashboard and linked action cards.

Add a separate authenticated local relationship dashboard, with attention projection and renderer in the relationships package. Keep unknown contact distinct from confirmed overdue contact, and show evidence provenance. Dashboard Text/Call controls should open a draft/dial action; no automatic contact send. Reuse existing control/confirmation methods. Derive owner from authentication, not request parameters. Preserve private export exclusions.

### Planning and calendar

Current planner checks conversational constraints and venue preferences, but selects stated time or earliest-time-plus-one-hour without calendar checks. Calendar adapter inserts an approved event only in the demo-reservation execution path. A free/busy adapter and explicit draft/event action independent of simulated reservation are required. Another person's availability cannot be asserted without authorization or confirmation.

### Conversation privacy

Selected personal sources intentionally bypass group Grok extraction. Follow-up processing should extend local selected-source ingestion; do not silently transmit personal conversations to a cloud model. Vague invitations need candidate/pending state because the existing group stall rule requires explicit blockers and multiple participants.

## Proposed MVP implementation design — for review

### Memory and private UI

Extend existing private people records with category and intention description. Preserve current cadence calculations; demo uses an explicitly configured interval (for example call every seven days). Rich weekday/count-per-week and multiple-intention scheduling remain separate follow-on requirements, not claimed implemented. Build owner-authenticated local /relationships dashboard, attention data and mutation endpoints; use session/header authentication and CSRF protection for browser mutations. Include contact evidence, paused/snoozed status, pending follow-ups and unfinished group plans. Text/Call actions open review/dial flows, not automatic third-party delivery.

### Conversation intelligence

Add private rel_followups records keyed by owner/source message/kind. Local conservative rules detect the four example commitments and unfinished-plan phrases. Persist source provenance, detector/source revision, optional due date and certainty, and suggested/accepted/done/dismissed state. Interpret relative time from source timestamp and owner time zone. Ambiguous timing requests confirmation. Incoming promises do not become owner obligations. Edits/deletions/source disable/remove invalidate derived evidence; explicit user decisions survive rescans. Do not claim awkwardness or meaningful-interaction inference from simple message presence.

Expose existing unfinished group plans without expanding autonomous-send rules. Selected private-source plan candidates stay local and enter the explicit reviewed action flow.

### Availability and action

Add an injected Google free/busy adapter and pure slot selection. Request events plus free/busy OAuth scopes through an executable local setup flow. Only connected calendars contribute coverage; errors/missing calendars remain unknown. Persist coverage and checked-at time, not event titles. Owner-only availability means 'your calendar is open; ask Alex', not 'both free'.

Add a generic approved meetup/call event path alongside the existing restaurant/calendar adapter. Bind draft and event approvals to exact current action versions; edits invalidate approvals. Draft review precedes optional sending; calendar creation needs its own explicit approval. Preserve deterministic provider event IDs and uncertain-outcome handling. Do not fabricate recipient email mappings or invitations.

### Connected demo and verification

Use synthetic seeded relationship plus a consented/fixture stalled conversation. Demonstrate overdue contact card → evidence-backed unfinished plan → available slot → editable draft → explicit approval → event outcome. Label fixture calendar results until actual OAuth is connected. Verify private ownership/auth, escaping, source lifecycle races, timezone/DST, busy overlap and unknown coverage, approval invalidation and dedupe, and no public export of private records. Keep existing 166-test baseline passing. Live calendar validation remains dependent on user OAuth credentials; live group messaging already worked in the latest latency checks.

### Execution boundaries

After design and implementation-plan review, run independent memory/dashboard, local follow-up, and availability/event tasks in parallel with nonoverlapping file ownership. Root handles shared main/config integration and the connected end-to-end demo. Integrate only reviewed passing changes. Preserve existing planner, transport, data, and public portal.
