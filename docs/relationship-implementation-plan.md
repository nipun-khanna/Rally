# Relationship Service Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if selected. Execute tasks in order and review the complete integration before live delivery.

**Goal:** Help the owner maintain relationships with private iMessage reminders and locally learned patterns from explicitly selected conversations.

**Architecture:** A separate relationship service shares the SQLite file and BlueBubbles transport, with its own tables and outbox. Personal requests are handled before planning or portal ingestion. A scoped importer supplies messaging evidence without exposing it to the portal or LLM.

**Tech Stack:** Python, SQLite, FastAPI, zoneinfo, existing BlueBubbles client; no new paid provider.

**Spec:** `docs/relationship-service-design.md`

## Global constraints

- Reminders go only to a configured private Rally conversation.
- Global archive reading stays disabled; learning sources require explicit selection.
- Personal records, source texts, and delivery activity are excluded from portal exports.
- Text activity never proves a call or visit occurred.
- Suggestions require explicit acceptance; no inferred schedule changes.
- Delivery uncertainty requires inspection rather than automatic resending.

## Review focus

1. Shared iMessage account: distinguish owner commands from Rally output without a reply loop.
2. Selected sources: prevent a disabled source's in-flight page from being committed.
3. Ambiguous dates and names: ask for clarification without state changes.
4. Restart during send: never duplicate a possibly delivered reminder.
5. Daylight saving and missed windows: reminders remain on local calendar rhythms.

## Task 1 — Private persistence and delivery cycles

**Create:** `app/relationships/store.py`, `app/relationships/schedule.py`, `tests/test_relationship_store.py`, `tests/test_relationship_schedule.py`.

Interfaces:

```python
class RelationshipStore:
    def __init__(self, path: Path): ...
    def configure(self, owner: str, destination: str, zone: str, hour: int = 18): ...
    def upsert(self, owner: str, label: str, mode: str, days: int, now: datetime): ...
    def list_relationships(self, owner: str) -> list[dict]: ...
    def confirm(self, owner: str, label: str, mode: str, at: datetime, event_id: str): ...
    def control(self, owner: str, label: str, action: str, now: datetime, until: datetime | None = None): ...
    def enqueue_due(self, now: datetime) -> int: ...
    def claim_delivery(self, now: datetime) -> dict | None: ...
    def finish_delivery(self, delivery_id: str, status: str, now: datetime): ...
```

- [ ] Write failing tests for per-owner isolation, case-insensitive label uniqueness, duplicate contact IDs, paused records, removed records, and distinct call/message channels.

```python
store.upsert('owner', 'Mom', 'call', 7, now)
store.confirm('owner', 'Mom', 'message', now, 'event1')
assert store.list_relationships('other') == []
assert store.list_relationships('owner')[0]['last_confirmed_at'] is None
assert store.enqueue_due(now + timedelta(days=7)) == 1
assert store.enqueue_due(now + timedelta(days=7)) == 0
```

- [ ] Run `python -m pytest tests/test_relationship_store.py tests/test_relationship_schedule.py -q` and verify initial failure.
- [ ] Implement tables for configuration, relationships, contact events, processed requests, learning sources, source texts, and personal outbox. Use transactions and unique `(owner, cycle_key)` outbox identity. Confirmation/cadence/snooze create a new generation; pause/removal cancel pending deliveries. Limit cadence to 1–90 days, hour to 0–23, validate IANA zone and direct-chat GUID.
- [ ] Compute deadlines by advancing local calendar dates. Eligible window is the configured hour through the end of that local day; missed windows defer to the next day. Unknown last contact uses creation date as the reminder anchor and asks whether contact happened.
- [ ] Snapshot destination/configuration revision on every outbox row. Reconfiguration cancels unsent old-destination rows. Immediately before transport, recheck generation, paused state, destination revision, and source eligibility. Once transport begins cancellation cannot guarantee recall; report the recorded outcome honestly.
- [ ] Persist `pending → sending → sent/rejected/uncertain` transitions. Recover `sending` at startup as `uncertain`; retry only a rejection proven to precede acceptance, at most three times with increasing delay. The existing BlueBubbles adapter treats all network/provider failures as uncertain: preserve that behavior and do not infer a safe rejection from an HTTP failure. Canceled deliveries cannot be claimed.
- [ ] Add a send-crash/restart test and DST boundary test, run task tests, then commit `feat: persist private relationship reminders`.

## Task 2 — Explicit personal requests

**Create:** `app/relationships/commands.py`, `app/relationships/service.py`, `tests/test_relationship_commands.py`.

Interfaces:

```python
def reply(store: RelationshipStore, owner: str, text: str,
          message_id: str, now: datetime) -> str: ...

class RelationshipService:
    def __init__(self, store: RelationshipStore, send_fn): ...
    def receive(self, message: ChatMessage) -> bool: ...
    def tick(self, now: datetime | None = None) -> int: ...
```

- [ ] Write failing tests for explicit setup (`Hey Rally, remind me to call Mom every week`), status, `I called Mom today`, cadence change, pause/resume/remove, and `snooze Mom until Friday`.
- [ ] Test unrecognized/ambiguous inputs return supported examples without changing data, duplicate request IDs cause one reply, unauthorized senders cannot read or change state, Rally-prefixed responses are ignored.
- [ ] Run `python -m pytest tests/test_relationship_commands.py -q` and verify initial failure.
- [ ] Implement deterministic supported phrases; parse dates in configured local zone (today, yesterday, next weekday, ISO date). Reject future contact confirmations, ambiguous labels, invalid frequencies, and past snoozes. Report precise accepted state. For private owner requests outside supported grammar, return help without invoking group Grok.
- [ ] Transactionally record command result and enqueue its acknowledgment once. Send only through the configured destination and dedicated outbox; no group Store writes.
- [ ] Run tests and commit `feat: handle personal relationship requests`.

