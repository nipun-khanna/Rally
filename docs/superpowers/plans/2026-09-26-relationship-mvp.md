# Relationship Manager MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build the PRD's private attention → unfinished plan → calendar availability → reviewed draft → approved event demo, preserving the existing iMessage planner.

**Architecture:** Extend private relationship storage and selected-source local analysis, mount a separate authenticated dashboard router, and add isolated calendar availability/event adapters. Use persistent versioned action state for reviewed drafts and approved events; existing group planner and reservation behavior remain compatible.

**Tech Stack:** Python, FastAPI, SQLite, Pydantic, server-rendered HTML/CSS/JavaScript, Google Calendar HTTP API, existing BlueBubbles adapter. Use current pinned requirements, no new runtime dependencies by default.

**Spec:** `PRD.md` and `docs/relationship-mvp-audit.md`; prior planner requirements preserved in `docs/group-planning-prd.md`.

## Global constraints

- Personal relationship records and selected source conversations stay outside public portals and static exports.
- Selected source analysis remains local; no new personal cloud-model transmission.
- No third-party send, invitation, or calendar write without explicit current-version approval.
- An outgoing message is messaging evidence, not proof of meaningful contact, call, or visit.
- Calendar errors/missing authorization mean unknown availability, never free.
- Only consented connected calendars may contribute to availability; no invented attendee email mappings.
- Keep existing planner, transport, data, and public portal working. Reservation simulation remains labeled.
- Demo may use clearly labeled synthetic/fixture data until Google OAuth is connected.
- Rich weekday/count-per-week and multiple-intention scheduling are later PRD work; this MVP implements category/intention text and current interval scheduling honestly.
- Verify with `/opt/homebrew/Caskroom/miniconda/base/bin/python -m pytest -q`; baseline is 166 passing tests.

## Review focus

1. No private reminder destination configured: dashboard setup must still work, without creating fake iMessage routing or sending reminders.
2. Disabled/removed/edited sources: derived follow-ups must disappear or become explicitly unsupported; rescans cannot resurrect a user's dismissal.
3. Another owner or forged form: no private reads/writes, including CSRF and stale action submissions.
4. Partial calendar response/DST: unknown coverage is not free, ambiguous/nonexistent local times cannot become approved events.
5. Provider accepted a send/write but response lost: uncertain state is durable, with no automatic duplicate action.

## Current execution ownership (user correction)

The user approved the written plan, then assigned dashboard, follow-up detection, calendar integration, and website deployment to external human teammates. `docs/team-ownership.md` governs execution. Tasks 1–3 and dashboard interaction implementation belong to those teammates, not internal coding agents. Root executes existing-runtime reliability and shared integration only, without prebuilding teammate schemas or adapters. Task 4 wiring and Task 5 connected demo wait for their actual interfaces. Earlier file/API suggestions below are proposals for handoff, not authority to duplicate teammate work.

## Original decomposition (reference only)

- Memory/dashboard worker: `app/relationships/store.py`, new `dashboard.py`, `view.py`, `routes.py`, related new tests. No `main.py` or `config.py` edits.
- Follow-up worker: new `app/relationships/followups.py`, `learning.py`, new follow-up tests. Add its own private table via its constructor using the existing transaction API; do not edit store schema concurrently.
- Calendar worker: new `app/availability.py`, `app/relationship_events.py`, `scripts/configure_calendar.py`, adapter tests, `docs/calendar.md`. Do not edit existing `calendar.py`/planner concurrently; reuse its primitives where safe.
- Root: shared main/config wiring, versioned action integration, connected demo, integration review, final verification and commits.
- Independent extraction bugfix: separately authorized and can proceed before this new-feature plan approval. One real diagnostic replay already consumed; no further replay is authorized by that permission.

## Task 1: Private profiles and attention dashboard

**Files:** Modify `app/relationships/store.py`; create `app/relationships/dashboard.py`, `app/relationships/view.py`, `app/relationships/routes.py`; test `tests/test_relationship_dashboard.py`, extend store/HTTP/export tests.

**Interfaces:**

- `store.ensure_profile(owner: str, zone: str, hour: int = 18) -> dict` creates local preferences without a transport destination.
- `store.profile(owner: str) -> dict` resolves existing reminder config preferences or local preferences. Reminder delivery still iterates actual configured destinations only.
- `store.set_metadata(owner: str, label: str, *, category: str, intention: str, contact_address: str | None = None) -> dict` validates supported categories and metadata lengths; no send.
- Existing `upsert` accepts a local profile as setup prerequisite; existing command/config behavior stays compatible. Learner uses `profile` for time zone.
- `build_attention(store, owner: str, now: datetime, *, followups=None, plans=()) -> dict` returns evidence-labeled relationship cards and unfinished plan references.
- `render_dashboard(data: dict, csrf: str) -> str` renders escaped private iMessage-themed UI.
- `relationship_router(store, owner: str, *, token: str, time_zone: str, action_service=None, planning_store=None) -> APIRouter` is mounted explicitly by root before catch-all group route.

