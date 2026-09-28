# Bounded Pending Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover one ordered prefix of at most 200 stored messages starting at the oldest pending human row, and mark processed only the pending human ids inside that prefix after extraction succeeds.

**Architecture:** `Store.recovery_snapshot` selects the oldest pending human row by `(sent_at, message_id)` and returns the following ordered prefix. `RallyService.recover_pending` drops any pending id that is not in that prefix, calls the extractor only when at least one such id remains, and marks those ids only after `extract` returns. `scripts/recover_pending.py` rejects `run` without `--apply` and rejects a limit outside 1 through 200 before it loads settings or builds the service.

**Tech Stack:** Python, sqlite3, pytest, the existing `RallyService` extractor seam.

**Spec:** `docs/demo-state-audit.md` section "Unprocessed rows — 2026-09-27 follow-up".

## Global Constraints

- Own only `scripts/recover_pending.py`, the recovery helper (`app/store.py` `recovery_snapshot` and `app/orchestrator.py` `recover_pending`), `tests/test_recovery.py`, this plan, and `docs/recovery-demo-check.md`.
- Do not edit browser files, `app/main.py`, or docs owned by other demo work.
- Do not mutate the production database, send stored text to a model, place calls, send texts, or deploy.
- Do not mark a pending row processed merely because it has a `direct_reply`.
- Preserve chronological extraction order, plan versioning, and the failure path that acks nothing.
- Cap the prefix at 200. Keep the default prefix at 75.
- `run` calls the extractor only with explicit `--apply`.
- Do not commit. Preserve unrelated dirty work.
- If auto-review rejects a command, report the rejection. Do not request a bypass.

## Runtime retry diagnosis (do not implement)

Normal runtime does not need an automatic pending retry in this change. `build_service` defers extraction to one thread-pool job. `app/main.py` `periodic` calls `service.tick` and `deliver_pending`. `tick` expires proposals, books an already approved proposal, intervenes, revives stalls, and delivers the outbox. It does not call `receive` or `recover_pending`.

The audited backlog is residual: 70 rows are `attempts=0` / `not_recorded`, so the failure recorder never ran, and 13 of those already have a sent `direct_reply` whose plan extract never finished. Re-entering `receive` can send another reply or treat old approval text as a new booking. A scheduler extract would transmit stored group text without `--apply`. Leave `app/main.py` unchanged.

---

### Task 1: Prefix recovery

**Files:**
- Modify: `app/store.py` `recovery_snapshot`
- Modify: `app/orchestrator.py` `recover_pending`
- Test: `tests/test_recovery.py`

**Interfaces:**
- Consumes: `Store.recovery_snapshot(chat_id, limit) -> tuple[list[ChatMessage], list[str]]`
- Produces: the same return shape. The message list is the ordered prefix. The id list is pending human ids inside that prefix only.

- [x] **Step 1: Write the failing tests**

Replace `test_recovery_refuses_partial_snapshot` with tests that expect a prefix, a later replied row left pending, a failed extract that acks nothing, the default of 75, and the cap of 200.

- [x] **Step 2: Run the new tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_recovery.py -q`

Expected: prefix tests fail because the snapshot still raises `Pending conversation exceeds bounded recovery window`.

- [x] **Step 3: Implement the prefix**

`recovery_snapshot` keeps `ValueError` for limits outside 1 through 200. It no longer raises when more rows exist after the prefix. `recover_pending` intersects pending ids with the message ids it will extract, returns 0 before calling the extractor when that list is empty, and still calls `mark_processed_many` only after `extract` returns.

- [x] **Step 4: Re-run `tests/test_recovery.py`**

Expected: the prefix tests pass, and the older recovery tests still pass.

### Task 2: CLI guards

**Files:**
- Modify: `scripts/recover_pending.py`
- Test: `tests/test_recovery.py`

**Interfaces:**
- Consumes: `main(argv) -> int`
- Produces: `SystemExit(2)` for `run` without `--apply` and for `--limit` outside 1 through 200, before `Settings.from_env` or `build_service`.

- [x] **Step 1: Write the failing CLI tests**

Patch `Settings.from_env` and `build_service` so either call raises `AssertionError`. Expect `SystemExit(2)` instead.

- [x] **Step 2: Run those tests and confirm they fail**

Expected: `AssertionError` from settings load, because the guards currently run after `Settings.from_env`.

- [x] **Step 3: Move the guards above settings load**

- [x] **Step 4: Re-run `tests/test_recovery.py`**

Expected: pass.

### Task 3: Evidence

**Files:**
- Create: `docs/recovery-demo-check.md`

- [x] Record the retry diagnosis, the prefix contract, the pytest result, and confirmation that production data, models, calls, texts, and deploy were not touched.