## Task 3 — Selected-conversation learning

**Create:** `app/relationships/learning.py`, `tests/test_relationship_learning.py`.

Interfaces:

```python
class RelationshipLearner:
    def __init__(self, store: RelationshipStore, client: BlueBubblesHistoryClient): ...
    def import_page(self, owner: str, chat_id: str, limit: int = 100) -> int: ...
    def observe(self, payload: dict) -> None: ...
    def suggestion(self, owner: str, label: str) -> dict | None: ...
```

- [ ] Write failing tests for paginated full-history coverage, duplicate pages/webhooks, disabled and removed sources, four distinct outbound contact days, incoming-only messages, reactions, deleted messages, and Rally output.

```python
for day in (1, 8, 15, 22):
    # Fixture is an outbound human text from an enabled selected source.
    learner.observe(source_payload(day))
assert learner.suggestion('owner', 'Friend')['days'] == 7
assert learner.suggestion('owner', 'Mom') is None
```

- [ ] Run `python -m pytest tests/test_relationship_learning.py -q` and verify initial failure.
- [ ] Fetch only explicitly enabled GUIDs using the existing history client's ASC pagination. Persist cursor, source row count, coverage state, import errors, and last sync. Recheck source revision inside the write transaction so disabling during fetch prevents ingestion. Live messages update private source tables only. A full reconciliation scan runs in page-sized jobs with a scan generation: mark seen IDs, and retire missing evidence only after the scan completes. Mutable offset pagination cannot prove a consistent snapshot during concurrent edits; report coverage as an available-history scan rather than guaranteed completeness and run another scan after changes. On fetch failure never retire unseen rows or mark coverage complete.
- [ ] Normalize texts privately without attachments. Derive outbound owner contact dates and last messaging contact. Compute median gaps from at least four unique dates; clamp/round cadence to 1–90 days. Return sample size, source, channel and incomplete coverage marker. Do not suggest during incomplete initial import.
- [ ] Extend personal commands for `suggest cadence for Friend` and `accept cadence for Friend`; recompute the current suggestion on acceptance and reject call/visit relationships for message-derived suggestions. Also derive cadence suggestions from at least four confirmed events of the relationship's configured channel.
- [ ] Source removal deletes imported rows and derived evidence, cancels pending source-derived reminders, and preserves manually confirmed events. Disable stops observations/imports without deleting stored text. Verify this and commit `feat: learn relationship rhythms from selected texts`.
- [ ] Disabled-source evidence is excluded from active suggestions and deadline anchors. Enabled-source messaging contact advances only messaging relationships, cancels stale pending cycles, and preserves call/visit anchors. Test source disable/remove after an overdue reminder has been queued and test live contact arriving just before delivery.

## Task 4 — Setup, integration, and live verification

**Create:** `scripts/configure_relationships.py`, `tests/test_relationship_http.py`, `docs/relationship-setup.md`.
**Modify:** `app/bluebubbles.py`, `app/config.py`, `app/main.py`, `.env.example`, `README.md`, `tasks/todo.md`.

- [ ] Write failing HTTP tests using FastAPI TestClient: selected private owner request works, unselected direct chat stays ignored, unauthorized request stays ignored, personal data never reaches group tables/portal exports, disabled global history remains disabled while selected learning works.
- [ ] Extend `normalize_webhook(payload, allowed_direct_chat_ids=frozenset())` to accept only explicit private destinations. Preserve group behavior and all existing tests.
- [ ] Wire personal service before archive and group processing. Tick its scheduler beside the existing group scheduler. Observe selected-source webhook texts directly from validated payloads, independently of the destination-only direct-message normalizer; never route source messages into personal command handling unless they come from the configured destination.
- [ ] Add local CLI `configure`, `status`, `sources`, `add-source`, `disable-source`, `enable-source`, `remove-source`. Require direct destination, owner identity, time zone, reminder hour; selection requires exact GUID and relationship label. Status excludes secrets and text content. Configuration lives in private SQLite, not public portal settings. Read BlueBubbles credentials from existing environment with no output.
- [ ] Current-account configuration uses canonical owner `local-imessage-account`; an external owner must match the incoming BlueBubbles handle exactly. Test both paths and reject group destinations. Do not offer a group fallback that could later be exposed by full portal imports.
- [ ] Document shared-account limitations, exact supported requests, source removal behavior, personal setup, and how to inspect uncertain sends. No real message is sent by setup or status.
- [ ] Run the entire suite via `/opt/homebrew/Caskroom/miniconda/base/bin/python -m pytest -q`; inspect personal outbox recovery with a reopened database; verify exported portal lacks personal labels/text/activity.
- [ ] Configure a real private destination only after the user supplies/selects it. With the current shared iMessage account, a direct conversation still has another recipient; explain who will receive the reminder and obtain the exact destination rather than pretending a separate bot contact already exists. Confirm BlueBubbles/Messages health. Send one labeled test reminder there, verify its actual thread receipt, then restore its test state. Record any external blocker explicitly.
- [ ] Commit verified integration and push to the authorized GitHub remote. Update checklist with test counts, live evidence, and remaining configuration requirements.

## Execution recommendation

Use native execution with a final independent review. The four tasks depend on
the same ownership and outbox interfaces, so maintaining one implementation context
reduces integration mistakes. A private conversation GUID and selected learning
sources are runtime setup inputs; absent these, code tests can run but live personal
delivery cannot be claimed verified.
