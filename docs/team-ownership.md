# Team ownership and integration handoff

Updated from user's explicit teammate assignments on 2026-09-26. This ownership map supersedes the earlier internal-agent ownership in the relationship MVP implementation plan.

## Work assignments

| Area | Owner | Deliverable | This session |
| --- | --- | --- | --- |
| Private relationship dashboard | Human frontend teammate | Attention cards, relationship profiles, draft review, action states | Do not implement dashboard UI or its interaction states |
| Local follow-up detection | Human backend teammate | Commitments, unfinished plans, source evidence, dismiss/snooze/done | Do not implement detector, follow-up tables or lifecycle APIs |
| Calendar integration | Human backend teammate | OAuth setup, free/busy, slots, approved meetup events | Do not implement calendar adapters or setup flow |
| Website deployment | Human frontend/infra teammate | GitHub → Vercel previews and production | Do not implement CI or deployment settings |
| Existing iMessage/planning reliability | Root + assigned subagent | Trigger fixes, provider diagnostics, scheduler isolation, regression tests | Implement and verify existing runtime fixes |
| Shared integration | Root | Agreed API/config contracts, shared main/config wiring after deliverables arrive, combined tests and demo | Prepare contract/checklist now; integrate actual modules later |

User confirmed external teammates have not started branches yet; those assignments remain reserved. No external teammates have been messaged by tools. Existing subagent audits were read-only; the extraction subagent changed only existing provider code/tests. Scheduler subagent is restricted to existing `app/orchestrator.py` and `tests/test_service.py`.

## Shared file ownership

Root coordinates changes to `app/main.py`, `app/config.py`, `.env.example`, the connected end-to-end demo, and cross-subsystem integration tests. Teammates can propose shared changes in their PRs; root reviews and merges agreed wiring rather than implementing duplicate APIs first.

The existing `app/relationships/store.py` and `learning.py` are shared dependencies. Any teammate modifying them should identify migrations and lifecycle hooks in their PR. Do not assume root has already added category/intention fields or follow-up hooks; those are planned, not implemented.

## Contract checklist to include in each PR

### Dashboard

- State which routes/components it owns and its local/private vs synthetic-preview mode.
- State expected relationship/attention/action schemas and authentication mechanism; do not treat public group bearer links as personal authorization.
- Unknown contact vs confirmed contact age and provenance are distinguishable.
- Draft review, calendar suggestion, send approval, and event approval have explicit UI states.
- Share mocked fixtures and action request/response examples; root will bind actual APIs after agreement.

### Follow-up backend

- State constructor/service/list/decision signatures and source ingestion hook requirements.
- Include owner, relationship/source IDs, source revision, evidence, timing certainty, status, and lifecycle behavior.
- Define how edit/delete/disable/remove/rescan affects candidates and durable user decisions.
- Keep personal selected source processing local. Do not expand cloud transmission from this assignment.
- Detection itself does not send a message or create an event.

### Calendar backend

- State configuration keys, required OAuth scopes, connected-calendar mapping and injectable transport interfaces.
- Availability results distinguish covered, unknown, and error calendars and include checked-at time and request window.
- Slot results use timezone-aware timestamps and durations. Owner-only availability cannot claim both participants are free.
- Approved event API must expose explicit approval/version requirements and idempotent/uncertain result states.
- Distinguish fixture mode from actual provider connectivity; no automatic attendee email guesses/invitations.

### Deployment

- State website root/build command, production branch, preview behavior and required repository/Vercel secrets.
- Use synthetic website data for collaboration previews; a GitHub runner does not have the Mac's operational SQLite database.
- Keep personal dashboard data and credentials out of static group export/deployment.
- Coordinate with existing local portal publisher so automatic deployments do not erase existing group snapshots unexpectedly.

## Root integration acceptance tests

After teammate contracts and branches arrive:

1. Existing group messages/approvals still work; one failing plan cannot starve another.
2. Private dashboard authentication rejects unauthenticated reads/writes and forged/stale actions.
3. Selected personal follow-ups never enter public portals or cloud group extraction.
4. Disabled/removed/edited source invalidates derived candidate/action and cannot resurrect it through rescan.
5. Calendar unknown coverage never becomes a free-slot claim.
6. Edited draft/time/source invalidates previous approval; repeated approval performs at most one side effect.
7. Lost provider response is retained as uncertain with no blind retry.
8. Connected fixture demo links attention → stalled plan → available slot → reviewed draft → approved event, clearly labeled until live OAuth is configured.

This document proposes handoff requirements. It does not claim teammate API contracts have been accepted or their modules completed.

## Integration ownership still to settle

Versioned draft-send/event action persistence (`relationships/actions.py` in the proposed plan) needs one agreed owner before implementation. Root will not prebuild it while frontend/calendar teammates define their contracts. The profile-preference fallback also crosses store/learner ownership and should be agreed in their handoff. Shared `create_app` dependencies must remain injectable for tests without reading operational `.env`.