- [ ] Write migration tests for existing database/category fields and local profile without reminder destination; prove they fail.
- [ ] Add backward-compatible migrations and metadata methods. Preserve existing config/destination protection.
- [ ] Write attention tests: confirmed overdue, unknown anchor, messaging provenance, snooze/pause, owner isolation; prove they fail.
- [ ] Implement attention projection from existing cadence rules and private records. Do not rename latest outgoing text as meaningful contact.
- [ ] Write auth/CSRF tests: missing/bad login, signed expiring HttpOnly SameSite=Strict session, CSRF mismatch, wrong owner, escaped HTML; prove they fail.
- [ ] Implement GET `/relationships`, POST `/relationships/login`, POST `/relationships/logout`, authenticated JSON attention and typed local relationship-control endpoints. Token is submitted in POST body, never query strings; no external script dependencies. Cookies Secure on HTTPS; local HTTP supported explicitly.
- [ ] Implement create/edit profile, confirm contact, pause/resume/snooze, draft/dial controls using existing methods. Text/Call does not send automatically. Unconfigured transport appears as setup state.
- [ ] Run focused tests, existing relationship tests and export privacy regression; request review before integration.

## Task 2: Local follow-up memory

**Files:** Create `app/relationships/followups.py`; modify `app/relationships/learning.py`; create `tests/test_relationship_followups.py`; extend source lifecycle tests.

**Interfaces:**

- `FollowupStore(store)` uses `store.db()` transactions; stores `rel_followups` source-owned records and separate durable user decisions.
- `detect_candidates(text: str, at: datetime, zone: str, *, outgoing: bool) -> list[dict]` returns kind/action/optional time window/certainty from local conservative rules.
- `sync_source(owner: str, chat_id: str)` projects current selected-source `rel_texts` inside a checked source revision transaction; no HTTP/model call.
- `list_for_owner(owner: str, *, now: datetime | None = None) -> list[dict]` includes only enabled current evidence. Source disable/remove is enforced by joins and cleanup.
- `decide(owner: str, followup_id: str, *, expected_revision: int, status: str, due_at: datetime | None = None)` accepts/dismisses/completes/snoozes owner-scoped current candidates.
- Learner constructor optional `followups=None`, updates follow-up projection in the same source-checked apply/rescan completion path.

- [ ] Write tests for the four PRD phrases plus 'we should get dinner'; prove fail.
- [ ] Implement conservative local candidate detection with provenance, owner-vs-incoming distinction, ambiguous due times, and timezone-relative dates.
- [ ] Write exclusion tests for negation, quoted examples, completed actions, bot output/reactions/deletions; implement minimal rules.
- [ ] Write duplicate/edit/delete/disabled/remove/full-rescan/source-revision race tests; implement source projection and durable decisions.
- [ ] Write owner separation, stale revision, dismissal survival, no cloud/portal export tests; implement decision APIs.
- [ ] Run focused source/followup tests and relationship suite; request review before integration.

## Task 3: Calendar availability, generic approved event, and setup

**Files:** Create `app/availability.py`, `app/relationship_events.py`, `scripts/configure_calendar.py`; create `tests/test_availability.py`, `tests/test_relationship_events.py`, `tests/test_calendar_setup.py`; update `docs/calendar.md`.

**Interfaces:**

- `BusyInterval(start: datetime, end: datetime)` and `AvailabilityResult(window_start, window_end, busy_by_calendar, covered_calendar_ids, unknown_calendar_ids, checked_at)`.
- `fetch_availability(credentials, calendar_ids: list[str], start: datetime, end: datetime, *, opener=...) -> AvailabilityResult` uses bounded Google OAuth/freeBusy HTTP requests. Reject wildcard/unconnected IDs at caller integration.
- `find_slots(result, *, required_calendar_ids: list[str], duration_minutes: int, zone: str, start_hour: int = 9, end_hour: int = 21) -> list[dict]` returns slots only within covered windows and known calendars, on 30-minute increments; busy intervals have exclusive end boundaries.
- `ApprovedRelationshipEvent(action_id, version, approval_id, title, start, duration_minutes, location)` and `create_relationship_event(event, credentials, *, opener=...) -> CalendarEvent` preserve deterministic provider IDs and matching approved terms.
- CLI obtains events and freebusy OAuth consent using a registered client, localhost callback, state+PKCE, timeout and restrictive ignored output file; no secrets/codes printed. `--help`/dry-run require no external calls.

