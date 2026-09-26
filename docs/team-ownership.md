# Team ownership and integration handoff

Updated 2026-09-26 after the user asked root to build the remaining relationship MVP. This supersedes the earlier human teammate ownership for dashboard, follow-up detection, and calendar availability.

## Work assignments

| Area | Owner | Deliverable | This session |
| --- | --- | --- | --- |
| Private relationship intelligence | Root (implementation requested) | Relationship intentions, private attention dashboard, evidence, reviewed actions | Keep every personal record owner-scoped and out of group storage/export |
| Local follow-up detection | Root (implementation requested) | Commitments, unfinished plans, source evidence, dismiss/snooze/done | Process only explicitly selected sources locally |
| Calendar availability | Root (implementation requested) | OAuth setup, free/busy coverage, slots, approved meetup events | Unknown calendar coverage is never reported as free |
| Vercel deployment | Root/operator (manual) | Use the existing Mac publisher for the group archive; deploy any future standalone site manually to a separate Vercel project | GitHub Actions is deferred; never deploy website code to `rallyplans` |
| Existing iMessage/planning reliability | Root + assigned subagent | Trigger fixes, provider diagnostics, scheduler isolation, regression tests | Implement and verify existing runtime fixes |
| Shared integration | Root | Wire relationship memory, dashboard, follow-ups, calendar availability, planning, and reviewed actions into one private demo | Integrate only after each module has its contract and focused tests |

The user's latest instruction assigns the remaining relationship MVP implementation to root. Keep the previously approved ownership boundaries for existing runtime reliability and deployment behavior; do not replace the BlueBubbles transport or modify live data during fixture testing.

## Shared file ownership

Root coordinates changes to `app/main.py`, `app/config.py`, `.env.example`, the connected end-to-end demo, and cross-subsystem integration tests. Independent modules must keep injectable dependencies and avoid reading operational `.env` during tests.

The existing `app/relationships/store.py` and `learning.py` are shared dependencies. Schema work must include backward-compatible migrations and source lifecycle hooks. Relationship intent fields and follow-up hooks are planned, not implemented.

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

- There is no standalone website source directory yet, and no GitHub Actions deployment workflow is configured.
- Use the Vercel CLI manually for a future standalone website, from its own directory and linked to a Vercel project separate from `rallyplans`.
- The existing `rallyplans` project is the production group archive and is refreshed by the Mac publisher, which requires the local SQLite database and media.
- Keep personal relationship data and credentials out of any website build inputs. Do not send archive data through GitHub Actions.
- Keep personal dashboard data and credentials out of static group export/deployment.
- See [Vercel deployment operations](vercel-deployment.md) for the manual procedures.

## Root integration acceptance tests

As the independent modules are integrated:

1. Existing group messages/approvals still work; one failing plan cannot starve another.
2. Private dashboard authentication rejects unauthenticated reads/writes and forged/stale actions.
3. Selected personal follow-ups never enter public portals or cloud group extraction.
4. Disabled/removed/edited source invalidates derived candidate/action and cannot resurrect it through rescan.
5. Calendar unknown coverage never becomes a free-slot claim.
6. Edited draft/time/source invalidates previous approval; repeated approval performs at most one side effect.
7. Lost provider response is retained as uncertain with no blind retry.
8. Connected fixture demo links attention → stalled plan → available slot → reviewed draft → approved event, clearly labeled until live OAuth is configured.

This document captures current implementation requirements; it does not claim that unfinished modules or live-provider setup are complete.

## Integration ownership

Root owns versioned draft-send/event action persistence and shared profile wiring for this implementation. Keep actions revision-bound and require separate approval for message sending and calendar event creation. Shared `create_app` dependencies must remain injectable for tests without reading operational `.env`.