- [ ] Write missing/error/calendar-boundary/DST/overlap tests; prove fail.
- [ ] Implement bounded free/busy adapter. Keep only intervals and coverage; missing/error calendar is unknown.
- [ ] Write owner-only vs all-participant coverage and slot duration/local-day tests; implement slot search.
- [ ] Write approval/no-network-before-approval, stable ID duplicate/lost response reconciliation and altered terms tests; implement generic event adapter separate from mock restaurant booking.
- [ ] Write OAuth URL scope/state/PKCE, callback validation and protected output tests; implement CLI and setup docs.
- [ ] Run calendar/availability/setup suites; request review before integration.

Google primary references: https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query and https://developers.google.com/workspace/calendar/api/auth. FreeBusy accepts `calendar.freebusy`; use it alongside existing `calendar.events` scope. Existing event-only refresh tokens need new consent.

## Task 4: Versioned reviewed action flow and shared wiring

**Files:** Create `app/relationships/actions.py`; modify `app/main.py`, `app/config.py`, `.env.example`; extend relationship HTTP/config tests; create `tests/test_relationship_actions.py`.

**Interfaces:**

- `RelationshipActions(private_store, planning_store, *, send_fn=None, availability_fn=None, event_fn=None, allowed_group_ids=())` stores owner-scoped `rel_actions` with source version, explicit destination mapping, draft/time/duration, availability provenance and separate send/event approval/result fields.
- `prepare(owner, source_kind, source_id) -> dict`, `check_availability(owner, action_id, version, window) -> dict`, `edit(owner, action_id, version, draft, start, duration) -> dict`, `approve_send(...)`, `approve_event(...)` all revalidate current source and expected action version.
- Sender uses current confirmed relationship chat mapping or approved allowlisted group; a label/phone guess cannot become a recipient. Unknown destination supports copy-draft only.
- Event creation is independent of optional draft send; failure/uncertainty reported separately. No automatic attendee invitations.

- [ ] Write stale-edit/source-disabled/unknown-recipient/no approval and repeated approval tests; prove fail.
- [ ] Implement durable transactional action claim with sending/creating → sent/created/uncertain outcomes and process-restart quarantine. Provider calls occur outside DB transactions, followed by revalidated results.
- [ ] Add server-local owner/dashboard secret/timezone settings and explicitly connected calendar IDs; fail closed on missing dashboard secret and report missing calendar/transport setup in UI.
- [ ] Mount router before public group catch-all. Create profile at authenticated local setup without enabling reminders. Wire local followups into learner and dashboard.
- [ ] Wire available-time draft/event controls into dashboard. State 'your calendar' for owner-only coverage, never 'both free' absent known coverage.
- [ ] Read current unfinished group plans through the existing Store, preserving existing autonomous-send rules and evidence; link draft actions to current plan version.
- [ ] Run integration HTTP/privacy/approval/uncertain-send tests and full suite; review diff for legacy group behavior.

## Task 5: Connected demo, local run, docs, structured commits

**Files:** Create `scripts/relationship_demo.py`, `tests/test_relationship_demo.py`; update `README.md`, `docs/demo.md`, `docs/relationship-setup.md`, `tasks/todo.md`.

- [ ] Write a connected test: overdue confirmed Mom contact → local dinner candidate/unfinished group plan → busy calendar blocks an early slot → later candidate slot → edited message draft → explicit current-version approval → exactly one simulated event. Prove fails first.
- [ ] Implement isolated temporary database demo and labeled fixtures; no real chat import or external send. Do not overwrite operational records or env.
- [ ] Verify no approval creates zero sends/events, approval replay dedupes, source edit invalidates candidate, calendar error remains unknown.
- [ ] Run full pytest, both demo smoke commands, diff whitespace checks and browser UI verification.
- [ ] Run the app locally and give the private dashboard URL with instructions to unlock; do not put its secret in a URL or response.
- [ ] Record actual live vs fixture functionality and remaining OAuth/sender/provider gaps.
- [ ] Commit reviewed components sequentially; push completed work to main under persistent user authorization. Do not include .env, operational DB, messages, attachments or generated portal artifacts.

## Separate open work

Deployment decision (2026-09-26): GitHub Actions → Vercel is deferred; deploy manually as needed. The current `rallyplans` production project serves the approved group archive and is refreshed by the Mac publisher. Any future standalone website must use a separate Vercel project and synthetic data. Private dashboard hosting and personal data synchronization are not authorized by approval of the public group archive. Dedicated sender topology is still unverified and is not a prerequisite for local dashboard/fixture event demo. See [Vercel deployment operations](../../vercel-deployment.md).

## Current execution status

Written plan approved; execution narrowed by explicit external teammate ownership. Root and subagents handle existing group runtime reliability and read-only integration review. No internal agent implements teammate-owned subsystems. Shared integration follows agreed external interfaces.
